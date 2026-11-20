"""Core 0.6.0 verification-first wiring through the Codex CLI and hook surfaces.

Mechanism may withhold; only a model may grant. These tests prove the adapter
only declares, runs, records, withholds and surfaces: it never marks a
requirement satisfied, dismisses evidence or closes by itself. They exercise
the emitted contract with real-shaped hook payloads, not a live Codex Host.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib
import types

import pytest

from thaliris import core
from thaliris_codex import (
    cli, codex_adapter, controller_instructions, lifecycle, observation_transport, roles, task_authority,
)
from tests.test_evidence_continuity_adapter import (
    evidence_task, _event, _identity, _invoke_hook_command, _selected_message, _spawn,
)

OWNER = "evidence-controller-session"
PASSING = [sys.executable, "-c", "raise SystemExit(0)"]
FAILING = [sys.executable, "-c", "raise SystemExit(3)"]
REPOSITORY = Path(__file__).resolve().parents[1]


def _run(root: Path, task_id: str, capsys, *argv: str) -> tuple[int, dict]:
    capsys.readouterr()
    code = cli.main(["--root", str(root), "--task-id", task_id, *argv])
    return code, json.loads(capsys.readouterr().out)


def _state(root: Path) -> dict:
    return core.task_show(root)["state"]


def _revision(root: Path) -> int:
    return _state(root)["revision"]


def _register(root: Path, task_id: str, capsys, *requirements: dict) -> dict:
    code, out = _run(root, task_id, capsys, "task-evidence-register", "--role", "controller",
                     "--base-revision", str(_revision(root)), "--json", json.dumps({"requirements": list(requirements)}))
    assert code == 0, out
    return out


def _declare(root: Path, task_id: str, capsys, check: dict, *extra: str) -> tuple[int, dict]:
    return _run(root, task_id, capsys, "task-check", "--role", "controller",
                "--base-revision", str(_revision(root)), "--json", json.dumps(check), *extra)


def _check(identifier: str = "C1", refs: tuple[str, ...] = ("R1",), command: list[str] | None = None) -> dict:
    return {"id": identifier, "requirement_refs": list(refs), "command": command or PASSING, "timeout_s": 120}


def _local_fact(root: Path, identifier: str = "O-local", requirement: str = "R1") -> str:
    """One Controller-local observation, so a judgment has an exact observation to cite."""
    body = {"id": identifier, "base_revision": _revision(root), "candidate": "C1", "requirement_refs": [requirement],
            "source_refs": ["S-" + identifier],
            "sources": [{"id": "S-" + identifier, "kind": "test", "locator": "tests/result.txt", "summary": "local check"}],
            "text": "The Controller observed this selected fact."}
    out = codex_adapter.task_observe(root, "controller", None, None, observation_json=json.dumps(body),
                                     controller_session_id_hash=lifecycle._identity_hash(OWNER))
    assert out["ok"]
    return identifier


def _judge(root: Path, task_id: str, capsys, identifier: str, requirement: str, refs: list[str], *extra: str,
           outcome: str = "satisfied") -> tuple[int, dict]:
    judgment = {"id": identifier, "candidate": "C1", "requirement_ref": requirement, "observation_refs": refs,
                "outcome": outcome, "reasoning": "The cited observation was reviewed for this candidate."}
    return _run(root, task_id, capsys, "task-judge", "--role", "controller", "--base-revision", str(_revision(root)),
                "--json", json.dumps(judgment), *extra)


def _child_record(root: Path, task_id: str, agent: str) -> dict:
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    return next(item for item in ledger["children"] if item.get("agent_id_hash") == lifecycle._identity_hash(agent))


def _handoff(root: Path, handoff_id: str) -> dict:
    return next(item for item in _state(root)["evidence_continuity"]["handoffs"] if item["id"] == handoff_id)


def _claims(*claims: dict) -> str:
    return "Final report with the full findings.\n\n```thaliris-claims\n" + json.dumps({"claims": list(claims)}) + "\n```\n"


def _claim(polarity: str, text: str, requirement: str = "R1", evidence: str = "src/parser.py:10") -> dict:
    return {"requirement": requirement, "polarity": polarity, "text": text, "evidence": evidence, "basis": "read"}


def _stop(child: dict, message: object = None, **extra: object) -> dict:
    payload = {**child, "hook_event_name": "SubagentStop", "model": "gpt-6-luna", "stop_hook_active": False, **extra}
    if message is not None:
        payload["last_assistant_message"] = message
    return payload


def _list_agents(root: Path, *entries: tuple[str, object]) -> str:
    return lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="list_agents", tool_response={"agents": [
        {"agent_name": f"/root/{agent}", "agent_status": status} for agent, status in entries]}))


def _packet(raw: str) -> tuple[str, dict]:
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    return context, json.loads(context.splitlines()[-1])


@pytest.fixture
def typed_task(evidence_task, capsys):
    """A delegated task with one compiled requirement (R1) and one judgment-only requirement (R2)."""
    root, task_id = evidence_task
    _register(root, task_id, capsys, {"id": "R1", "workchain_ref": "opaque-1", "kind": "compiled"},
              {"id": "R2", "workchain_ref": "opaque-2"})
    return root, task_id


@pytest.fixture
def adaptive_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """A quick adaptive admission: boundary and invariants are omitted."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    home = tmp_path / "isolated-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = home / "agents" / name
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path.parent / (tmp_path.name + "-task-authority"))
    codex_adapter.init(tmp_path)
    task_id = core.task_start(tmp_path, "small adaptive change", None, None)["task_id"]
    core.select_task(tmp_path, task_id)
    owner_hash = hashlib.sha256(OWNER.encode()).hexdigest()
    task_authority.establish(tmp_path, core._load_state(tmp_path), {
        "human_instruction": "Fix the small thing quickly", "acceptance": "The small thing is fixed",
        "execution_mode": "adaptive", "write_surface": ["src/**"],
    }, owner_hash)
    lifecycle.record_task_start_owner(tmp_path, task_id, owner_hash)
    return tmp_path, task_id


# --- CLI: declare, verify, withhold, override -----------------------------------------------------

