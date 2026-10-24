"""Core 0.5.1 controller ergonomics through the Codex CLI and hook surfaces."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from thaliris import core
from thaliris_codex import cli, codex_adapter, lifecycle, observation_transport, task_authority
from tests.test_evidence_continuity_adapter import (
    evidence_task, _event, _identity, _invoke_hook_command, _observation, _register_requirement,
    _selected_message, _spawn,
)


def _run(root: Path, task_id: str, capsys, *argv: str) -> tuple[int, dict]:
    capsys.readouterr()
    code = cli.main(["--root", str(root), "--task-id", task_id, *argv])
    return code, json.loads(capsys.readouterr().out)


def _revision(root: Path) -> int:
    return core.task_show(root)["state"]["revision"]


def _judgment(identifier: str, refs: list[str], outcome: str = "satisfied") -> dict[str, object]:
    return {"id": identifier, "candidate": "C1", "requirement_ref": "R1", "observation_refs": refs,
            "outcome": outcome, "reasoning": "Selected observations were reviewed for this candidate."}


@pytest.fixture
def two_children(evidence_task):
    """Two live sibling children that each report the same local ids."""
    root, task_id = evidence_task
    _register_requirement(root)
    children = []
    for agent in ("parallel-a", "parallel-b"):
        child, handoff = _spawn(root, "investigator", agent, marker=_selected_message("C1"))
        children.append((agent, child, handoff))
    return root, task_id, children


def _observe_both(root: Path, children) -> list[dict]:
    results = []
    for agent, _child, handoff in children:
        results.append(codex_adapter.task_observe(
            root, "investigator", handoff, lifecycle._identity_hash(agent),
            observation_json=json.dumps(_observation("O1"))))
    return results


def test_overlong_child_local_id_refusal_names_the_local_limit(two_children):
    root, _task_id, children = two_children
    agent, _child, handoff = children[0]
    assert len(handoff) == 40
    with pytest.raises(core.ThalirisError) as refused:
        codex_adapter.task_observe(root, "investigator", handoff, lifecycle._identity_hash(agent),
                                   observation_json=json.dumps(_observation("O" * 24)))
    assert refused.value.code == "CONTINUITY_INVALID" and str(refused.value) == "invalid observation id"
    assert "23 characters" in refused.value.recovery and handoff in refused.value.recovery
    ok = codex_adapter.task_observe(root, "investigator", handoff, lifecycle._identity_hash(agent),
                                    observation_json=json.dumps(_observation("O" * 21)))
    assert ok["ok"]


def test_parallel_children_reporting_the_same_ids_are_namespaced_and_judged_in_one_batch(two_children, capsys):
    root, task_id, children = two_children
    (_, _, first), (_, _, second) = children
    results = _observe_both(root, children)
    assert [item["appended"] for item in results] == [[f"{first}.O1"], [f"{second}.O1"]]
    assert all(item["ok"] for item in results)
    ledger = core.task_show(root)["state"]
    observations = {item["id"]: item for item in ledger["evidence_continuity"]["observations"]}
    assert set(observations) == {f"{first}.O1", f"{second}.O1"}
    # Each embedded source and its reference move with the observation id.
    assert observations[f"{first}.O1"]["source_refs"] == [f"{first}.S-O1"]
    assert observations[f"{second}.O1"]["source_refs"] == [f"{second}.S-O1"]
    assert {f"{first}.S-O1", f"{second}.S-O1"} <= {item["id"] for item in ledger["evidence_refs"]}
    assert observations[f"{first}.O1"]["handoff_id"] == first
    # Re-presenting an already-qualified id is idempotent, not double-prefixed.
    assert codex_adapter.namespaced_observation(first, {"id": f"{first}.O1"})["id"] == f"{first}.O1"

    # One packet states the revision the next write must use.
    revision = _revision(root)
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="list_agents", tool_response={"agents": []}))
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    assert f"task revision {revision}" in context
    assert json.loads(context.splitlines()[-1])["task_revision"] == revision

    batch = root / "batch.json"
    batch.write_text(json.dumps({"judgments": [
        _judgment("J1", [f"{first}.O1"], "unknown"),
        _judgment("J2", [f"{first}.O1", f"{second}.O1"]),
    ]}), encoding="utf-8")
    code, judged = _run(root, task_id, capsys, "task-judge", "--role", "controller",
                        "--base-revision", str(revision), "--input", str(batch))
    assert code == 0 and judged["ok"] is True
    assert judged["appended"] == ["J1", "J2"] and judged["revision"] == revision + 1
    assert _revision(root) == revision + 1
    assert judged["evidence"]["unincorporated_total"] == 0
    assert judged["evidence"]["unresolved_judgments_total"] == 0
    assert "Evidence Continuity" not in judged

    # A later batch with one invalid item is atomic and structured.
    before = _revision(root)
    batch.write_text(json.dumps({"judgments": [
        _judgment("J3", [f"{second}.O1"]), _judgment("J4", ["missing.O1"]),
    ]}), encoding="utf-8")
    code, refused = _run(root, task_id, capsys, "task-judge", "--role", "controller",
                         "--base-revision", str(before), "--input", str(batch))
    assert code == 2 and refused["ok"] is False
    assert refused["code"].startswith("CONTINUITY_") and "details" in refused
    assert _revision(root) == before
    assert {item["id"] for item in core.task_show(root)["state"]["evidence_continuity"]["judgments"]} == {"J1", "J2"}


def test_revision_conflict_is_structured_and_text_is_unchanged(two_children, capsys):
    root, task_id, children = two_children
    _observe_both(root, children)
    stale = _revision(root) - 1
    update = root / "update.json"
    update.write_text(json.dumps({"pending_results": []}), encoding="utf-8")
    code, conflict = _run(root, task_id, capsys, "task-update", "--role", "controller",
                          "--base-revision", str(stale), "--input", str(update))
    assert code == 2 and conflict["ok"] is False
    assert conflict["error"] == "task revision conflict"
    assert conflict["code"] == "TASK_REVISION_CONFLICT"
    assert conflict["recovery"]
    details = conflict["details"]
    assert details["current_revision"] == stale + 1 and details["base_revision"] == stale
    changes = details["changes_since"]
    assert changes["exact"] is False and changes["revision_gap"] == 1
    assert changes["evidence"]["unincorporated_total"] == 2
    # The conflict already carries the evidence summary; it is not repeated.
    assert "evidence" not in conflict
    # Retrying once with the reported revision succeeds.
    code, retried = _run(root, task_id, capsys, "task-update", "--role", "controller",
                         "--base-revision", str(details["current_revision"]), "--input", str(update))
    assert code == 0 and retried["revision"] == details["current_revision"] + 1
    assert retried["evidence"]["unincorporated_total"] == 2

    code, register_conflict = _run(root, task_id, capsys, "task-evidence-register", "--role", "controller",
                                   "--base-revision", str(stale), "--json", json.dumps({"requirements": [{"id": "R2", "workchain_ref": "x"}]}))
    assert code == 2 and register_conflict["code"] == "TASK_REVISION_CONFLICT"
    assert register_conflict["details"]["current_revision"] == _revision(root)


def test_task_status_is_compact_by_default_and_full_on_request(two_children, capsys):
    root, task_id, children = two_children
    _observe_both(root, children)
    for agent, _child, handoff in children:
        for number in range(2, 12):
            codex_adapter.task_observe(root, "investigator", handoff, lifecycle._identity_hash(agent),
                                       observation_json=json.dumps(_observation(f"O{number}")))
    code, compact = _run(root, task_id, capsys, "task-status")
    assert code == 0 and compact["view"] == "compact"
    assert "Evidence Continuity" not in compact
    assert compact["Evidence"]["unincorporated_total"] == 22
    assert compact["Evidence"]["next_offset"] is not None  # bounded, paged
    assert compact["Task"]["revision"] == _revision(root)
    capsys.readouterr()
    cli.main(["--root", str(root), "--task-id", task_id, "task-status"])
    compact_bytes = len(capsys.readouterr().out.encode())
    cli.main(["--root", str(root), "--task-id", task_id, "task-status", "--view", "full"])
    full_text = capsys.readouterr().out
    full = json.loads(full_text)
    assert "view" not in full and full["Evidence Continuity"]["unincorporated_total"] == 22
    assert compact_bytes < len(full_text.encode())

    code, since = _run(root, task_id, capsys, "task-status", "--since-revision", "0")
    assert code == 0 and since["Changes Since"]["current_revision"] == _revision(root)
    assert since["Changes Since"]["exact"] is False
    code, bad = _run(root, task_id, capsys, "task-status", "--since-revision", "-1")
    assert code == 2 and bad["code"] == "REVISION_DELTA_INVALID"


def test_inline_json_is_accepted_for_controller_writes_and_requires_exactly_one_source(two_children, capsys):
    root, task_id, children = two_children
    (_, _, first), _ = children
    (_, _, _), (_, _, second) = children
    _observe_both(root, children)
    revision = _revision(root)
    payload = {"judgments": [_judgment("J1", [f"{first}.O1", f"{second}.O1"])]}
    code, judged = _run(root, task_id, capsys, "task-judge", "--role", "controller",
                        "--base-revision", str(revision), "--json", json.dumps(payload))
    assert code == 0 and judged["appended"] == ["J1"]

    encoded = observation_transport.PREFIX + base64.urlsafe_b64encode(
        json.dumps({"pending_results": ["雪 \U0001fab7 data"]}, ensure_ascii=False).encode("utf-8")).decode("ascii")
    code, updated = _run(root, task_id, capsys, "task-update", "--role", "controller",
                         "--base-revision", str(revision + 1), "--json", encoded)
    assert code == 0
    assert core.task_show(root)["state"]["pending_results"] == ["雪 \U0001fab7 data"]

    code, none = _run(root, task_id, capsys, "task-judge", "--role", "controller", "--base-revision", "0")
    assert code == 2 and "--input" in none["error"] and "--json" in none["error"]
    code, array = _run(root, task_id, capsys, "task-update", "--role", "controller",
                       "--base-revision", str(_revision(root)), "--json", "[1]")
    assert code == 2 and array["code"] == "INPUT_NOT_OBJECT"
    code, broken = _run(root, task_id, capsys, "task-update", "--role", "controller",
                        "--base-revision", str(_revision(root)), "--json", "{nope")
    assert code == 2 and broken["code"] == "INPUT_JSON_INVALID"


@pytest.mark.parametrize("shell", ["powershell", "bash"])
def test_controller_hook_transports_inline_json_literal_as_data(two_children, capsys, shell):
    root, task_id, children = two_children
    (_, _, first), (_, _, second) = children
    _observe_both(root, children)
    revision = _revision(root)
    body = {"judgments": [_judgment("J1", [f"{first}.O1", f"{second}.O1"])]}
    body["judgments"][0]["reasoning"] = "apply_patch was only discussed; Native's text > not.txt $(x) `y`"
    inline = json.dumps(body, separators=(",", ":"))
    literal = "'" + inline.replace("'", "''") + "'" if shell == "powershell" else shlex.quote(inline)
    command = (f"thaliris --root '{root}' --task-id {task_id} task-judge --role controller "
               f"--base-revision {revision} --json " + literal)
    event = _event()
    raw = lifecycle.handle_hook(root, "PreToolUse", {
        **event, "tool_name": "Bash", "tool_input": {"command": command, "shell": shell}})
    updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
    assert "utf8-base64:" in updated and "apply_patch" not in updated
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert tokens[0] == "thaliris"
    capsys.readouterr()
    assert cli.main(tokens[1:]) == 0
    assert json.loads(capsys.readouterr().out)["appended"] == ["J1"]
    stored = core.task_get(root, "J1")["object"]
    assert stored["reasoning"] == body["judgments"][0]["reasoning"]


def test_transport_option_is_bound_to_its_operation():
    judged = "thaliris task-judge --role controller --base-revision 3 --json '{\"judgments\":[]}'"
    assert observation_transport.literal_object_argument(judged, powershell=False, option="--json") is not None
    # The observation option is not a judge option and stays untouched there.
    assert observation_transport.literal_object_argument(judged, powershell=False) is None
    assert observation_transport.INLINE_OPTIONS["task-judge"] == "--json"
    assert observation_transport.INLINE_OPTIONS["task-observe"] == "--observation-json"


def test_controller_import_keeps_the_controller_chosen_id(two_children):
    root, _task_id, children = two_children
    (_, _, first), _ = children
    result = codex_adapter.task_observe(root, "controller", first, None, observation_json=json.dumps(_observation("O-import")))
    assert result["appended"] == ["O-import"]
    assert result["evidence"]["unincorporated_total"] == 1


def test_bootstrap_and_guidance_stdout_are_utf8_under_a_legacy_code_page(tmp_path):
    env = {**os.environ, "CODEX_HOME": str(tmp_path / "codex-home"), "PYTHONIOENCODING": "cp936", "PYTHONPATH": os.pathsep.join(sys.path)}
    env.pop("PYTHONUTF8", None)
    completed = subprocess.run(
        [sys.executable, "-m", "thaliris_codex.cli", "--root", str(tmp_path), "controller-instructions", "--section", "routing"],
        capture_output=True, env=env)
    assert completed.returncode == 0, completed.stderr
    text = completed.stdout.decode("utf-8")
    assert json.loads(text)["ok"] is True
    assert "–".encode("utf-8") in completed.stdout  # U+2013 is written as UTF-8, not as a cp936 byte pair


def test_utf8_writer_ignores_the_stream_encoding(monkeypatch):
    import io
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    cli._write_utf8_line(json.dumps({"text": "雪 \U0001fab7 –"}, ensure_ascii=False))
    stream.flush()
    assert json.loads(raw.getvalue().decode("utf-8")) == {"text": "雪 \U0001fab7 –"}
