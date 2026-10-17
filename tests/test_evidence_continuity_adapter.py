from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading

import pytest

from thaliris import core
from thaliris_codex import cli, codex_adapter, lifecycle, roles, task_authority


@pytest.fixture
def evidence_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    home = tmp_path / "isolated-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    agents = home / "agents"
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = agents / name
        if not profile.exists():
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path.parent / (tmp_path.name + "-task-authority"))
    codex_adapter.init(tmp_path)
    started = core.task_start(tmp_path, "selected evidence continuity", None, None)
    task_id = started["task_id"]
    core.select_task(tmp_path, task_id)
    owner_hash = hashlib.sha256(b"evidence-controller-session").hexdigest()
    task_authority.establish(tmp_path, core._load_state(tmp_path), {
        "human_instruction": "Maintain selected evidence continuity for one candidate",
        "boundary": "Adapter evidence lifecycle fixture",
        "invariants": "Keep native handoff producer identity and do not inject global task text",
        "acceptance": "Only selected handoffs can append their own observation",
        "execution_mode": "delegated",
    }, owner_hash)
    lifecycle.record_task_start_owner(tmp_path, task_id, owner_hash)
    return tmp_path, task_id


def _register_requirement(root: Path) -> None:
    path = root / "requirement.json"
    path.write_text(json.dumps({"requirements": [{"id": "R1", "workchain_ref": "opaque-workchain-ref"}]}), encoding="utf-8")
    revision = core.task_show(root)["state"]["revision"]
    registered = core.task_evidence_register(root, "controller", revision, str(path))
    task_authority.checkpoint(root)
    assert registered.get("ok") is True
    assert task_authority.check(root) is not None


def _event(**values: object) -> dict[str, object]:
    return {"session_id": "evidence-controller-session", "turn_id": "evidence-controller-turn", **values}


def _identity(role: str, agent: str) -> dict[str, object]:
    return _event(agent_id=agent, agent_type=f"thaliris-{role}", turn_id=f"{agent}-turn")


def _selected_message(candidate: str = "candidate-current", refs: list[str] | None = None,
                      durable_paths: list[str] | None = None) -> str:
    selection: dict[str, object] = {
        "candidate": candidate,
        "requirement_refs": refs or ["R1"],
    }
    if durable_paths is not None:
        selection["durable_paths"] = durable_paths
    return "Do only this selected work.\nthaliris-evidence: " + json.dumps(selection, separators=(",", ":"))


def _spawn(root: Path, role: str, agent: str, *, parent: dict[str, object] | None = None,
           marker: str | None = None) -> tuple[dict[str, object], str]:
    selected_model = roles.ROLE_MODEL_ROUTING_DEFAULTS.get(role)
    selection = ({"model": selected_model[0], "reasoning_effort": selected_model[1]}
                 if selected_model is not None else {})
    request = {
        **(parent or _event()),
        "tool_name": "spawn_agent",
        "tool_input": {
            "agent_type": f"thaliris-{role}",
            "fork_turns": "none",
            "message": marker or "Legacy selected task without an evidence marker",
            **selection,
        },
    }
    decision = lifecycle.handle_hook(root, "PreToolUse", request)
    assert not decision or json.loads(decision)["hookSpecificOutput"].get("permissionDecision") != "deny", decision
    child = _identity(role, agent)
    assert lifecycle._record_subagent_start(root, child)
    lifecycle.handle_hook(root, "PostToolUse", {**request, "tool_response": {"task_name": f"/root/{agent}"}})
    task_id = core.task_show(root)["state"]["task_id"]
    record = next(item for item in lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)["children"]
                  if item.get("agent_id_hash") == lifecycle._identity_hash(agent))
    return child, record["handoff_id"]


def _observation(identifier: str, *, handoff_id: str | None = None, candidate: str | None = None,
                 requirement_refs: list[str] | None = None) -> dict[str, object]:
    source_id = "S-" + identifier
    body: dict[str, object] = {
        "id": identifier,
        "source_refs": [source_id],
        "sources": [{"id": source_id, "kind": "local", "locator": "tests/evidence-result.md", "summary": "selected source"}],
        "text": "The selected local source supports this observation.",
    }
    if handoff_id is not None:
        body["handoff_id"] = handoff_id
    if candidate is not None:
        body["candidate"] = candidate
    if requirement_refs is not None:
        body["requirement_refs"] = requirement_refs
    return body


def _invoke_hook_command(root: Path, child: dict[str, object], command: str, *, readonly: bool = False) -> tuple[str, dict[str, object]]:
    payload = {**child, "tool_name": "Bash", "tool_input": {"command": command}}
    if readonly:
        payload["readonly"] = True
    raw = lifecycle.handle_hook(root, "PreToolUse", payload)
    if not raw:
        return "", payload
    return raw, payload