def test_typed_requirement_is_registered_and_an_unchecked_compiled_one_withholds(typed_task, capsys):
    root, task_id = typed_task
    state = _state(root)
    assert state["schema_version"] == core._STATE_SCHEMA_VERSION
    stored = {item["id"]: item for item in state["evidence_continuity"]["requirements"]}
    assert stored["R1"]["kind"] == "compiled" and "kind" not in stored["R2"]
    assert task_authority.check(root) is not None
    observation = _local_fact(root)
    code, refused = _judge(root, task_id, capsys, "J1", "R1", [observation])
    assert code == 2 and refused["code"] == "VERIFICATION_WITHHELD"
    assert refused["details"]["withheld"][0]["checks"][0]["reason"] == "no-declared-check"
    assert refused["Verification"]["uncovered_requirements"] == ["R1"]
    assert not _state(root)["evidence_continuity"]["judgments"]
    # A judgment-only requirement is not gated: only the model's judgment decides it.
    second = _local_fact(root, "O-second", "R2")
    code, accepted = _judge(root, task_id, capsys, "J2", "R2", [second])
    assert code == 0 and accepted["ok"], accepted


def test_controller_declares_verifies_and_the_gate_withholds_until_green_or_overridden(typed_task, capsys):
    root, task_id = typed_task
    code, declared = _declare(root, task_id, capsys, _check(command=FAILING))
    assert code == 0 and declared["declared"] == ["C1"], declared
    assert declared["Verification"]["unrun"] == 1 and declared["Verification"]["withheld_requirements"] == ["R1"]
    assert task_authority.check(root) is not None  # the declaration is anchored
    code, duplicate = _declare(root, task_id, capsys, _check(command=PASSING))
    assert code == 2 and duplicate["code"] == "CHECK_ALREADY_DECLARED"
    code, invalid = _declare(root, task_id, capsys, {"id": "bad id", "requirement_refs": ["R1"], "command": PASSING})
    assert code == 2 and invalid["code"] == "CHECK_INVALID"
    observation = _local_fact(root)

    revision = _revision(root)
    code, withheld = _judge(root, task_id, capsys, "J1", "R1", [observation])
    assert code == 2 and withheld["code"] == "VERIFICATION_WITHHELD" and _revision(root) == revision
    assert withheld["details"]["withheld"][0]["checks"][0] == {"id": "C1", "status": "unrun"}

    code, red = _run(root, task_id, capsys, "task-verify", "--role", "controller", "--check", "C1")
    assert code == 0 and red["result"]["outcome"] == "FAIL" and red["result"]["status"] == "red", red
    assert red["result"]["exit_code"] == 3 and "evidence" in red and red["Verification"]["red"] == 1
    assert core.task_get(root, "C1.r1")["object"]["observed_by"] == "controller"
    assert task_authority.check(root) is not None  # the result is anchored with its write
    code, withheld = _judge(root, task_id, capsys, "J1", "R1", [observation])
    assert code == 2 and withheld["code"] == "VERIFICATION_WITHHELD"

    code, empty = _judge(root, task_id, capsys, "J1", "R1", [observation], "--override-reason", "  ")
    assert code == 2 and empty["code"] == "VERIFICATION_OVERRIDE_INVALID"
    assert not _state(root)["evidence_continuity"]["judgments"]
    code, overridden = _judge(root, task_id, capsys, "J1", "R1", [observation], "--override-reason", "flaky fixture, verified by hand")
    assert code == 0 and overridden["ok"], overridden
    judgment = core.task_get(root, "J1")["object"]
    assert judgment["override_reason"] == "flaky fixture, verified by hand"
    assert [item["id"] for item in judgment["overridden_checks"]] == ["C1"]
    assert task_authority.check(root) is not None

    # Superseding is how the Controller accepts changed check content; the old result is then not fresh.
    code, superseded = _declare(root, task_id, capsys, _check(command=PASSING), "--supersede")
    assert code == 0 and superseded["checks"][0]["declaration"] == 2
    code, green = _run(root, task_id, capsys, "task-verify", "--role", "controller", "--check", "C1",
                       "--base-revision", str(_revision(root)))
    assert code == 0 and green["result"]["status"] == "green" and green["result"]["fresh"] is True, green
    # Green grants nothing: no judgment appeared; the model still judges.
    assert [item["id"] for item in _state(root)["evidence_continuity"]["judgments"]] == ["J1"]
    code, satisfied = _judge(root, task_id, capsys, "J2", "R1", [observation])
    assert code == 0 and "override_reason" not in core.task_get(root, "J2")["object"], satisfied

    code, closed = _run(root, task_id, capsys, "task-close", "--base-revision", str(_revision(root)))
    assert code == 0 and closed["status"] == "DONE" and closed["closure"]["gate"] == "clear", closed
    assert closed["closure"]["by"] == "controller"
    # Judgment-only requirements are surfaced at close with their latest judgment (none here).
    assert closed["surfaced"] == [{"requirement": "R2", "kind": "judgment-only", "latest_judgment": None}]
    assert "Verification" not in closed  # a closed task no longer re-presents standing lines


def test_close_is_withheld_until_the_controller_records_an_override(typed_task, capsys):
    root, task_id = typed_task
    assert _declare(root, task_id, capsys, _check(command=FAILING))[0] == 0
    revision = _revision(root)
    code, withheld = _run(root, task_id, capsys, "task-close", "--base-revision", str(revision))
    assert code == 2 and withheld["code"] == "VERIFICATION_WITHHELD" and withheld["details"]["operation"] == "close"
    assert _state(root)["status"] == "ACTIVE" and _revision(root) == revision
    assert task_authority.check(root) is not None  # a refusal writes nothing
    code, invalid = _run(root, task_id, capsys, "task-close", "--base-revision", str(revision), "--override-reason", "")
    assert code == 2 and invalid["code"] == "VERIFICATION_OVERRIDE_INVALID" and _state(root)["status"] == "ACTIVE"
    code, closed = _run(root, task_id, capsys, "task-close", "--base-revision", str(revision),
                        "--override-reason", "the user accepted shipping without this check")
    assert code == 0 and closed["status"] == "DONE", closed
    assert closed["closure"]["gate"] == "overridden"
    assert closed["closure"]["override_reason"] == "the user accepted shipping without this check"
    assert [item["id"] for item in closed["closure"]["overridden_checks"]] == ["C1"]
    assert {item["requirement"] for item in closed["surfaced"]} == {"R2"}


