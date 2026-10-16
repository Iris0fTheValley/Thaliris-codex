from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import subprocess

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
    assert first["requirement_refs"] == second["requirement_refs"] == ["R1"]
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