def test_readonly_child_appends_inline_observation_with_hook_bound_identity(evidence_task, capsys) -> None:
    root, task_id = evidence_task
    _register_requirement(root)
    child, handoff_id = _spawn(root, "investigator", "evidence-investigator", marker=_selected_message())
    value = _observation("O-inline")
    inline = json.dumps(value, separators=(",", ":"))
    command = f'thaliris --root "{root}" task-observe --role investigator --observation-json \'{inline}\''
    denied, _ = _invoke_hook_command(root, child, command + " > source.py", readonly=True)
    assert "deny" in denied
    assert not (root / "source.py").exists()
    raw, _ = _invoke_hook_command(root, child, command, readonly=True)
    updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
    assert "--observation-json" in updated and "--input" not in updated
    assert f"--task-id {task_id}" in updated
    assert f"--handoff-id {handoff_id}" in updated
    assert f"--agent-id-hash {lifecycle._identity_hash('evidence-investigator')}" in updated

    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert tokens[0] == "thaliris"
    assert cli.main(tokens[1:]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert "Evidence Continuity" not in result and "evidence_continuity" not in result
    stored = core.task_get(root, "O-inline")["object"]
    assert stored["producer"] == "handoff:" + handoff_id
    assert stored["native_actor"] == lifecycle._identity_hash("evidence-investigator")
    assert "submitted_by" not in stored
    assert task_authority.check(root) is not None
    assert core.task_status(root)["Evidence Continuity"]["unincorporated"][0]["observation_id"] == "O-inline"


def test_nested_handoff_inherits_opaque_lineage_without_global_text(evidence_task) -> None:
    root, _task_id = evidence_task
    _register_requirement(root)
    parent, parent_handoff = _spawn(root, "implementer", "evidence-parent", marker=_selected_message("candidate-parent"))
    nested, nested_handoff = _spawn(root, "investigator", "evidence-scanner", parent=parent)
    state = core.task_show(root)["state"]["evidence_continuity"]
    first = next(item for item in state["handoffs"] if item["id"] == parent_handoff)
    second = next(item for item in state["handoffs"] if item["id"] == nested_handoff)
    assert first["candidate"] == second["candidate"] == "candidate-parent"
    assert first["requirement_refs"] == ["R1"]
    assert second["requirement_refs"] == []
    assert second["parent_handoff_id"] == parent_handoff
    assert nested["turn_id"] == "evidence-scanner-turn"
    assert "text" not in first and "text" not in second
    assert "requirements" not in first and "observations" not in second


def test_child_cannot_forge_observation_provenance(evidence_task) -> None:
    root, task_id = evidence_task
    _register_requirement(root)
    child, handoff_id = _spawn(root, "investigator", "evidence-guard", marker=_selected_message())
    native_hash = lifecycle._identity_hash("evidence-guard")
    valid = _observation("O-forgery", candidate="candidate-current", requirement_refs=["R1"])
    for role, selected_handoff, selected_actor, body in (
        ("verifier", handoff_id, native_hash, valid),
        ("investigator", "handoff-forged", native_hash, valid),
        ("investigator", handoff_id, "0" * 64, valid),
        ("investigator", handoff_id, native_hash, {**valid, "candidate": "candidate-other"}),
        ("investigator", handoff_id, native_hash, {**valid, "requirement_refs": ["R-other"]}),
        ("investigator", handoff_id, native_hash, {**valid, "producer": "controller"}),
        ("investigator", handoff_id, native_hash, {**valid, "submitted_by": "controller"}),
        ("investigator", handoff_id, native_hash, {**valid, "native_actor": "0" * 64}),
        ("investigator", handoff_id, native_hash, {**valid, "native_status": "completed"}),
        ("investigator", handoff_id, native_hash, {**valid, "native_status_conflict": False}),
    ):
        with pytest.raises((ValueError, KeyError)):
            codex_adapter.task_observe(root, role, selected_handoff, selected_actor,
                                       observation_json=json.dumps(body, separators=(",", ":")))

    for command in (
        f"thaliris --root \"{root}\" task-evidence-register --role investigator --base-revision 2 --input denied.json",
        f"thaliris --root \"{root}\" task-judge --role investigator --base-revision 2 --input denied.json",
    ):
        raw, _ = _invoke_hook_command(root, child, command)
        assert "deny" in raw


def test_controller_imports_selected_historical_legacy_handoff_without_reactivation(evidence_task, capsys) -> None:
    root, task_id = evidence_task
    _register_requirement(root)
    child, handoff_id = _spawn(root, "implementer", "legacy-evidence-child")
    child_hash = lifecycle._identity_hash("legacy-evidence-child")
    body = _observation("O-imported")
    with pytest.raises(ValueError, match="selected handoff has no evidence association"):
        codex_adapter.task_observe(root, "controller", handoff_id, None,
                                   observation_json=json.dumps(body, separators=(",", ":")))

    # A Controller can preserve a reviewed result from an abandoned/stale child.
    # This records its exact source identity and UNKNOWN status without treating
    # the child as live or resolving its native execution state.
    revision = core.task_show(root)["state"]["revision"]
    life_path = lifecycle._lifecycle_path(root, task_id)
    disposed = lifecycle.task_dispose_dependency(
        root, handoff_id, revision, task_authority.digest(life_path), "retain source observation from stale handoff",
    )
    assert disposed["native_execution"] == "UNKNOWN"
    lifecycle_state = lifecycle._load_lifecycle(life_path, task_id)
    lifecycle_state["children"][0]["native_status_conflict"] = True
    lifecycle._write_capture(life_path, lifecycle_state)

    input_path = root / "legacy-registration.json"
    input_path.write_text(json.dumps({"handoffs": [{
        "id": handoff_id,
        "parent_handoff_id": None,
        "candidate": "candidate-from-controller-review",
        "producer": "handoff:" + handoff_id,
        "requirement_refs": ["R1"],
    }]}), encoding="utf-8")
    revision = core.task_show(root)["state"]["revision"]
    assert cli.main(["--root", str(root), "--task-id", task_id, "task-evidence-register", "--role", "controller",
                     "--base-revision", str(revision), "--input", str(input_path)]) == 0
    capsys.readouterr()
    body["candidate"] = "candidate-from-controller-review"
    body["requirement_refs"] = ["R1"]
    with pytest.raises(ValueError, match="exact live native handoff producer"):
        codex_adapter.task_observe(root, "implementer", handoff_id, child_hash,
                                   observation_json=json.dumps(body, separators=(",", ":")))

    inline = json.dumps(body, separators=(",", ":"))
    assert cli.main(["--root", str(root), "--task-id", task_id, "task-observe", "--role", "controller",
                     "--handoff-id", handoff_id, "--observation-json", inline]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    stored = core.task_get(root, "O-imported")["object"]
    assert stored["producer"] == "handoff:" + handoff_id
    assert stored["native_actor"] == child_hash
    assert stored["submitted_by"] == "controller"
    assert stored["native_status"] == "UNKNOWN"
    assert stored["native_status_conflict"] is True


def test_controller_results_keep_unincorporated_evidence_visible(evidence_task, capsys) -> None:
    root, task_id = evidence_task
    _register_requirement(root)
    registration = root / "controller-chain.json"
    registration.write_text(json.dumps({"handoffs": [{
        "id": "H-controller", "parent_handoff_id": None, "candidate": "C1",
        "producer": "controller", "requirement_refs": ["R1"],
    }]}), encoding="utf-8")
    revision = core.task_show(root)["state"]["revision"]
    core.task_evidence_register(root, "controller", revision, str(registration))
    core.task_observe(root, "controller", {
        **_observation("O-pending"), "handoff_id": "H-controller",
        "candidate": "C1", "requirement_refs": ["R1"],
    })
    task_authority.checkpoint(root)
    revision = core.task_show(root)["state"]["revision"]
    update = root / "update.json"
    update.write_text(json.dumps({"pending_results": []}), encoding="utf-8")
    prefix = ["--root", str(root), "--task-id", task_id]
    assert cli.main([*prefix, "task-update", "--role", "controller", "--base-revision", str(revision), "--input", str(update)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["Evidence Continuity"]["unincorporated"][0]["observation_id"] == "O-pending"
    assert cli.main([*prefix, "task-update", "--role", "controller", "--base-revision", str(revision), "--input", str(update)]) == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["error"] == "task revision conflict"
    assert conflict["Evidence Continuity"]["unincorporated_total"] == 1
    assert cli.main([*prefix, "task-close", "--base-revision", str(revision + 1)]) == 0
    closed = json.loads(capsys.readouterr().out)
    assert closed["ok"] is True
    assert closed["Evidence Continuity"]["unincorporated_total"] == 1
    assert core.task_status(root)["Task"]["status"] == "DONE"


def test_controller_context_skips_empty_evidence_packet(evidence_task) -> None:
    root, _task_id = evidence_task
    _register_requirement(root)
    _spawn(root, "investigator", "empty-evidence-child", marker=_selected_message())
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(
        tool_name="list_agents", tool_response={"agents": []}))
    assert raw == ""


def test_controller_context_keeps_unresolved_judgment_visible(evidence_task) -> None:
    root, _task_id = evidence_task
    _register_requirement(root)
    handoff_id = "H-controller"
    registration = root / "controller-handoff.json"
    registration.write_text(json.dumps({"handoffs": [{
        "id": handoff_id, "parent_handoff_id": None, "candidate": "C1",
        "producer": "controller", "requirement_refs": ["R1"],
    }]}), encoding="utf-8")
    revision = core.task_show(root)["state"]["revision"]
    core.task_evidence_register(root, "controller", revision, str(registration))
    core.task_observe(root, "controller", {
        **_observation("O-judged", handoff_id=handoff_id, candidate="C1", requirement_refs=["R1"]),
    })
    judgment = root / "judgment.json"
    judgment.write_text(json.dumps({
        "id": "J-unresolved", "candidate": "C1", "requirement_ref": "R1",
        "observation_refs": ["O-judged"], "outcome": "unknown",
        "reasoning": "The selected evidence does not resolve this requirement.",
    }), encoding="utf-8")
    revision = core.task_show(root)["state"]["revision"]
    core.task_judge(root, "controller", revision, str(judgment))
    task_authority.checkpoint(root)
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(
        tool_name="list_agents", tool_response={"agents": []}))
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    packet = json.loads(context.splitlines()[-1])
    assert packet["unresolved_judgments"] == [{
        "id": "J-unresolved", "candidate": "C1", "requirement_ref": "R1", "outcome": "unknown",
    }]


def test_curator_maintenance_is_limited_to_exact_selected_paths(evidence_task, capsys) -> None:
    root, task_id = evidence_task
    _register_requirement(root)
    selected_paths = [".agent-memory/new.md", ".agent-memory/INDEX.md"]
    curator, handoff_id = _spawn(root, "curator", "evidence-curator",
                                 marker=_selected_message("candidate-curator", durable_paths=selected_paths))
    base_revision = core.task_show(root)["state"]["revision"]
    old_index = (root / ".agent-memory" / "INDEX.md").read_bytes()
    transaction = {
        "writes": [{"path": selected_paths[0], "base_sha256": None,
                    "content": core._entry("new", "split output").decode("utf-8")}],
        "index_update": {"path": selected_paths[1], "base_sha256": core._digest(old_index),
                         "content": core._entry("map", "[new](new.md)").decode("utf-8")},
    }
    source = root / "selected-maintenance.json"
    source.write_text(json.dumps(transaction), encoding="utf-8")
    command = f'thaliris --root "{root}" document-maintain --role curator --base-revision {base_revision} --input "{source}"'
    raw, _ = _invoke_hook_command(root, curator, command)
    updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
    assert f"--task-id {task_id}" in updated and f"--handoff-id {handoff_id}" in updated
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["written"] == sorted(selected_paths)
    assert "Evidence Continuity" not in output and "evidence_continuity" not in output
    assert task_authority.check(root) is not None

    outside = {"writes": [{"path": ".agent-memory/outside.md", "base_sha256": None,
                            "content": core._entry("outside", "must not be written").decode("utf-8")}]}
    outside_path = root / "outside-maintenance.json"
    outside_path.write_text(json.dumps(outside), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds Controller-selected durable paths"):
        codex_adapter.document_maintain(root, "curator", core.task_show(root)["state"]["revision"],
                                        str(outside_path), handoff_id)


def test_unmarked_legacy_handoff_stays_compatible_but_cannot_auto_record(evidence_task) -> None:
    root, _task_id = evidence_task
    _register_requirement(root)
    child, handoff_id = _spawn(root, "implementer", "legacy-unmarked-child")
    assert not any(item["id"] == handoff_id for item in core.task_show(root)["state"]["evidence_continuity"]["handoffs"])
    with pytest.raises(ValueError, match="selected handoff has no evidence association"):
        codex_adapter.task_observe(root, "implementer", handoff_id,
                                   lifecycle._identity_hash("legacy-unmarked-child"),
                                   observation_json=json.dumps(_observation("O-unregistered"), separators=(",", ":")))


def test_opaque_native_spawn_reports_gap_then_exact_controller_association_supports_child(evidence_task, capsys):
    root, task_id = evidence_task
    _register_requirement(root)
    # Real Native acceptance supplied gAAAA... messages to Hooks; lifecycle
    # payload_hash matched those opaque strings, not the intended plaintext.
    # This real-shaped input must stay opaque. The explicit association path
    # preserves native provenance without pretending marker extraction worked.
    child, handoff_id = _spawn(root, "implementer", "opaque-native-parent", marker="gAAAAABopaqueHostMessage")
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="list_agents", tool_response={"agents": []}))
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    packet = json.loads(context.splitlines()[-1])
    assert packet["unassociated_handoffs"] == [{"handoff_id": handoff_id,
        "role": "implementer", "parent_handoff_id": None}]
    assert packet["unassociated_handoffs_total"] == 1
    assert "task-evidence-register" in context
    with pytest.raises(ValueError, match="selected handoff has no evidence association"):
        codex_adapter.task_observe(root, "implementer", handoff_id, lifecycle._identity_hash("opaque-native-parent"),
                                   observation_json=json.dumps(_observation("O-opaque")))
    source = root / "exact-association.json"
    source.write_text(json.dumps({"handoffs": [{"id": handoff_id, "parent_handoff_id": None,
        "candidate": "opaque-candidate", "producer": "handoff:" + handoff_id, "requirement_refs": ["R1"]}]}), encoding="utf-8")
    assert cli.main(["--root", str(root), "--task-id", task_id, "task-evidence-register", "--role", "controller",
                     "--base-revision", str(core.task_show(root)["state"]["revision"]), "--input", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    codex_adapter.task_observe(root, "implementer", handoff_id, lifecycle._identity_hash("opaque-native-parent"),
                               observation_json=json.dumps(_observation("O-opaque")))
    task_authority.checkpoint(root)
    stored = core.task_get(root, "O-opaque")["object"]
    assert stored["handoff_id"] == handoff_id and stored["candidate"] == "opaque-candidate"
    assert stored["native_actor"] == lifecycle._identity_hash("opaque-native-parent")
    assert stored["requirement_refs"] == ["R1"] and "submitted_by" not in stored
    scanner, nested_id = _spawn(root, "investigator", "opaque-native-scanner", parent=child,
                                marker="gAAAAABopaqueNestedHostMessage")
    nested = core.task_get(root, nested_id)["object"]
    assert nested["parent_handoff_id"] == handoff_id
    assert nested["candidate"] == "opaque-candidate" and nested["requirement_refs"] == []
    codex_adapter.task_observe(root, "investigator", nested_id, lifecycle._identity_hash("opaque-native-scanner"),
                               observation_json=json.dumps(_observation("O-opaque-nested")))
    task_authority.checkpoint(root)
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response={"exit_code": 0}))
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    assert json.loads(context.splitlines()[-1])["unassociated_handoffs_total"] == 0
    assert "O-opaque-nested" in context and core.selected_task(root) == task_id
    assert task_authority.check(root) is not None


@pytest.mark.parametrize("tool,result", [("Bash", {"exit_code": 0, "output": "PASS"}),
    ("wait_agent", {"status": {"child": {"completed": "READY"}}}),
    ("list_agents", {"agents": []})])
def test_ordinary_positive_result_reenters_evidence_before_completion_decision(evidence_task, tool, result):
    root, _ = evidence_task
    _register_requirement(root)
    child, handoff = _spawn(root, "investigator", "evidence-timing", marker=_selected_message())
    codex_adapter.task_observe(root, "investigator", handoff, lifecycle._identity_hash("evidence-timing"),
        observation_json=json.dumps(_observation("O-decision-changing")))
    task_authority.checkpoint(root)
    raw = lifecycle.handle_hook(root.parent, "PostToolUse", _event(cwd=str(root.parent), tool_name=tool, tool_response=result))
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    assert "O-decision-changing" in context
    assert "before your next" in context and "Models decide applicability" in context
    assert core.task_show(root)["state"]["status"] == "ACTIVE"
    assert lifecycle.handle_hook(root.parent, "PostToolUse", {**child, "cwd": str(root.parent), "tool_name": tool, "tool_response": result}) == ""


def test_two_dispatched_regions_keep_local_provenance_and_controller_global_judgment(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    authority_before = task_authority.check(root)["contract"]
    goal_before = core.task_show(root)["state"]["goal"]
    handoffs = []
    for region in ("navigation", "evidence"):
        child, handoff = _spawn(root, "investigator", f"region-{region}", marker=_selected_message())
        handoffs.append(handoff)
        codex_adapter.task_observe(root, "investigator", handoff, lifecycle._identity_hash(f"region-{region}"),
                                   observation_json=json.dumps(_observation(f"O-{region}")))
        task_authority.checkpoint(root)
    # The prompt assigns this investigation to the children. Hooks still allow
    # legal reads/Git/diagnostics while they run: no tool quota or privilege gate
    # can prove whether the Controller is cognitively repeating their work.
    for command in ("rg --files src", "rg -n association src", "git diff", "python -m pytest tests"):
        assert lifecycle.handle_hook(root, "PreToolUse", _event(tool_name="Bash", tool_input={"command": command})) == ""
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    assert {item["handoff_id"] for item in ledger["children"]} == set(handoffs)
    assert all(not lifecycle._native_execution_terminal(item) for item in ledger["children"])
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="list_agents", tool_response={"agents": [
        {"agent_name": f"/root/region-{region}", "agent_status": {"completed": f"distilled {region} conclusion"}}
        for region in ("navigation", "evidence")]}))
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    assert "O-navigation" in context and "O-evidence" in context
    # One precise post-result read is equally legal. The model determines its
    # immediate decision purpose; native completion cannot judge acceptance.
    assert lifecycle.handle_hook(root, "PreToolUse", _event(tool_name="Bash",
        tool_input={"command": "Get-Content src/thaliris_codex/repository_association.py -TotalCount 20"})) == ""
    state = core.task_show(root)["state"]
    assert state["status"] == "ACTIVE" and state["goal"] == goal_before
    assert state["evidence_continuity"]["judgments"] == []
    assert task_authority.check(root)["contract"] == authority_before