def test_check_and_verify_actor_rules_at_the_cli_boundary(typed_task, capsys):
    root, task_id = typed_task
    code, refused = _run(root, task_id, capsys, "task-check", "--role", "implementer", "--base-revision", str(_revision(root)),
                         "--json", json.dumps(_check()))
    assert code == 2 and refused["error"] == "only Controller may perform this operation"
    assert "checks" not in _state(root)
    assert _declare(root, task_id, capsys, _check())[0] == 0
    code, missing = _run(root, task_id, capsys, "task-verify", "--role", "controller", "--check", "C-absent")
    assert code == 2 and missing["code"] == "CHECK_NOT_FOUND"
    code, mixed = _run(root, task_id, capsys, "task-verify", "--role", "controller", "--check", "C1", "--handoff-id", "handoff-x")
    assert code == 2 and "takes no handoff" in mixed["error"]
    # A role label alone is no identity: a child needs its exact live handoff binding.
    code, unbound = _run(root, task_id, capsys, "task-verify", "--role", "implementer", "--check", "C1")
    assert code == 2 and "exact live native handoff producer" in unbound["error"]
    code, stale = _run(root, task_id, capsys, "task-verify", "--role", "controller", "--check", "C1", "--base-revision", "1")
    assert code == 2 and stale["code"] == "TASK_REVISION_CONFLICT"
    assert not [item for item in _state(root)["verification_results"] if "check_id" in item]


def test_bound_children_verify_as_their_handoff_and_cannot_declare(typed_task, capsys):
    root, task_id = typed_task
    assert _declare(root, task_id, capsys, _check())[0] == 0
    child, handoff = _spawn(root, "implementer", "verify-implementer", marker=_selected_message("C1"))
    reviewer, review_handoff = _spawn(root, "reviewer", "verify-reviewer", marker=_selected_message("C1"))
    prefix = f'thaliris --root "{root}" '

    denied, _ = _invoke_hook_command(root, child, prefix + "task-check --role implementer --base-revision 1 --json '{}'")
    assert "THALIRIS_ROLE_SESSION_CONTROL_STATE_MUTATION" in denied
    denied, _ = _invoke_hook_command(root, child, prefix + "task-verify --role controller --check C1")
    assert "THALIRIS_EVIDENCE_PRODUCER_CONFLICT" in denied
    denied, _ = _invoke_hook_command(root, child, prefix + "task-verify --role implementer --check C1 --agent-id-hash " + "0" * 64)
    assert "THALIRIS_EVIDENCE_PRODUCER_CONFLICT" in denied
    stranger = {**child, "agent_id": "never-started"}
    denied, _ = _invoke_hook_command(root, stranger, prefix + "task-verify --role implementer --check C1")
    assert "deny" in denied
    # A readonly role may record a declared check's result, but a redirect is still a write.
    denied, _ = _invoke_hook_command(root, reviewer, prefix + "task-verify --role reviewer --check C1 > out.txt", readonly=True)
    assert "deny" in denied

    for actor, role, selected, agent in ((child, "implementer", handoff, "verify-implementer"),
                                         (reviewer, "reviewer", review_handoff, "verify-reviewer")):
        raw, _ = _invoke_hook_command(root, actor, prefix + f"task-verify --role {role} --check C1", readonly=role == "reviewer")
        updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
        assert f"--task-id {task_id}" in updated and f"--handoff-id {selected}" in updated
        assert f"--agent-id-hash {lifecycle._identity_hash(agent)}" in updated
        tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
        capsys.readouterr()
        assert cli.main(tokens[1:]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["result"]["status"] == "green" and "evidence" not in result and "Verification" not in result
        assert core.task_get(root, result["result"]["id"])["object"]["observed_by"] == "handoff:" + selected
        assert task_authority.check(root) is not None

    # The exact binding is checked again at the CLI: a wrong actor or an ended child records nothing.
    results = len(_state(root)["verification_results"])
    with pytest.raises(ValueError, match="exact live native handoff producer"):
        codex_adapter.task_verify(root, "implementer", "C1", handoff, lifecycle._identity_hash("verify-reviewer"))
    with pytest.raises(ValueError, match="exact live native handoff producer"):
        codex_adapter.task_verify(root, "reviewer", "C1", handoff, lifecycle._identity_hash("verify-implementer"))
    _list_agents(root, ("verify-implementer", {"completed": "done"}))
    with pytest.raises(ValueError, match="exact live native handoff producer"):
        codex_adapter.task_verify(root, "implementer", "C1", handoff, lifecycle._identity_hash("verify-implementer"))
    assert len(_state(root)["verification_results"]) == results


def test_a_ledger_edit_during_a_check_run_is_refused_and_never_anchored(typed_task, capsys, monkeypatch):
    root, task_id = typed_task
    assert _declare(root, task_id, capsys, _check())[0] == 0
    run_declared_check = core._run_declared_check

    def edited_during_run(checked_root, declaration):
        run = run_declared_check(checked_root, declaration)
        path = core._state_path(root)
        path.write_bytes(path.read_bytes() + b"\n")
        return run

    monkeypatch.setattr(core, "_run_declared_check", edited_during_run)
    with pytest.raises(ValueError, match="TASK_AUTHORITY_STATE_CHANGED"):
        codex_adapter.task_verify(root, "controller", "C1")
    # No result was appended and the changed bytes were not checkpointed over.
    with pytest.raises(ValueError, match="TASK_AUTHORITY_STATE_CHANGED"):
        task_authority.check(root)
    assert not [item for item in _state(root)["verification_results"] if "check_id" in item]


def test_typed_requirement_registers_together_with_a_dispatch_selection(evidence_task):
    root, _task_id = evidence_task
    assert _state(root)["schema_version"] == core._STATE_SCHEMA_VERSION
    source = root.parent / (root.name + "-typed-selection.json")
    source.write_text(json.dumps({
        "requirements": [{"id": "R7", "workchain_ref": "opaque", "kind": "partial", "surface": "contract"}],
        "next_dispatch": {"role": "implementer", "expected_agent_type": "thaliris-implementer", "candidate": "C1",
                          "requirement_refs": ["R7"]}}), encoding="utf-8")
    out = codex_adapter.task_evidence_register(root, "controller", _revision(root), str(source),
                                               lifecycle._identity_hash(OWNER))
    assert out["ok"] and out["next_dispatch"]["requirement_refs"] == ["R7"]
    state = _state(root)
    assert state["schema_version"] == core._STATE_SCHEMA_VERSION
    assert state["evidence_continuity"]["requirements"] == [
        {"id": "R7", "workchain_ref": "opaque", "kind": "partial", "surface": "contract"}]
    assert task_authority.check(root) is not None


def test_task_check_inline_json_uses_the_literal_transport(typed_task):
    root, task_id = typed_task
    assert observation_transport.INLINE_OPTIONS["task-check"] == "--json"
    command = (f'thaliris --root "{root}" --task-id {task_id} task-check --role controller --base-revision 3 '
               "--json '" + json.dumps({"id": "C1", "requirement_refs": ["R1"], "command": ["git", "apply", "--check"]}) + "'")
    raw = lifecycle.handle_hook(root, "PreToolUse", _event(tool_name="Bash", tool_input={"command": command}))
    updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
    assert "utf8-base64:" in updated and "git" not in updated.split("task-check", 1)[1]


# --- typed claims at SubagentStop -----------------------------------------------------------------

def test_stop_ingests_typed_claims_of_the_exact_handoff_once(typed_task):
    root, task_id = typed_task
    child, handoff = _spawn(root, "implementer", "claims-implementer", marker=_selected_message("C1"))
    message = _claims(_claim("contradicts", "Empty rows are dropped by the parser."),
                      _claim("supports", "The round trip holds for the sample.", evidence="C1"),
                      _claim("unknown", "Concurrent writers were not exercised.", requirement="R2"))
    revision = _revision(root)
    assert lifecycle.handle_hook(root, "SubagentStop", _stop(child, message)) == ""
    state = _state(root)
    assert state["revision"] == revision + 1  # one hook observation, one revision
    marker = _handoff(root, handoff)["claims"]
    assert marker["status"] == "present" and marker["total"] == 3
    assert marker["supports"] == [{"requirement": "R1", "evidence": "C1", "basis": "read"}]
    adverse = core.task_get(root, handoff + ".c1")["object"]
    assert adverse["producer"] == "handoff:" + handoff and adverse["claim"]["polarity"] == "contradicts"
    assert adverse["requirement_refs"] == ["R1"] and adverse["text"] == "Empty rows are dropped by the parser."
    # A claim about a requirement outside the handoff's refs stays unassigned evidence.
    assert core.task_get(root, handoff + ".c2")["object"]["requirement_refs"] == []
    assert task_authority.check(root) is not None  # ingested under the lock and checkpointed
    record = _child_record(root, task_id, "claims-implementer")
    assert record["stop_observed"] and record["claim_ingest"] == {
        "source": "SubagentStop", "claims": "present", "usage": "recorded", "message": "PRESENT"}
    # The adverse claim is an ordinary open obligation; nothing was judged or dismissed for the model.
    summary = core.evidence_summary(state)
    assert {item["observation_id"] for item in summary["unincorporated"]} == {handoff + ".c1", handoff + ".c2"}
    assert not state["evidence_continuity"]["judgments"]

    # A repeated Stop, and the same text arriving again as a native result, change nothing.
    assert lifecycle._record_subagent_stop(root, _stop(child, message)) is False
    _list_agents(root, ("claims-implementer", {"completed": message}))
    after = _state(root)
    assert len(after["evidence_continuity"]["observations"]) == 2
    assert _handoff(root, handoff)["claims"] == marker
    assert _child_record(root, task_id, "claims-implementer")["claim_ingest"]["claims"] == "present"


@pytest.mark.parametrize("message, status", [
    ("Final report.\n\n```thaliris-claims\nnone\n```\n", "present"),
    ("Final report without any block.", "missing"),
    ("Final report.\n\n```thaliris-claims\n{not json\n```\n", "malformed"),
    (None, "missing"),
])
def test_stop_records_core_markers_and_invents_no_claims(typed_task, message, status):
    root, task_id = typed_task
    child, handoff = _spawn(root, "investigator", "marker-investigator", marker=_selected_message("C1"))
    assert lifecycle._record_subagent_stop(root, _stop(child, message)) is True
    marker = _handoff(root, handoff)["claims"]
    assert marker["status"] == status
    assert not _state(root)["evidence_continuity"]["observations"]
    assert marker.get("supports", []) == [] and marker.get("observations", []) == []
    record = _child_record(root, task_id, "marker-investigator")
    assert record["claim_ingest"]["claims"] == status
    assert record["claim_ingest"]["message"] == ("ABSENT" if message is None else "PRESENT")
    assert task_authority.check(root) is not None
    section = cli._task_status(root, suppress_protocol_notice=True)["Claims"]
    assert section["handoffs_without_typed_claims"]["total"] == (0 if status == "present" else 1)


def test_stop_without_an_exact_child_and_handoff_ingests_nothing(typed_task):
    root, task_id = typed_task
    message = _claims(_claim("contradicts", "This must not be recorded for a stranger."))
    child, handoff = _spawn(root, "investigator", "exact-investigator", marker=_selected_message("C1"))
    revision = _revision(root)
    assert lifecycle._record_subagent_stop(root, _stop({**child, "turn_id": "another-turn"}, message)) is False
    assert lifecycle._record_subagent_stop(root, _stop({**child, "agent_id": "another-agent"}, message)) is False
    assert lifecycle._record_subagent_stop(root, _stop({**child, "agent_type": "thaliris-reviewer"}, message)) is False
    assert _revision(root) == revision and "claims" not in _handoff(root, handoff)
    lifecycle._record_subagent_stop(root, _stop(child, "ends this child"))

    # A bound child whose handoff has no evidence association: the Stop is kept, nothing is guessed.
    opaque, opaque_handoff = _spawn(root, "investigator", "opaque-investigator")
    revision = _revision(root)
    assert lifecycle._record_subagent_stop(root, _stop(opaque, message)) is True
    assert _revision(root) == revision
    assert opaque_handoff not in {item["id"] for item in _state(root)["evidence_continuity"]["handoffs"]}
    record = _child_record(root, task_id, "opaque-investigator")
    assert record["stop_observed"] and "claim_ingest" not in record
    assert len(_state(root)["evidence_continuity"]["observations"]) == 0


def test_an_ingest_or_write_failure_degrades_to_a_diagnostic_and_keeps_the_stop(typed_task, monkeypatch):
    root, task_id = typed_task
    message = _claims(_claim("contradicts", "A finding that could not be stored."))
    child, handoff = _spawn(root, "implementer", "failing-implementer", marker=_selected_message("C1"))

    def refuse(*_args, **_kwargs):
        raise core.ThalirisError("TASK_STATE_CAPACITY_EXCEEDED", "observations are full")

    # Scope only the refusal: monkeypatch.undo() would also revert the fixture's
    # isolated CODEX_HOME/THALIRIS_HOME and task-authority directory, so the
    # rest of the test would depend on the developer machine's Host profiles.
    with monkeypatch.context() as refusal:
        refusal.setattr(core, "ingest_claims", refuse)
        assert lifecycle.handle_hook(root, "SubagentStop", _stop(child, message)) == ""
        record = _child_record(root, task_id, "failing-implementer")
        assert record["stop_observed"] and record["claim_ingest"]["claims"] == "error:TASK_STATE_CAPACITY_EXCEEDED"
        assert record["claim_ingest"]["usage"] == "recorded" and "claims" not in _handoff(root, handoff)
        assert task_authority.check(root) is not None
        # The failed ingest is surfaced to the Controller instead of vanishing.
        context, packet = _packet(lifecycle._controller_evidence_context(root, _event(tool_name="Bash", tool_response="ok")))
        assert packet["Claims"]["ingest_errors"] == [{"handoff_id": handoff, "claims": "error:TASK_STATE_CAPACITY_EXCEEDED"}]
        assert "could not be recorded" in context

    assert os.environ["CODEX_HOME"] == str(root / "isolated-codex-home")
    second, second_handoff = _spawn(root, "investigator", "unwritable-investigator", marker=_selected_message("C1"))

    def unwritable(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(lifecycle, "_write_evidence_reservation", unwritable)
    assert lifecycle._record_subagent_stop(root, _stop(second, message)) is True
    record = _child_record(root, task_id, "unwritable-investigator")
    assert record["stop_observed"] and record["claim_ingest"]["claims"] == "error:OSError"
    assert "claims" not in _handoff(root, second_handoff) and task_authority.check(root) is not None


# --- terminal reconciliation and usage ------------------------------------------------------------

def test_terminal_completed_text_with_a_claim_block_is_ingested_best_effort(typed_task):
    root, task_id = typed_task
    _first, first = _spawn(root, "investigator", "terminal-with-block", marker=_selected_message("C1"))
    # A distinct dispatch needs the first one bound; both are then live together.
    _second, second = _spawn(root, "investigator", "terminal-plain", marker=_selected_message("C1"))
    message = _claims(_claim("unknown", "The migration path was not run."))
    revision = _revision(root)
    _list_agents(root, ("terminal-with-block", {"completed": message}), ("terminal-plain", {"completed": "A plain summary."}))
    state = _state(root)
    assert state["revision"] == revision + 1  # both children of one snapshot share one revision
    assert _handoff(root, first)["claims"]["status"] == "present"
    assert core.task_get(root, first + ".c1")["object"]["claim"]["polarity"] == "unknown"
    # Text without a block may be a partial snapshot: no marker is invented from it.
    assert "claims" not in _handoff(root, second)
    for handoff in (first, second):
        usage = _handoff(root, handoff)["usage"]
        assert usage["outcome"] == "completed" and usage["model"] is None  # the observer's model is not the child's
    assert _child_record(root, task_id, "terminal-with-block")["claim_ingest"] == {
        "source": "list_agents", "claims": "present", "usage": "recorded", "message": "PRESENT"}
    assert _child_record(root, task_id, "terminal-plain")["claim_ingest"]["claims"] == "skipped"
    assert task_authority.check(root) is not None
    # Unchanged later snapshots write nothing.
    _list_agents(root, ("terminal-with-block", {"completed": message}), ("terminal-plain", {"completed": "A plain summary."}))
    assert _revision(root) == revision + 1


@pytest.mark.parametrize("tool, key", [("interrupt_agent", "target"), ("close_agent", "id")])
def test_control_snapshots_carry_a_completed_claim_block(typed_task, tool, key):
    root, _task_id = typed_task
    _child, handoff = _spawn(root, "investigator", "controlled", marker=_selected_message("C1"))
    message = _claims(_claim("contradicts", "The cache is never invalidated."))
    lifecycle.handle_hook(root, "PostToolUse", _event(
        tool_name=tool, tool_input={key: "/root/controlled"}, tool_response={"previous_status": {"completed": message}}))
    assert _handoff(root, handoff)["claims"]["status"] == "present"
    assert _handoff(root, handoff)["usage"]["outcome"] == "completed"
    assert core.task_get(root, handoff + ".c1")["object"]["claim"]["polarity"] == "contradicts"
    assert task_authority.check(root) is not None


def test_a_v1_wait_status_map_carries_a_completed_claim_block(typed_task):
    root, task_id = typed_task
    model, effort = roles.ROLE_MODEL_ROUTING_DEFAULTS["investigator"]
    request = {**_event(), "tool_name": "spawn_agent", "tool_input": {
        "agent_type": "thaliris-investigator", "fork_turns": "none", "message": _selected_message("C1"),
        "model": model, "reasoning_effort": effort}}
    decision = lifecycle.handle_hook(root, "PreToolUse", request)
    assert not decision or json.loads(decision)["hookSpecificOutput"].get("permissionDecision") != "deny", decision
    # A V1 Host returns the spawned thread id and keys its wait status map by it.
    lifecycle.handle_hook(root, "PostToolUse", {**request, "tool_response": {"agent_id": "v1-thread", "nickname": None}})
    assert lifecycle._record_subagent_start(root, _identity("investigator", "v1-thread"))
    handoff = _child_record(root, task_id, "v1-thread")["handoff_id"]
    message = _claims(_claim("unknown", "The retry path was not observed."))
    lifecycle.handle_hook(root, "PostToolUse", _event(
        tool_name="wait_agent", tool_input={"targets": ["v1-thread"]},
        tool_response={"status": {"v1-thread": {"completed": message}}, "timed_out": False}))
    assert _handoff(root, handoff)["claims"]["status"] == "present"
    usage = _handoff(root, handoff)["usage"]
    assert usage["outcome"] == "completed" and usage["effort"] == effort and usage["model"] is None
    assert _child_record(root, task_id, "v1-thread")["claim_ingest"]["source"] == "wait_agent"


def test_usage_records_only_observable_facts_and_leaves_tokens_unknown(typed_task):
    root, task_id = typed_task
    child, handoff = _spawn(root, "implementer", "usage-implementer", marker=_selected_message("C1"))
    effort = roles.ROLE_MODEL_ROUTING_DEFAULTS["implementer"][1]
    lifecycle._record_subagent_stop(root, _stop(child, "Final report.\n\n```thaliris-claims\nnone\n```\n", model="gpt-6-terra"))
    usage = _handoff(root, handoff)["usage"]
    assert usage["model"] == "gpt-6-terra" and usage["effort"] == effort  # the explicit spawn argument
    assert type(usage["duration_ms"]) is int and usage["duration_ms"] >= 0
    # A Stop hook is not native terminal proof, so the outcome stays unknown until one is observed.
    assert usage["outcome"] == "unknown"
    assert all(usage[field] is None for field in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "tool_uses"))
    duration = usage["duration_ms"]
    _list_agents(root, ("usage-implementer", {"completed": None}))
    usage = _handoff(root, handoff)["usage"]
    assert usage["outcome"] == "completed" and usage["duration_ms"] == duration and usage["model"] == "gpt-6-terra"
    section = cli._task_status(root, suppress_protocol_notice=True)["Usage"]
    assert section["totals"]["handoffs"] == 1 and section["totals"]["total_tokens"] is None and section["totals"]["cost_usd"] is None
    assert section["outcomes"] == {"completed": 1} and "gpt-6-terra" in section["by_model"]

    errored, errored_handoff = _spawn(root, "investigator", "usage-errored", marker=_selected_message("C1"))
    _list_agents(root, ("usage-errored", {"errored": "tool failure"}))
    assert _handoff(root, errored_handoff)["usage"]["outcome"] == "failed"
    assert "claims" not in _handoff(root, errored_handoff)


def test_disposing_a_dependency_records_its_usage_outcome(typed_task):
    root, task_id = typed_task
    _child, handoff = _spawn(root, "investigator", "disposed-investigator", marker=_selected_message("C1"))
    revision = _revision(root)
    path = lifecycle._lifecycle_path(root, task_id)
    out = lifecycle.task_dispose_dependency(root, handoff, revision, task_authority.digest(path), "no longer needed")
    assert out["ok"] and out["revision"] == revision + 1
    assert _handoff(root, handoff)["usage"]["outcome"] == "disposed"
    assert task_authority.check(root) is not None


# --- adaptive mode: accepted everywhere, no extra hook restriction, lane counter and advisories --------

def test_adaptive_quick_admission_is_accepted_and_adds_no_hook_restriction(adaptive_task, tmp_path, capsys):
    root, task_id = adaptive_task
    anchor = task_authority.check(root)
    assert anchor["contract"]["execution_mode"] == "adaptive"
    assert anchor["contract"]["boundary"] == anchor["contract"]["invariants"] == "unspecified"
    source = tmp_path.parent / (tmp_path.name + "-adaptive-contract.json")
    source.write_text(json.dumps({"human_instruction": "do it", "acceptance": "done", "execution_mode": "adaptive"}), encoding="utf-8")
    assert task_authority.contract(str(source))["boundary"] == "unspecified"
    assert "adaptive" in task_authority.MODES
    parsed = cli._parser().parse_args(["task-mode", "--mode", "adaptive", "--human-instruction", "x",
                                       "--base-revision", "1", "--expected-authority-sha256", "0" * 64])
    assert parsed.mode == "adaptive"
    status = cli._task_status(root, suppress_protocol_notice=True)
    assert status["Task Authority"]["execution_mode"] == "adaptive"
    assert status["Advisories"]["blocking"] is False and status["Advisories"]["contract_unspecified"] == ["boundary", "invariants"]

    # The Controller executes directly and also dispatches an Implementer: neither restricted set applies.
    for command in ("python -m pytest tests", "git diff", "echo fixed > src/note.txt"):
        assert lifecycle.handle_hook(root, "PreToolUse", _event(tool_name="Bash", tool_input={"command": command})) == ""
    assert lifecycle.handle_hook(root, "PreToolUse", _event(tool_name="apply_patch", tool_input={"patch": "*** Begin Patch"})) == ""
    _register(root, task_id, capsys, {"id": "R1", "workchain_ref": "opaque"})
    _child, handoff = _spawn(root, "implementer", "adaptive-implementer", marker=_selected_message("C1"))
    assert _child_record(root, task_id, "adaptive-implementer")["handoff_id"] == handoff
    _native = lifecycle.handle_hook(root, "PreToolUse", _event(tool_name="spawn_agent", tool_input={
        "agent_type": "worker", "message": "ordinary native helper"}))
    assert "THALIRIS_SINGLE_AGENT_TASK" not in _native and "THALIRIS_CONTROLLER_DIRECT_TASK" not in _native


def test_mode_switch_to_and_from_adaptive(evidence_task):
    root, _task_id = evidence_task
    digest = task_authority.digest(task_authority.path(root))
    changed = task_authority.switch_mode(root, digest, _revision(root), "adaptive", "The user chose the quick lane")
    assert changed["execution_mode"] == "adaptive"
    assert "Advisories" in cli._task_status(root, suppress_protocol_notice=True)
    digest = task_authority.digest(task_authority.path(root))
    back = task_authority.switch_mode(root, digest, _revision(root), "delegated", "An advisory fired; escalate")
    assert back["execution_mode"] == "delegated"
    assert "Advisories" not in cli._task_status(root, suppress_protocol_notice=True)


def test_lane_counter_counts_controller_tool_output_in_adaptive_mode(adaptive_task):
    root, task_id = adaptive_task
    revision, anchor = _revision(root), task_authority.digest(task_authority.path(root))
    assert lifecycle.handle_hook(root, "PostToolUse", _event(
        tool_name="Bash", tool_input={"command": "pytest"}, tool_response="x" * 401)) == ""
    assert core.lane_counters(root, task_id)["controller_tool_output_tokens"] == 101  # ceil(401 / 4)
    lifecycle.handle_hook(root, "PostToolUse", _event(
        tool_name="Bash", tool_input={"command": "pytest"}, tool_response={"output": "y" * 10, "exit_code": 0}))
    structured = len(json.dumps({"output": "y" * 10, "exit_code": 0}, separators=(",", ":")))
    assert core.lane_counters(root, task_id)["controller_tool_output_tokens"] == 101 + -(-structured // 4)
    counted = core.lane_counters(root, task_id)["controller_tool_output_tokens"]
    # The sidecar changes neither the revision nor the anchored bytes.
    assert _revision(root) == revision and task_authority.digest(task_authority.path(root)) == anchor
    assert task_authority.check(root) is not None
    # Another session, and a child's own tool output, are not the Controller's.
    lifecycle.handle_hook(root, "PostToolUse", {**_event(tool_name="Bash", tool_response="z" * 4000), "session_id": "someone-else"})
    lifecycle.handle_hook(root, "PostToolUse", {**_event(tool_name="Bash", tool_response="z" * 4000),
                                                "agent_id": "child", "agent_type": "thaliris-implementer"})
    assert core.lane_counters(root, task_id)["controller_tool_output_tokens"] == counted


@pytest.mark.parametrize("mode", ["delegated", "controller-direct", "single-agent"])
def test_lane_counter_is_not_kept_outside_adaptive_mode(evidence_task, mode):
    root, task_id = evidence_task
    if mode != "delegated":
        task_authority.switch_mode(root, task_authority.digest(task_authority.path(root)), _revision(root), mode, "selected")
    lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="x" * 4000))
    assert core.lane_counters(root, task_id)["controller_tool_output_tokens"] == 0
    assert not list((root / ".context").rglob("lane.json"))
    # Switching to adaptive starts the count from this point.
    task_authority.switch_mode(root, task_authority.digest(task_authority.path(root)), _revision(root), "adaptive", "quick lane")
    lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="x" * 4000))
    assert core.lane_counters(root, task_id)["controller_tool_output_tokens"] == 1000