def test_auxiliary_handoff_diagnostic_failure_keeps_selected_evidence_visible(evidence_task, monkeypatch):
    root, _ = evidence_task
    _register_requirement(root)
    child, handoff = _spawn(root, "investigator", "diagnostic-failure", marker=_selected_message())
    codex_adapter.task_observe(root, "investigator", handoff, lifecycle._identity_hash("diagnostic-failure"),
                               observation_json=json.dumps(_observation("O-must-remain-visible")))
    task_authority.checkpoint(root)
    original = lifecycle._load_lifecycle
    reads = []
    def unavailable(*args):
        reads.append(args)
        if len(reads) > 1:
            raise ValueError("auxiliary lifecycle read unavailable")
        return original(*args)
    monkeypatch.setattr(lifecycle, "_load_lifecycle", unavailable)
    raw = lifecycle._controller_evidence_context(root, _event(tool_name="Bash", tool_response={"exit_code": 0}))
    context = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    assert "O-must-remain-visible" in context
    packet = json.loads(context.splitlines()[-1])
    assert packet["unassociated_handoffs_status"] == "UNKNOWN"
    assert packet["unassociated_handoffs_total"] is None


def _preselect(root, role="implementer", **changes):
    selection = {"role": role, "expected_agent_type": "thaliris-" + role,
                 "candidate": "C4", "requirement_refs": ["R1"], **changes}
    source = root / "preselection.json"
    source.write_text(json.dumps({"next_dispatch": selection}), encoding="utf-8")
    return codex_adapter.task_evidence_register(root, "controller",
        core.task_show(root)["state"]["revision"], str(source), lifecycle._identity_hash("evidence-controller-session"))