# --- the Controller packet -------------------------------------------------------------------------

def test_an_advisory_is_shown_without_any_continuity_record(adaptive_task):
    root, _task_id = adaptive_task
    assert "evidence_continuity" not in _state(root)
    assert lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="small")) == ""
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="x" * 120_004))
    context, packet = _packet(raw)
    assert [item["code"] for item in packet["Advisories"]["items"]] == ["CONTROLLER_TOOL_OUTPUT"]
    assert packet["Advisories"]["blocking"] is False and packet["unincorporated_total"] == 0
    assert "Advisories (adaptive mode, non-blocking): CONTROLLER_TOOL_OUTPUT" in context
    assert "task-mode" in context


def test_a_withheld_check_is_shown_with_no_open_observation_and_stays_bounded(typed_task, capsys):
    root, task_id = typed_task
    # Typed requirements alone: an unchecked compiled requirement is already worth showing.
    context, packet = _packet(lifecycle._controller_evidence_context(root, _event(tool_name="Bash", tool_response="ok")))
    assert packet["Verification"]["uncovered_requirements"] == ["R1"] and "no declared check: R1" in context
    assert _declare(root, task_id, capsys, _check())[0] == 0
    context, packet = _packet(lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="ok")))
    assert packet["unincorporated_total"] == packet["unresolved_judgments_total"] == packet["latest_judgments_total"] == 0
    assert packet["Verification"] == {"checks_total": 1, "green": 0, "red": 0, "stale": 0, "unrun": 1,
                                      "not_green": [{"id": "C1", "status": "unrun"}], "withheld_requirements": ["R1"]}
    assert "Verification: 1 unrun of 1 declared checks" in context and "--override-reason" in context
    assert "A green check grants nothing." in context

    assert _run(root, task_id, capsys, "task-verify", "--role", "controller", "--check", "C1")[0] == 0
    # All green, nothing open and no judgment yet: there is nothing to re-present.
    assert lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="ok")) == ""
    # A source change makes the result stale for the current tree, which is shown again.
    (root / "changed.py").write_text("value = 1\n", encoding="utf-8")
    context, packet = _packet(lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="ok")))
    assert packet["Verification"]["stale"] == 1 and packet["Verification"]["not_green"][0]["reason"] == "tree_changed"

    checks = [_check(f"check-with-a-long-identifier-{index:02d}", command=FAILING) for index in range(16)]
    assert _declare(root, task_id, capsys, {"checks": checks})[0] == 0
    lines = lifecycle.verification_lines(root, _state(root), task_authority.check(root)["contract"])
    assert lines["Verification"]["checks_total"] == 17 and len(lines["Verification"]["not_green"]) <= 8
    assert len(json.dumps(lines, separators=(",", ":")).encode()) <= lifecycle._PACKET_LINES_MAX_BYTES


def test_packet_lines_are_trimmed_to_the_byte_budget_and_keep_their_counts(typed_task, monkeypatch):
    root, _task_id = typed_task
    oversized = {
        "Verification": {"checks_total": 400, "green": 0, "red": 400, "stale": 0, "unrun": 0,
                         "checks": [{"id": f"check-{index}-" + "x" * 30, "status": "red", "requirement_refs": ["R1"]} for index in range(16)],
                         "withheld_requirements": [f"R-{index}-" + "y" * 56 for index in range(32)],
                         "uncovered_requirements": [f"U-{index}-" + "z" * 56 for index in range(32)]},
        "Claims": {"handoffs_ingested": 9, "supports": {},
                   "handoffs_without_typed_claims": {"total": 9, "ids": [f"handoff-{index:032d}" for index in range(8)],
                                                     "missing": 9, "malformed": 0}},
        "Advisories": {"blocking": False, "items": [
            {"code": "WRITE_SURFACE_EXCEEDED", "paths": ["p" * 200] * 8, "paths_total": 8} for _ in range(8)]},
    }
    monkeypatch.setattr(core, "task_status_packet", lambda *_args, **_kwargs: oversized)
    lines = lifecycle.verification_lines(root, _state(root), None)
    assert len(json.dumps(lines, ensure_ascii=False, separators=(",", ":")).encode()) <= lifecycle._PACKET_LINES_MAX_BYTES
    assert lines["Verification"]["red"] == 400 and lines["Verification"]["truncated"] is True
    assert lines["Claims"]["without_typed_claims"]["total"] == 9 and lines["Advisories"]["items_total"] == 8
    assert lifecycle._lines_actionable(lines)