def _opaque_request(role="implementer", **values):
    return _event(tool_name="spawn_agent", tool_input={
        "agent_type": "thaliris-" + role, "fork_turns": "none",
        "message": "gAAAAABopaqueNativeHandoff", **values})


def _protected_evidence_bytes(root, task_id):
    paths = (core._state_path(root), lifecycle._lifecycle_path(root, task_id), task_authority.path(root))
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def test_preselection_cli_registers_requirements_and_opaque_first_observation_before_ack(evidence_task, capsys):
    root, task_id = evidence_task
    selection = {"role": "implementer", "expected_agent_type": "thaliris-implementer",
                 "candidate": "C4", "requirement_refs": ["R1"]}
    source = root / "preselection.json"
    source.write_text(json.dumps({"requirements": [{"id": "R1", "workchain_ref": "opaque"}],
                                  "next_dispatch": selection}), encoding="utf-8")
    command = f'thaliris --root "{root}" --task-id {task_id} task-evidence-register --role controller --base-revision 1 --input "{source}"'
    raw, _ = _invoke_hook_command(root, _event(), command)
    updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
    assert "--controller-session-id-hash " + lifecycle._identity_hash("evidence-controller-session") in updated
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 0
    assert json.loads(capsys.readouterr().out)["next_dispatch"] == selection
    request = _opaque_request()
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", request)
    pending = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    handoff_id = pending["pending_authorized_spawn"]["handoff_id"]
    assert "next_evidence_dispatch" not in pending
    assert core.task_get(root, handoff_id)["object"]["candidate"] == "C4"
    child = _identity("implementer", "opaque-before-ack")
    assert lifecycle._record_subagent_start(root, child)
    codex_adapter.task_observe(root, "implementer", handoff_id, lifecycle._identity_hash(child["agent_id"]),
        observation_json=json.dumps(_observation("O-before-ack")))
    assert core.task_get(root, "O-before-ack")["object"]["requirement_refs"] == ["R1"]
    assert task_authority.check(root) is not None
    # Parent PostToolUse acknowledgement has not happened; the bound child can
    # already dispatch its Scanner, which inherits exact lineage and empty refs.
    scanner_request = {**_opaque_request("investigator"), **child}
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", scanner_request)
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    scanner_handoff = ledger["pending_authorized_spawn"]["handoff_id"]
    scanner = _identity("investigator", "opaque-scanner-before-ack")
    assert lifecycle._record_subagent_start(root, scanner)
    command = f'thaliris --root "{root}" task-observe --role investigator --observation-json ' + "'" + json.dumps(_observation("O-scanner-first"), separators=(",", ":")) + "'"
    raw, _ = _invoke_hook_command(root, scanner, command, readonly=True)
    updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
    assert "--task-id " + task_id in updated and "--handoff-id " + scanner_handoff in updated
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 0
    capsys.readouterr()
    observation = core.task_get(root, "O-scanner-first")["object"]
    assert observation["requirement_refs"] == [] and observation["candidate"] == "C4"
    assert core.task_get(root, scanner_handoff)["object"]["parent_handoff_id"] == handoff_id
    assert observation["native_actor"] == lifecycle._identity_hash(scanner["agent_id"])
    raw = lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="list_agents", tool_response={"agents": []}))
    assert "O-before-ack" in raw and "O-scanner-first" in raw