def test_claims_without_a_typed_block_are_named_and_a_task_without_features_keeps_its_packet(evidence_task, capsys):
    root, task_id = evidence_task
    assert lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="ok")) == ""
    _register(root, task_id, capsys, {"id": "R1", "workchain_ref": "opaque"})
    assert _state(root)["schema_version"] == core._STATE_SCHEMA_VERSION
    assert lifecycle.verification_lines(root, _state(root), task_authority.check(root)["contract"]) == {}
    assert lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="ok")) == ""
    code, out = _run(root, task_id, capsys, "task-update", "--role", "controller", "--base-revision", str(_revision(root)),
                     "--json", json.dumps({"active_work": ["one thing"]}))
    assert code == 0 and not {"Verification", "Claims", "Advisories"} & out.keys()

    child, handoff = _spawn(root, "investigator", "silent-investigator", marker=_selected_message("C1"))
    lifecycle._record_subagent_stop(root, _stop(child, "A report with no typed block."))
    context, packet = _packet(lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="ok")))
    assert packet["Claims"]["without_typed_claims"] == {"total": 1, "ids": [handoff], "missing": 1, "malformed": 0}
    assert "returned no readable typed claim block" in context and "Read their FINAL reports directly" in context


# --- guidance and generated outputs ----------------------------------------------------------------

def test_child_guidance_states_task_verify_and_the_exact_claim_block():
    for policy in (None, "luna-only"):
        for name, (model, effort, role) in roles.agent_profiles(policy).items():
            text = tomllib.loads(codex_adapter._agent_profile(name[:-5], role, model, effort).decode())["developer_instructions"]
            assert "task-verify --role <your role> --check <id>" in text
            assert "A green check grants nothing" in text
            # The block shown to children is exactly what Core's parser reads.
            parsed = core.parse_claim_block(text)
            assert parsed["status"] == "present" and parsed["total"] == 1
            assert parsed["claims"][0]["requirement"] == "R1" and parsed["claims"][0]["evidence"] == "<check id or path:line>"
            assert "at most 5 claims" in text and "body none" in text


def test_controller_guidance_states_the_verification_first_routine():
    resident = controller_instructions.resident("runner")
    for phrase in (
        "Mechanism may\nwithhold; only a model may grant",
        "`kind` is `compiled`", "`judgment-only` (the default when\nomitted)", "task-check --role controller",
        "task-verify --role\nROLE --check C1", "`VERIFICATION_WITHHELD`", "--override-reason '<why>'",
        "A green check grants nothing", "`task-check --supersede`", "as `surfaced`",
        "single-agent or adaptive", "Adaptive is the quick admission", "advisories never block",
        "prefer escalating\nto delegated with `task-mode`", "`thaliris-claims` block",
    ):
        assert phrase in resident, phrase
    # Superseded statements were replaced, not left beside the new rule.
    assert "before recording `DONE`; it does not" not in resident
    assert "delegated, controller-direct\nor single-agent. Omitted" not in resident


def test_generated_outputs_are_current_without_needing_git():
    assert (REPOSITORY / "docs/thaliris-controller.md").read_text(encoding="utf-8") == controller_instructions.render()
    assert (REPOSITORY / "docs/thaliris-role-packs.md").read_text(encoding="utf-8") == codex_adapter.render_role_packs()
    assert (REPOSITORY / "docs/thaliris-role-registry.md").read_text(encoding="utf-8") == roles.render_registry_document().decode("utf-8")
    current = (REPOSITORY / "AGENTS.md").read_bytes().decode("utf-8")
    start, end = codex_adapter._managed_span(current, "AGENTS.md")
    assert current[start:end] == codex_adapter.render_managed().rstrip("\n")
    for name, (model, effort, role) in roles.agent_profiles().items():
        path = REPOSITORY / ".codex/agents" / name
        assert path.read_bytes() == codex_adapter._agent_profile(name[:-5], role, model, effort), name


def test_released_predecessor_profiles_still_upgrade_only_with_exact_bytes_and_filename():
    """Independent released-source witness for the bytes emitted before this guidance change."""
    base = Path(__file__).parent / "fixtures/verification-first-predecessor"
    proof = json.loads((base / "provenance.json").read_text(encoding="utf-8"))
    blobs = {name: (base / name).read_bytes() for name in
             ("roles.py.blob", "execution_observation.py.blob", "profile_renderer.py.blob", "role-packs.md")}

    def git_blob(raw: bytes) -> str:
        return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

    assert proof["revision"] == "af80cf94a35a2a151160590d8d08648e6f68fa0f"
    assert git_blob(blobs["roles.py.blob"]) == proof["roles_git_blob"]
    assert hashlib.sha256(blobs["roles.py.blob"]).hexdigest() == proof["roles_sha256"]
    assert git_blob(blobs["execution_observation.py.blob"]) == proof["execution_observation_git_blob"]
    assert hashlib.sha256(blobs["profile_renderer.py.blob"]).hexdigest() == proof["renderer_sha256"]
    assert git_blob(blobs["role-packs.md"]) == proof["role_pack_git_blob"]
    assert hashlib.sha256(blobs["role-packs.md"]).hexdigest() == proof["role_pack_sha256"]
    assert codex_adapter._role_pack_state(blobs["role-packs.md"]) == "legacy"
    assert codex_adapter._role_pack_state(blobs["role-packs.md"] + b"\nuser edit") == "user"
    assert codex_adapter._role_pack_state(codex_adapter.ROLE_PACKS.encode()) == "current"

    package = types.ModuleType("verification_first_predecessor")
    package.__path__ = []
    observation = types.ModuleType(package.__name__ + ".execution_observation")
    module = types.ModuleType(package.__name__ + ".roles")
    module.__package__ = package.__name__
    registered = {item.__name__: item for item in (package, observation, module)}
    sys.modules.update(registered)
    try:
        exec(compile(blobs["execution_observation.py.blob"], "released_execution_observation.py", "exec"), observation.__dict__)
        exec(compile(blobs["roles.py.blob"], "released_roles.py", "exec"), module.__dict__)
        namespace = {"json": json, "roles": module}
        exec(compile(blobs["profile_renderer.py.blob"], "released_renderer.py", "exec"), namespace)
        assert proof["profiles"] == codex_adapter._VERIFICATION_FIRST_PREDECESSOR_PROFILE_HASHES
        for constraint in (None, "luna-only"):
            for name, (model, effort, role) in module.agent_profiles(constraint).items():
                raw = namespace["_agent_profile"](name[:-5], role, model, effort)
                assert hashlib.sha256(raw).hexdigest() == proof["profiles"][constraint or "default"][name]
                assert codex_adapter._agent_profile_state(raw, name, constraint) == "legacy"
                assert codex_adapter._agent_profile_state(raw + b"\n# user edit", name, constraint) == "user"
                other = next(item for item in module.agent_profiles() if item != name)
                assert codex_adapter._agent_profile_state(raw, other, constraint) == "user"
                # The released bytes are not the current render: the guidance did change.
                current = roles.agent_profiles(constraint)[name]
                assert raw != codex_adapter._agent_profile(name[:-5], current[2], current[0], current[1])
    finally:
        for name in registered:
            sys.modules.pop(name, None)


def test_adapter_and_core_versions_are_paired():
    import thaliris
    import thaliris_codex
    assert thaliris_codex.__version__ == "0.6.1"
    project = tomllib.loads((REPOSITORY / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == "0.6.1" and project["dependencies"] == ["thaliris>=0.6.2,<0.7"]
    assert thaliris.__version__ == "0.6.2"