def test_preselection_consumes_once_and_nested_never_consumes_root_selection(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    _preselect(root)
    parent, handoff_id = _spawn(root, "implementer", "selected-parent", marker="gAAAAABopaque")
    _preselect(root, "reviewer")
    scanner, scanner_id = _spawn(root, "investigator", "selected-scanner", parent=parent, marker="gAAAAABnested")
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    assert ledger["next_evidence_dispatch"]["role"] == "reviewer"
    assert core.task_get(root, scanner_id)["object"]["parent_handoff_id"] == handoff_id
    _spawn(root, "reviewer", "selected-reviewer", marker="gAAAAABopaqueReview")
    assert "next_evidence_dispatch" not in lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    _child, legacy_id = _spawn(root, "investigator", "unselected-later", marker="gAAAAABunselected")
    with pytest.raises(ValueError, match="not found"):
        core.task_get(root, legacy_id)


@pytest.mark.parametrize("kind", ["profile", "role", "owner", "readonly", "fenced", "marker"])
def test_preselection_refusals_preserve_selection_and_no_reservation(evidence_task, kind):
    root, task_id = evidence_task
    _register_requirement(root)
    _preselect(root)
    if kind == "owner":
        lifecycle._write_session_association(root, task_id, lifecycle._identity_hash("different-controller"))
    before = _protected_evidence_bytes(root, task_id)
    request = _opaque_request()
    if kind == "profile":
        request["tool_input"]["agent_type"] = "thaliris-focused-implementer-astra-medium"
    elif kind == "role":
        request["tool_input"]["agent_type"] = "thaliris-reviewer"
    elif kind == "owner":
        request["session_id"] = "different-controller"
    elif kind in {"readonly", "fenced"}:
        request[kind] = True
    elif kind == "marker":
        request["tool_input"]["message"] = _selected_message("conflicting-candidate")
    assert "deny" in lifecycle.handle_hook(root, "PreToolUse", request)
    assert _protected_evidence_bytes(root, task_id) == before


@pytest.mark.parametrize("operation,failure_stage", [
    (operation, stage) for operation in ("register", "reserve", "observe")
    for stage in ("state", "checkpoint", "capture") if (operation, stage) != ("observe", "capture")])
def test_evidence_transaction_failures_restore_exact_state_authority_and_selection(evidence_task, monkeypatch, failure_stage, operation):
    root, task_id = evidence_task
    _register_requirement(root)
    if operation in {"reserve", "observe"}:
        _preselect(root)
    if operation == "observe":
        child, handoff_id = _spawn(root, "implementer", "transaction-observer", marker="gAAAAABopaque")
    before = _protected_evidence_bytes(root, task_id)
    module, name = {"state": (core, "_write_state"), "checkpoint": (task_authority, "checkpoint"),
                    "capture": (task_authority, "capture")}[failure_stage]
    original = getattr(module, name)
    def write_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected after existing writer")
    monkeypatch.setattr(module, name, write_then_fail)
    if operation == "reserve":
        assert "deny" in lifecycle._reserve_managed_spawn(root, _opaque_request())
    else:
        with pytest.raises(OSError, match="injected"):
            if operation == "register":
                _preselect(root)
            else:
                codex_adapter.task_observe(root, "implementer", handoff_id, lifecycle._identity_hash(child["agent_id"]),
                    observation_json=json.dumps(_observation("O-rolled-back")))
    assert _protected_evidence_bytes(root, task_id) == before
    assert task_authority.check(root) is not None


def test_preselection_validation_and_revision_conflict_do_not_mutate(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    before = _protected_evidence_bytes(root, task_id)
    for changes in ({"requirement_refs": ["missing"]}, {"durable_paths": [".agent-memory/no.md"]},
                    {"expected_agent_type": "worker"}, {"candidate": ""}, {"requirement_refs": []}):
        with pytest.raises(ValueError):
            _preselect(root, **changes)
        assert _protected_evidence_bytes(root, task_id) == before
    _preselect(root)
    selected = _protected_evidence_bytes(root, task_id)
    with pytest.raises(ValueError, match="revision conflict"):
        codex_adapter.task_evidence_register(root, "controller", 1, str(root / "preselection.json"))
    with pytest.raises(ValueError, match="already pending"):
        _preselect(root)
    assert _protected_evidence_bytes(root, task_id) == selected


def test_child_and_wrong_owner_cannot_register_root_preselection(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    child, _handoff = _spawn(root, "implementer", "selection-forger", marker=_selected_message())
    lifecycle._write_session_association(root, task_id, lifecycle._identity_hash("wrong-owner"))
    command = f'thaliris --root "{root}" task-evidence-register --role controller --base-revision 3 --input forged.json'
    before = _protected_evidence_bytes(root, task_id)
    raw, _ = _invoke_hook_command(root, child, command)
    assert "deny" in raw
    raw = lifecycle.handle_hook(root, "PreToolUse", _event(session_id="wrong-owner", tool_name="Bash", tool_input={"command": command}))
    assert "--controller-session-id-hash " + lifecycle._identity_hash("wrong-owner") in raw
    source = root / "forged.json"
    source.write_text(json.dumps({"next_dispatch": {"role": "implementer", "expected_agent_type": "thaliris-implementer",
        "candidate": "forged", "requirement_refs": ["R1"]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="owning Controller"):
        codex_adapter.task_evidence_register(root, "controller", core.task_show(root)["state"]["revision"],
            str(source), lifecycle._identity_hash("wrong-owner"))
    assert core._state_path(root).read_bytes() == before[core._state_path(root)]
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    assert ledger["pending_authorized_spawn"] is None and "next_evidence_dispatch" not in ledger
    assert task_authority.check(root) is not None


def test_reassociated_controller_keeps_legacy_registration_but_cannot_forge_selection_actor(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    lifecycle.associate_task(root, task_id, lifecycle._identity_hash("reassociated"), task_authority.digest(task_authority.path(root)))
    source = root / "legacy-registration.json"
    source.write_text(json.dumps({"requirements": [{"id": "R2", "workchain_ref": "legacy"}]}), encoding="utf-8")
    command = f'thaliris --root "{root}" --task-id {task_id} task-evidence-register --role controller --base-revision 2 --input "{source}"'
    event = _event(session_id="reassociated", tool_name="Bash", tool_input={"command": command})
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", event)
    codex_adapter.task_evidence_register(root, "controller", 2, str(source), lifecycle._identity_hash("reassociated"))
    assert core.task_get(root, "R2")["object"]["workchain_ref"] == "legacy"
    event["tool_input"]["command"] += " --controller-session-id-hash " + lifecycle._identity_hash("evidence-controller-session")
    assert "deny" in lifecycle.handle_hook(root, "PreToolUse", event)


def test_preselection_malformed_registration_and_exact_same_role_profile_refuse(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    before = _protected_evidence_bytes(root, task_id)
    source = root / "invalid-selection.json"
    source.write_text(json.dumps({"requirements": [{"broken": "shape"}], "next_dispatch": {
        "role": "implementer", "expected_agent_type": "thaliris-implementer", "candidate": "C4", "requirement_refs": ["R1"]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="continuity object"):
        codex_adapter.task_evidence_register(root, "controller", 2, str(source), lifecycle._identity_hash("evidence-controller-session"))
    assert _protected_evidence_bytes(root, task_id) == before
    _preselect(root, "focused-implementer", expected_agent_type="thaliris-focused-implementer-xhigh")
    raw = lifecycle.handle_hook(root, "PreToolUse", _opaque_request("focused-implementer"))
    assert "THALIRIS_EVIDENCE_DISPATCH_CONFLICT" in raw
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    assert ledger["next_evidence_dispatch"]["expected_agent_type"] == "thaliris-focused-implementer-xhigh"
    assert ledger["pending_authorized_spawn"] is None


@pytest.mark.parametrize("role", ["investigator", "curator"])
def test_preselection_matching_readable_marker_and_curator_paths_remain_exact(evidence_task, role):
    root, _ = evidence_task
    _register_requirement(root)
    paths = [".agent-memory/selected.md"] if role == "curator" else None
    _preselect(root, role, **({"durable_paths": paths} if paths else {}))
    _child, handoff = _spawn(root, role, "selected-readable", marker=_selected_message("C4", durable_paths=paths))
    assert core.task_get(root, handoff)["object"].get("durable_paths") == paths


@pytest.mark.parametrize("overrides", [{}, {"model": "gpt-6-luna", "reasoning_effort": "max"},
                                      {"model": "gpt-6.1-sol", "reasoning_effort": "high"}])
def test_preselection_preserves_native_defaults_overrides_and_generic_passthrough(evidence_task, overrides):
    root, task_id = evidence_task
    _register_requirement(root)
    _preselect(root, "investigator")
    before = _protected_evidence_bytes(root, task_id)
    generic = _opaque_request()
    generic["tool_input"]["agent_type"] = "default"
    assert lifecycle.handle_hook(root, "PreToolUse", generic) == ""
    assert _protected_evidence_bytes(root, task_id) == before
    request = _opaque_request("investigator", **overrides)
    raw = lifecycle.handle_hook(root, "PreToolUse", request)
    assert "deny" not in raw
    if overrides:
        routed = json.loads(raw)["hookSpecificOutput"]["updatedInput"] if raw else request["tool_input"]
        assert all(routed[key] == value for key, value in overrides.items())
    assert core.task_show(root)["state"]["evidence_continuity"]["handoffs"][-1]["candidate"] == "C4"


def test_concurrent_child_append_selection_and_reservation_share_checkpoint_lock(evidence_task, monkeypatch):
    root, task_id = evidence_task
    _register_requirement(root)
    child, handoff = _spawn(root, "implementer", "concurrent-observer", marker=_selected_message())
    checkpoint_entered, release_checkpoint, check_lock_attempted = threading.Event(), threading.Event(), threading.Event()
    original = task_authority.checkpoint
    original_lock = core._lock
    @contextmanager
    def observed_task_lock(selected_root):
        if threading.current_thread().name.startswith("evidence-root"):
            check_lock_attempted.set()
        with original_lock(selected_root):
            yield
    monkeypatch.setattr(core, "_lock", observed_task_lock)
    def paused_checkpoint(selected_root):
        if threading.current_thread().name.startswith("evidence-append"):
            checkpoint_entered.set()
            assert release_checkpoint.wait(10)
        original(selected_root)
    monkeypatch.setattr(task_authority, "checkpoint", paused_checkpoint)
    def append():
        core.select_task(root, task_id)
        return codex_adapter.task_observe(root, "implementer", handoff, lifecycle._identity_hash(child["agent_id"]),
            observation_json=json.dumps(_observation("O-concurrent")))
    def select_and_reserve():
        core.select_task(root, task_id)
        # The child write is still in progress; authority checking must wait for
        # the checkpoint instead of rejecting its intermediate state digest.
        assert task_authority.check(root) is not None
        _preselect(root, "reviewer")
        return lifecycle._reserve_managed_spawn(root, _opaque_request("reviewer"))
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidence-append") as append_pool, ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidence-root") as root_pool:
        first = append_pool.submit(append)
        try:
            assert checkpoint_entered.wait(10)
            second = root_pool.submit(select_and_reserve)
            assert check_lock_attempted.wait(10)
        finally:
            release_checkpoint.set()
        assert first.result()["ok"] is True
        assert second.result() == ""
    assert core.task_get(root, "O-concurrent")["object"]["handoff_id"] == handoff
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    assert core.task_get(root, ledger["pending_authorized_spawn"]["handoff_id"])["object"]["candidate"] == "C4"
    assert task_authority.check(root) is not None
