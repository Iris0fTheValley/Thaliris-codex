import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from thaliris import core
from thaliris_codex import cli, codex_adapter, codex_bootstrap, lifecycle, roles, task_authority


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "host"))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "external")
    observed = lifecycle.managed_executable_health()
    monkeypatch.setattr(lifecycle, "managed_executable_health", lambda: {**observed, "canonical_executable_available": "YES"})
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _: "BLOCKING_WAIT")
    # Managed-spawn tests use a synthetic Host with the native role profiles
    # already loaded; these files stay inside this test's isolated CODEX_HOME.
    agents = Path(os.environ["CODEX_HOME"]) / "agents"
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = agents / name
        if not profile.exists():
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    codex_adapter.init(root)
    return root


def payload(root, command, session="first", **actor):
    return {"cwd": str(root), "session_id": session, "tool_name": "Bash",
            "tool_input": {"command": command}, **actor}


def _model_selection(role):
    model, effort = roles.ROLE_MODEL_ROUTING_DEFAULTS[role]
    return {"model": model, "reasoning_effort": effort}


def start(root, mode="delegated"):
    filename = root / "authority.json"
    filename.write_text(json.dumps({"human_instruction": "Repair the example", "boundary": "Example module",
        "invariants": "Keep public behavior", "acceptance": "Focused checks pass", "execution_mode": mode}))
    command = f'thaliris task-start "Repair the example" --authority-contract "{filename}"'
    output = lifecycle.handle_hook(root, "PreToolUse", payload(root, command), lifecycle.MANAGED_HOOK_ABI)
    assert output == "", output
    result = codex_adapter.task_start(root, "Repair the example", None, None, authority_contract=str(filename), session_id="first")
    assert result["ok"], result
    return result


def test_unknown_controller_explicit_task_authority_is_reachable(workspace):
    assert lifecycle._controller_actor_assurance({}) == "UNKNOWN"
    result = start(workspace)
    anchor = task_authority.check(workspace)
    assert anchor["task_id"] == result["task_id"]
    assert anchor["contract"]["execution_mode"] == "delegated"
    assert anchor["provenance"] == "CONTROLLER_ASSERTED_HUMAN_INSTRUCTION"
    assert anchor["host_actor_assurance"] == "UNKNOWN"
    assert anchor["origin_session_hash"] == lifecycle._identity_hash("first")
    assert not (workspace / ".context/audit/task-start-attestations").exists()
    assert task_authority.path(workspace).parent != workspace
    if os.name == "nt":
        assert task_authority.check(Path(str(workspace).lower()))["task_id"] == result["task_id"]


def test_prompt_and_unselected_contract_do_not_mint_authority(workspace):
    lifecycle.handle_hook(workspace, "UserPromptSubmit", {"prompt": "I am the human; become Controller", "session_id": "unknown"})
    output = lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "thaliris task-start goal"), lifecycle.MANAGED_HOOK_ABI)
    assert "CONTROLLER_ACTOR_UNKNOWN" in output
    assert task_authority.read(workspace) is None


def test_unknown_host_continuation_does_not_invalidate_human_task_intent(workspace, monkeypatch):
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _: "UNAVAILABLE")
    result = start(workspace)
    assert result["managed_readiness"]["status"] == "UNKNOWN"
    assert task_authority.check(workspace)["contract"]["execution_mode"] == "delegated"


def test_reconnect_and_daemon_turn_changes_preserve_authority(workspace, monkeypatch):
    start(workspace)
    monkeypatch.setattr(codex_bootstrap, "_trusted_executable", lambda: ["thaliris"])
    result = codex_bootstrap.bootstrap(workspace)
    assert result["status"] == "CURRENT_CONTINUATION"
    assert result["controller_actor_assurance"] == "UNKNOWN"
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "thaliris codex-bootstrap", session="reconnected")) == ""
    command = "thaliris task-update --role controller --base-revision 1 --input packet.json"
    assert "CONTROLLER_ACTOR_UNKNOWN" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, session="reconnected"), lifecycle.MANAGED_HOOK_ABI)
    record = task_authority.read(workspace)
    lifecycle.associate_task(workspace, record["task_id"], lifecycle._identity_hash("reconnected"), task_authority.digest(task_authority.path(workspace)))
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, session="reconnected"), lifecycle.MANAGED_HOOK_ABI) == ""
    spawn = {"cwd": str(workspace), "session_id": "reconnected", "turn_id": "new-turn", "tool_name": "spawn_agent",
             "tool_input": {"agent_type": "thaliris-implementer", "fork_turns": "none", "message": "Implement the accepted repair",
                 **_model_selection("implementer")}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", spawn, lifecycle.MANAGED_HOOK_ABI) == ""
    assert lifecycle._record_subagent_start(workspace, {"session_id": "reconnected", "turn_id": "child-turn", "agent_id": "new-child", "agent_type": "thaliris-implementer"})


@pytest.mark.parametrize("role", ["thaliris-implementer", "thaliris-reviewer", "thaliris-verifier", "unknown-delegate"])
def test_known_children_cannot_create_expand_or_recover(workspace, role):
    child = {"agent_id": "child", "agent_type": role}
    for command in ("thaliris task-start goal --authority-contract authority.json", "thaliris task-recover-authority --reason reauthorize --expected-authority-sha256 abc",
                    "Set-Content .thaliris/task-authority/anchor.json '{}'", "thaliris task-update --role controller --base-revision 1 --input changed.json"):
        assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, **child), lifecycle.MANAGED_HOOK_ABI)
    assert task_authority.read(workspace) is None
    start(workspace)
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "thaliris task-recover-authority --reason reauthorize --expected-authority-sha256 abc", **child), lifecycle.MANAGED_HOOK_ABI)


@pytest.mark.parametrize("target", [".context/state.json", ".context/config.json", ".codex/config.toml", "lifecycle"])
def test_repository_tampering_does_not_rebless_authority(workspace, target):
    result = start(workspace)
    original = task_authority.path(workspace).read_bytes()
    path = lifecycle._lifecycle_path(workspace, result["task_id"]) if target == "lifecycle" else (core._state_path(workspace) if target == ".context/state.json" else workspace / target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{}')
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "git status", session="new"), lifecycle.MANAGED_HOOK_ABI) == ""
    assert "TASK_AUTHORITY_CONFLICT" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "thaliris task-update --role controller --base-revision 1 --input packet.json"), lifecycle.MANAGED_HOOK_ABI)
    assert task_authority.path(workspace).read_bytes() == original
    with pytest.raises(ValueError, match="TASK_AUTHORITY"):
        task_authority.check(workspace)
    with pytest.raises(ValueError, match="TASK_AUTHORITY_CHANGED"):
        task_authority.recover(workspace, "0" * 64, "Human selected restore")
    recovered = task_authority.recover(workspace, hashlib.sha256(original).hexdigest(), "Human selected restore of the same intent and original baseline")
    assert recovered["child_death_proof"] == "UNKNOWN"
    assert task_authority.read(workspace)["recoveries"][-1]["death_proof"] == "UNKNOWN"
    assert task_authority.check(workspace)["goal"] == "Repair the example"


def test_recovery_fences_old_children_without_death_claim(workspace):
    result = start(workspace)
    ledger_path = lifecycle._lifecycle_path(workspace, result["task_id"])
    ledger = lifecycle._load_lifecycle(ledger_path, result["task_id"])
    ledger["children"].append({"agent_id_hash": lifecycle._identity_hash("old-child"), "managed": True, "native_terminal_status": None})
    lifecycle._write_capture(ledger_path, ledger)
    original = task_authority.path(workspace).read_bytes()
    ledger_path.unlink()
    task_authority.recover(workspace, hashlib.sha256(original).hexdigest(), "Human selected recovery; fence the old children")
    assert "ABANDONED_ACTOR" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "git status", agent_id="old-child", agent_type="thaliris-implementer"), lifecycle.MANAGED_HOOK_ABI)
    assert lifecycle._load_lifecycle(ledger_path, result["task_id"])["children"] == []


@pytest.mark.parametrize("mode", ["controller-direct", "single-agent"])
def test_explicit_execution_overrides_allow_ordinary_work_and_close_without_spawn(workspace, mode):
    start(workspace, mode)
    for command in ("Get-Content src/example.py", "Set-Content src/example.py fixed", "pytest tests/test_example.py", "git commit -m repair"):
        assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, session="first"), lifecycle.MANAGED_HOOK_ABI) == ""
    spawn = {"session_id": "first", "tool_name": "spawn_agent", "tool_input": {"agent_type": "thaliris-implementer", "fork_turns": "none", "message": "implement",
        **_model_selection("implementer")}}
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", spawn, lifecycle.MANAGED_HOOK_ABI)
    assert codex_adapter.task_close(workspace, 1)["ok"]
    assert task_authority.read(workspace)["status"] == "DONE"


def test_default_delegation_guidance_does_not_gate_ordinary_execution(workspace):
    start(workspace)
    for command in ("pytest tests/test_example.py", "git status", "git diff", "git commit -m repair",
                    "Get-Content src/example.py", "Set-Content src/example.py fixed"):
        assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command), lifecycle.MANAGED_HOOK_ABI) == ""
    assert codex_adapter.task_close(workspace, 1)["ok"]
    assert task_authority.read(workspace)["status"] == "DONE"


@pytest.mark.parametrize("new_task", [False, True])
def test_completed_executor_cannot_write_after_task_close_or_new_task(workspace, new_task):
    started = start(workspace)
    _spawn(workspace)
    actor = {"session_id": "first", "turn_id": "implementer-turn",
        "agent_id": "old-implementer", "agent_type": "thaliris-implementer"}
    assert lifecycle._record_subagent_start(workspace, actor)
    lifecycle.handle_hook(workspace, "PostToolUse", {"session_id": "first", "tool_name": "list_agents",
        "tool_response": {"agents": [{"agent_name": "old-implementer", "agent_status": {"completed": None}}]}})
    assert codex_adapter.task_close(workspace, started["revision"])["status"] == "DONE"
    if new_task:
        start(workspace)
    write = {**actor, "cwd": str(workspace), "tool_name": "Bash", "tool_input": {"command": "Set-Content example.py stale"}}
    assert "CLOSED_ROLE_SESSION" in lifecycle.handle_hook(workspace, "PreToolUse", write, lifecycle.MANAGED_HOOK_ABI)
    read = {**write, "tool_input": {"command": "Get-Content example.py"}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", read, lifecycle.MANAGED_HOOK_ABI) == ""


def test_completed_executor_identity_cannot_write_during_active_task_without_role_fields(workspace):
    started = start(workspace)
    _spawn(workspace)
    actor = {"session_id": "first", "turn_id": "implementer-turn",
        "agent_id": "old-implementer", "agent_type": "thaliris-implementer"}
    assert lifecycle._record_subagent_start(workspace, actor)
    lifecycle.handle_hook(workspace, "PostToolUse", {"session_id": "first", "tool_name": "list_agents",
        "tool_response": {"agents": [{"agent_name": "old-implementer", "agent_status": {"completed": None}}]}})
    assert core.task_show(workspace)["state"]["status"] == "ACTIVE"
    exact_identity = {"cwd": str(workspace), "agent_id": "old-implementer"}
    for tool_name, tool_input in (
        ("Bash", {"command": "Set-Content example.py stale"}),
        ("apply_patch", {"patch": "*** Begin Patch\n*** Update File: example.py\n*** End Patch"}),
    ):
        result = lifecycle.handle_hook(workspace, "PreToolUse", {
            **exact_identity, "tool_name": tool_name, "tool_input": tool_input,
        }, lifecycle.MANAGED_HOOK_ABI)
        assert "TERMINAL_ROLE_SESSION" in result
    read = lifecycle.handle_hook(workspace, "PreToolUse", {
        **exact_identity, "tool_name": "Bash", "tool_input": {"command": "Get-Content example.py"},
    }, lifecycle.MANAGED_HOOK_ABI)
    assert read == ""


def test_missing_legacy_lifecycle_is_unknown_and_deleted_anchored_lifecycle_is_rejected(workspace):
    started = start(workspace)
    path = lifecycle._lifecycle_path(workspace, started["task_id"])
    path.unlink()
    assert not lifecycle.native_execution_closed(workspace)
    with pytest.raises(ValueError, match="LIFECYCLE_CHANGED"):
        codex_adapter.task_close(workspace, started["revision"])


def test_disposition_without_native_identity_fence_cannot_clear_execution_risk(workspace):
    started = start(workspace)
    _spawn(workspace)
    actor = {"session_id": "first", "turn_id": "implementer-turn",
        "agent_id": "executor", "agent_type": "thaliris-implementer"}
    assert lifecycle._record_subagent_start(workspace, actor)
    path = lifecycle._lifecycle_path(workspace, started["task_id"])
    state = lifecycle._load_lifecycle(path, started["task_id"])
    original = dict(state["children"][0])
    state["children"][0]["management_disposition"] = "ABANDONED_DEPENDENCY"
    state["dependency_dispositions"] = [{"kind": "child", "record": original}]
    lifecycle._write_capture(path, state)
    assert not lifecycle.native_execution_closed(workspace)


def test_healthy_hook_blocks_reviewer_git_commit_and_host_profile_patches(workspace):
    start(workspace)
    _spawn(workspace, role="reviewer")
    child = {"cwd": str(workspace), "session_id": "first", "turn_id": "reviewer-turn",
        "agent_id": "reviewer", "agent_type": "thaliris-reviewer", "tool_name": "Bash",
        "tool_input": {"command": "git commit -m changed"}}
    assert lifecycle._record_subagent_start(workspace, child)
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", child, lifecycle.MANAGED_HOOK_ABI)

    home = Path(os.environ["CODEX_HOME"])
    for path in (home / "agents/thaliris-controller.toml",
                 home / "thaliris-host-generations/g1/config.toml"):
        patch_call = {"cwd": str(workspace), "session_id": "first", "tool_name": "apply_patch",
            "tool_input": {"patch": f"*** Update File: {path}\n+changed"}}
        result = lifecycle.handle_hook(workspace, "PreToolUse", patch_call, lifecycle.MANAGED_HOOK_ABI)
        assert "CONTROL_STATE_DIRECT_WRITE" in result

    source_patch = {"cwd": str(workspace), "session_id": "first", "tool_name": "apply_patch",
        "tool_input": {"patch": "*** Update File: src/example.py\n+changed"}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", source_patch, lifecycle.MANAGED_HOOK_ABI) == ""


def test_damaged_agent_navigation_keeps_known_reviewer_peer_message_denied(workspace):
    started = start(workspace)
    _spawn(workspace, role="reviewer")
    child = {"session_id": "first", "turn_id": "reviewer-turn", "agent_id": "reviewer",
        "agent_type": "thaliris-reviewer"}
    assert lifecycle._record_subagent_start(workspace, child)
    assert task_authority.check(workspace)["task_id"] == started["task_id"]
    assert core._load_state(workspace, active=True)["task_id"] == started["task_id"]
    lifecycle_path = lifecycle._lifecycle_path(workspace, started["task_id"])
    assert lifecycle._load_lifecycle(lifecycle_path, started["task_id"])["children"][0]["handoff_bound"] is True

    agent_hash = lifecycle._identity_hash("reviewer")
    agent_association = lifecycle._association_path(workspace, agent_hash, "agent")
    agent_association.write_bytes(b"{damaged agent navigation only")
    core.select_task(workspace, None)
    assert core.selected_task(workspace) is None

    call = {"cwd": str(workspace), "session_id": "first", "turn_id": "reviewer-turn",
        "agent_id": "reviewer", "tool_name": "send_message",
        "tool_input": {"target": "ordinary-peer", "message": "continue independent work"}}
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", call, lifecycle.MANAGED_HOOK_ABI)
    assert core.selected_task(workspace) is None

    unknown = {**call, "agent_id": "ordinary-agent"}
    assert lifecycle.handle_hook(workspace, "PreToolUse", unknown, lifecycle.MANAGED_HOOK_ABI) == ""
    assert core.selected_task(workspace) is None


@pytest.mark.parametrize("with_stop", [False, True])
def test_controller_direct_auxiliary_close_requires_native_completed_independent_of_stop(workspace, with_stop):
    start(workspace, "controller-direct")
    identity = {"session_id": "first", "turn_id": "aux-turn"}
    spawn = {**identity, "tool_name": "spawn_agent", "tool_input": {
        "agent_type": "thaliris-reviewer", "fork_turns": "none", "message": "selected review",
        **_model_selection("reviewer"),
    }}
    assert lifecycle.handle_hook(workspace, "PreToolUse", spawn, lifecycle.MANAGED_HOOK_ABI) == ""
    child = {**identity, "agent_id": "reviewer-id", "agent_type": "thaliris-reviewer"}
    assert lifecycle.handle_hook(workspace, "SubagentStart", child) == ""
    if with_stop:
        assert lifecycle.handle_hook(workspace, "SubagentStop", child) == ""
    with pytest.raises(ValueError, match="resolved native execution risk"):
        codex_adapter.task_close(workspace, 1)
    observed = {**identity, "tool_name": "list_agents", "tool_response": {
        "agents": [{"agent_name": "reviewer-id", "agent_status": {"completed": "review result"}}],
    }}
    assert lifecycle.handle_hook(workspace, "PostToolUse", observed) == ""
    assert core.task_show(workspace)["state"]["status"] == "ACTIVE"
    assert codex_adapter.task_close(workspace, 1)["ok"]


def test_abandoned_authority_is_not_reactivated_by_state_or_prompt(workspace):
    start(workspace)
    state_path = core._state_path(workspace)
    previous = state_path.read_bytes()
    state_path.unlink()
    task_authority.checkpoint(workspace)
    assert task_authority.read(workspace)["status"] == "ABANDONED"
    state_path.write_bytes(previous)
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "git status"), lifecycle.MANAGED_HOOK_ABI) == ""
    assert "TASK_AUTHORITY_CONFLICT" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "thaliris task-update --role controller --base-revision 1 --input packet.json"), lifecycle.MANAGED_HOOK_ABI)


def test_checked_abandon_retires_external_authority_and_preserves_fence(workspace):
    result = start(workspace)
    # Exercise a known owner observation separately from contract admission.
    lifecycle.record_task_start_owner(workspace, result["task_id"], lifecycle._identity_hash("first"))
    state_path = core._state_path(workspace)
    ledger_path = lifecycle._lifecycle_path(workspace, result["task_id"])
    command = (f'thaliris task-abandon --task-id {result["task_id"]} --revision 1 '
               f'--state-sha256 {task_authority.digest(state_path)} --lifecycle-sha256 {task_authority.digest(ledger_path)} --reason abandon')
    output = lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, session="replacement"), lifecycle.MANAGED_HOOK_ABI)
    rewritten = json.loads(output)["hookSpecificOutput"]["updatedInput"]["command"]
    token = rewritten.split("--hook-attestation ", 1)[1]
    assert codex_adapter.task_abandon(workspace, result["task_id"], 1, task_authority.digest(state_path), task_authority.digest(ledger_path), "abandon", token)["ok"]
    assert task_authority.read(workspace)["status"] == "ABANDONED"
    assert "ABANDONED_ACTOR" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "thaliris task-start new --authority-contract authority.json"), lifecycle.MANAGED_HOOK_ABI)
    # Deleting the mutable repository fence cannot remove the external fence.
    lifecycle._session_fence_path(workspace).unlink()
    assert "ABANDONED_ACTOR" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "git status"), lifecycle.MANAGED_HOOK_ABI)


def test_command_updates_checkpoint_without_expanding_contract(workspace, capsys):
    start(workspace, "single-agent")
    packet = workspace / "packet.json"
    packet.write_text('{"active_work":["repair"]}')
    task_id = core.selected_task(workspace)
    assert cli.main(["--root", str(workspace), "--task-id", task_id, "task-update", "--role", "controller", "--base-revision", "1", "--input", str(packet)]) == 0
    capsys.readouterr()
    assert task_authority.check(workspace)["contract"]["boundary"] == "Example module"
    assert core._load_state(workspace)["revision"] == 2


def test_explicit_contract_cli_admission_requires_no_hook_or_receipt(workspace, capsys):
    filename = workspace / "contract.json"
    filename.write_text(json.dumps({"human_instruction": "Repair", "boundary": "Example",
        "invariants": "Preserve bytes", "acceptance": "Checks pass", "execution_mode": "single-agent"}))
    assert cli.main(["--root", str(workspace), "task-start", "Repair", "--authority-contract", str(filename)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["task_authority"]["host_actor_assurance"] == "UNKNOWN"
    assert result["managed_readiness"]["HOST_INSTRUCTION_ACTIVE"] == "UNKNOWN"
    assert result["managed_readiness"]["controller_activation_bridge"] == "NOT_APPLICABLE"


@pytest.mark.parametrize("option", ["--bootstrap-receipt", "--controller-bridge-sha256"])
@pytest.mark.parametrize("proof", ["0" * 64, "", "invalid"])
def test_optional_incorrect_bridge_is_rejected_without_bearer(workspace, capsys, option, proof):
    filename = workspace / "contract.json"
    filename.write_text(json.dumps({"human_instruction": "Repair", "boundary": "Example",
        "invariants": "Preserve bytes", "acceptance": "Checks pass", "execution_mode": "single-agent"}))
    assert cli.main(["--root", str(workspace), "task-start", "Repair", "--authority-contract", str(filename),
                     option, proof]) == 3
    assert "CONTROLLER_BRIDGE_REQUIRED" in capsys.readouterr().out
    assert task_authority.read(workspace) is None
    assert not core._state_path(workspace).exists()


def test_optional_correct_bridge_without_bearer_preserves_unknown_observation(workspace):
    filename = workspace / "contract.json"
    filename.write_text(json.dumps({"human_instruction": "Repair", "boundary": "Example",
        "invariants": "Preserve bytes", "acceptance": "Checks pass", "execution_mode": "single-agent"}))
    bridge = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    result = codex_adapter.task_start(workspace, "Repair", None, None,
        authority_contract=str(filename), controller_bridge_sha256=bridge)
    assert result["ok"]
    assert result["managed_readiness"]["HOST_INSTRUCTION_ACTIVE"] == "UNKNOWN"


def test_optional_bearer_remains_strict_even_with_explicit_human_contract(workspace, monkeypatch):
    filename = workspace / "contract.json"
    filename.write_text(json.dumps({"human_instruction": "Repair", "boundary": "Example",
        "invariants": "Preserve bytes", "acceptance": "Checks pass", "execution_mode": "single-agent"}))
    calls = []
    def reject(*args):
        calls.append(args)
        raise ValueError("MANAGED_CURRENT_SESSION_NOT_ATTESTED")
    monkeypatch.setattr(lifecycle, "consume_task_start_attestation", reject)
    with pytest.raises(ValueError, match="MANAGED_CURRENT_SESSION_NOT_ATTESTED"):
        codex_adapter.task_start(workspace, "Repair", None, None, hook_attestation="invalid-proof",
            controller_bridge_sha256=codex_adapter._controller_bridge()["controller_bridge_sha256"],
            authority_contract=str(filename))
    assert len(calls) == 1
    assert task_authority.read(workspace) is None


@pytest.mark.parametrize("tool", ["mcp__codex_app__list_projects", "mcp__codex_app__create_thread"])
def test_delegated_controller_can_coordinate_separate_codex_session(workspace, tool):
    start(workspace)
    value = {"cwd": str(workspace), "session_id": "first", "tool_name": tool,
             "tool_input": {"prompt": "Authorized independent Host maintenance", "target": {"type": "projectless"}}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", value, lifecycle.MANAGED_HOOK_ABI) == ""
    for actor in ({"readonly": True}, {"agent_id": "known-child", "agent_type": "thaliris-implementer"}):
        observed = lifecycle.handle_hook(workspace, "PreToolUse", {**value, **actor}, lifecycle.MANAGED_HOOK_ABI)
        # Listing is an ordinary read. Creating a separate executing task is
        # coordination authority and remains unavailable to known children.
        assert ("deny" in observed) if tool.endswith("create_thread") else observed == ""
    impostor = {**value, "tool_name": "mcp__unrelated__" + tool.rsplit("__", 1)[-1]}
    assert lifecycle.handle_hook(workspace, "PreToolUse", impostor, lifecycle.MANAGED_HOOK_ABI) == ""
    assert lifecycle.handle_hook(workspace, "PreToolUse", {**value, "tool_name": "send_message"}, lifecycle.MANAGED_HOOK_ABI) == ""


@pytest.mark.parametrize("actor", [{"readonly": True}, {"fenced": True}])
def test_explicit_contract_does_not_override_known_actor_restrictions(workspace, actor):
    command = 'thaliris task-start repair --authority-contract contract.json'
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, **actor))
    assert task_authority.read(workspace) is None
    start(workspace, "single-agent")
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "Set-Content example.py changed", **actor))


def test_unknown_actor_invalid_contract_is_not_admitted(workspace, capsys):
    filename = workspace / "invalid.json"
    filename.write_text('{"human_instruction": "repair"}')
    assert cli.main(["--root", str(workspace), "task-start", "repair", "--authority-contract", str(filename)]) == 2
    assert "TASK_AUTHORITY_CONTRACT_REQUIRED" in capsys.readouterr().out
    assert task_authority.read(workspace) is None
    assert not core._state_path(workspace).exists()


def _spawn(root, message="Selected repair", call="dispatch-1", role="implementer"):
    value = {"session_id": "first", "turn_id": "controller-turn", "tool_use_id": call,
        "tool_name": "spawn_agent", "tool_input": {"agent_type": "thaliris-" + role,
        "fork_turns": "none", "message": message, **_model_selection(role)}}
    assert lifecycle.handle_hook(root, "PreToolUse", value, lifecycle.MANAGED_HOOK_ABI) == ""
    return value


def test_unknown_dependency_disposition_preserves_task_and_allows_mode_cas(workspace):
    started = start(workspace)
    original_contract = dict(task_authority.check(workspace)["contract"])
    _spawn(workspace)
    path = lifecycle._lifecycle_path(workspace, started["task_id"])
    before = json.loads(path.read_text(encoding="utf-8"))
    pending = before["pending_authorized_spawn"]
    digest = task_authority.digest(path)
    for revision, expected in ((started["revision"] + 1, digest), (started["revision"], "0" * 64)):
        with pytest.raises(ValueError, match="conflict|CHANGED"):
            lifecycle.task_dispose_dependency(workspace, pending["handoff_id"], revision, expected, "Drop this dependency")
        assert json.loads(path.read_text(encoding="utf-8")) == before
    result = lifecycle.task_dispose_dependency(workspace, pending["handoff_id"], started["revision"], digest, "Drop this dependency; isolate possible writes")
    assert result["native_execution"] == result["death_proof"] == result["writing_risk"] == "UNKNOWN"
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["dependency_dispositions"][0]["record"] == pending
    assert not lifecycle.managed_dependency_pending(workspace)
    changed = task_authority.switch_mode(workspace, task_authority.digest(task_authority.path(workspace)), result["revision"], "single-agent", "User selected direct execution")
    assert changed["task_id"] == started["task_id"]
    assert {**task_authority.check(workspace)["contract"], "execution_mode": original_contract["execution_mode"]} == original_contract
    assert core.task_show(workspace)["state"]["goal"] == "Repair the example"
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace,
        "thaliris task-dispose-dependency --handoff-id h --base-revision 1 --expected-lifecycle-sha256 x --reason unauthorized",
        agent_id="old-reviewer", agent_type="thaliris-reviewer"), lifecycle.MANAGED_HOOK_ABI)


def test_two_bound_workstreams_run_before_either_is_final(workspace):
    started = start(workspace)
    _spawn(workspace)
    assert lifecycle._record_subagent_start(workspace, {"session_id": "first", "turn_id": "child-1-turn", "agent_id": "child-1", "agent_type": "thaliris-implementer"})
    _spawn(workspace, message="Independent worktree repair", call="dispatch-2")
    assert lifecycle._record_subagent_start(workspace, {"session_id": "first", "turn_id": "child-2-turn", "agent_id": "child-2", "agent_type": "thaliris-implementer"})
    ledger = json.loads(lifecycle._lifecycle_path(workspace, started["task_id"]).read_text(encoding="utf-8"))
    assert len(ledger["children"]) == 2
    assert all(child["managed"] and "terminal_state" not in child for child in ledger["children"])


def test_disposed_child_stays_fenced_after_mode_change_and_late_result(workspace):
    started = start(workspace)
    _spawn(workspace, role="reviewer")
    assert lifecycle._record_subagent_start(workspace, {"session_id": "first", "turn_id": "review-turn", "agent_id": "reviewer", "agent_type": "thaliris-reviewer"})
    path = lifecycle._lifecycle_path(workspace, started["task_id"])
    child = json.loads(path.read_text(encoding="utf-8"))["children"][0]
    disposed = lifecycle.task_dispose_dependency(workspace, child["handoff_id"], started["revision"], task_authority.digest(path), "No longer rely on this review")
    task_authority.switch_mode(workspace, task_authority.digest(task_authority.path(workspace)), disposed["revision"], "controller-direct", "User chose direct work")
    child_call = payload(workspace, "Set-Content example.py changed", agent_id="reviewer", agent_type="thaliris-reviewer", turn_id="review-turn")
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", child_call, lifecycle.MANAGED_HOOK_ABI)
    ledger = lifecycle._load_lifecycle(path, started["task_id"])
    assert lifecycle._record_native_terminal(ledger, ledger["children"][0], "completed", "wait_agent")
    assert ledger["children"][0]["native_terminal_status"] is None
    assert ledger["children"][0]["management_disposition"] == "ABANDONED_DEPENDENCY"
    closed = codex_adapter.task_close(workspace, disposed["revision"] + 1)
    assert closed["task_disposition"] == "CLOSED_BY_CONTROLLER"
    assert closed["native_execution"] == "UNKNOWN"
    assert closed["death_proof"] == "UNKNOWN" and closed["writing_risk"] == "UNKNOWN"
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", child_call, lifecycle.MANAGED_HOOK_ABI)


@pytest.mark.parametrize("actor", [{"readonly": True}, {"agent_id": "reviewer", "agent_type": "thaliris-reviewer"}])
def test_unknown_or_damaged_task_never_relaxes_readonly(workspace, actor):
    started = start(workspace, "single-agent")
    task_authority.path(workspace).write_text("{broken", encoding="utf-8")
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "Set-Content public.py changed", **actor), lifecycle.MANAGED_HOOK_ABI)
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, "Get-Content public.py", **actor), lifecycle.MANAGED_HOOK_ABI) == ""


def test_state_recovery_requires_selected_task_and_preserves_legacy_bytes(workspace, capsys):
    legacy = workspace / ".context/state.json"
    original = b'{"status":"ACTIVE","task_id":"7e500c6a-6aec-4e22-94b0-42cc6a5459ef"}'
    legacy.write_bytes(original)
    result = cli.main(["--root", str(workspace), "task-recover-state", "--expected-sha256",
        hashlib.sha256(original).hexdigest(), "--abandon-active"])
    assert result != 0
    assert "explicit --task-id or associated --session-id required" in capsys.readouterr().out
    assert legacy.read_bytes() == original


def test_same_session_new_task_does_not_inherit_or_guess_old_reservation(workspace):
    old = start(workspace)
    _spawn(workspace)
    old_path = lifecycle._lifecycle_path(workspace, old["task_id"])
    old_bytes = old_path.read_bytes()
    new = start(workspace)
    spawn = _spawn(workspace, call="new-dispatch")
    observed = {"session_id": "first", "turn_id": "new-child-turn", "agent_id": "new-child", "agent_type": "thaliris-implementer"}
    assert not lifecycle._record_subagent_start(workspace, observed)
    assert old_path.read_bytes() == old_bytes
    lifecycle.handle_hook(workspace, "PostToolUse", {**spawn, "tool_response": {"agent_id": "new-child", "nickname": None}}, lifecycle.MANAGED_HOOK_ABI)
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(workspace, new["task_id"]), new["task_id"])
    assert ledger["children"][0]["managed"] is True
    assert ledger["pending_authorized_spawn"] is None


@pytest.mark.parametrize("count,limit", [(10, 128), (1, 128), (201, 128), (10, None), (10, 8192)])
def test_controller_reads_are_not_mechanically_limited(workspace, count, limit):
    start(workspace)
    call = payload(workspace, f"Get-Content README.md -TotalCount {count}")
    call["tool_name"] = "functions.exec_command"
    if limit is not None:
        call["tool_input"]["max_output_tokens"] = limit
    result = lifecycle.handle_hook(workspace, "PreToolUse", call)
    assert result == ""


@pytest.mark.parametrize("command", ["Get-Content (dir) -TotalCount 10", "rg --files src", "rg -n known_symbol src"])
def test_controller_discovery_tools_remain_available(workspace, command):
    start(workspace)
    call = payload(workspace, command)
    call["tool_name"] = "functions.exec_command"
    call["tool_input"]["max_output_tokens"] = 128
    assert lifecycle.handle_hook(workspace, "PreToolUse", call) == ""


@pytest.mark.parametrize("agent_type", ["worker", "explorer", None])
def test_unknown_actor_active_native_spawn_is_ordinary_and_cannot_consume_managed_handoff(workspace, agent_type):
    started = start(workspace)
    _spawn(workspace)
    path = lifecycle._lifecycle_path(workspace, started["task_id"])
    before = path.read_bytes()
    tool_input = {"message": "Independent native work", "fork_turns": "all", "model": "native-selection"}
    if agent_type is not None:
        tool_input["agent_type"] = agent_type
    call = {"session_id": "first", "tool_name": "spawn_agent", "tool_input": tool_input}
    assert lifecycle.handle_hook(workspace, "PreToolUse", call) == ""
    lifecycle.handle_hook(workspace, "PostToolUse", {**call, "tool_response": {"agent_id": "ordinary-child", "nickname": None}})
    assert path.read_bytes() == before
    child = {"session_id": "first", "agent_id": "ordinary-child", "agent_type": agent_type or "default"}
    assert lifecycle.handle_hook(workspace, "SubagentStart", child) == ""
    assert path.read_bytes() == before
    for tool in ("send_message", "followup_task", "send_input", "interrupt_agent", "close_agent", "wait_agent", "list_agents"):
        coordination = {"session_id": "first", "tool_name": tool,
            "tool_input": {"target": "ordinary-child", "id": "ordinary-child", "message": "Selected supplement"}}
        assert lifecycle.handle_hook(workspace, "PreToolUse", coordination) == ""
        lifecycle.handle_hook(workspace, "PostToolUse", {**coordination, "tool_response": {"previous_status": {"completed": "native result"}}})
        assert path.read_bytes() == before
    for command in ("Set-Content example.py changed", "git status"):
        assert lifecycle.handle_hook(workspace, "PreToolUse", {**child,
            "tool_name": "Bash", "tool_input": {"command": command}}) == ""
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", {**child,
        "tool_name": "Bash", "tool_input": {"command": "thaliris task-update --role controller --base-revision 1 --input packet.json"}})
    assert lifecycle._load_lifecycle(path, started["task_id"])["pending_authorized_spawn"] is not None


@pytest.mark.parametrize("damage", ["none", "association", "authority"])
def test_unknown_ordinary_native_spawn_survives_damaged_control_evidence(workspace, damage):
    start(workspace)
    if damage == "association":
        lifecycle._association_path(workspace, lifecycle._identity_hash("first"), "session").write_text("{broken")
    elif damage == "authority":
        task_authority.path(workspace).write_text("{broken")
    call = {"cwd": str(workspace), "session_id": "first", "tool_name": "spawn_agent",
        "tool_input": {"agent_type": "worker", "message": "Independent native source repair"}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", call) == ""
    call["tool_input"]["agent_type"] = "thaliris-implementer"
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", call)


@pytest.mark.parametrize("tool,response", [
    ("wait_agent", {"status": {"ordinary-child": {"completed": "native result"}}, "timed_out": False}),
    ("list_agents", {"agents": [{"agent_name": "ordinary-child", "agent_status": {"completed": "native result"}}]}),
])
def test_native_ordinary_completion_shapes_do_not_release_managed_reservation(workspace, tool, response):
    started = start(workspace)
    _spawn(workspace)
    path = lifecycle._lifecycle_path(workspace, started["task_id"])
    before = path.read_bytes()
    call = {"session_id": "first", "tool_name": tool, "tool_input": {"targets": ["ordinary-child"]}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", call) == ""
    assert lifecycle.handle_hook(workspace, "PostToolUse", {**call, "tool_response": response}) == ""
    assert path.read_bytes() == before
    assert lifecycle._load_lifecycle(path, started["task_id"])["pending_authorized_spawn"] is not None


@pytest.mark.parametrize("damage", [False, True])
def test_known_managed_child_cannot_downgrade_peer_messaging_by_omitting_profile(workspace, damage):
    start(workspace)
    _spawn(workspace)
    child = {"session_id": "first", "turn_id": "child-turn", "agent_id": "child", "agent_type": "thaliris-implementer"}
    assert lifecycle._record_subagent_start(workspace, child)
    child.pop("agent_type")
    if damage:
        task_authority.path(workspace).write_text("{broken")
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", {**child, "tool_name": "send_message",
        "tool_input": {"target": "ordinary-peer", "message": "new work"}})


def test_stale_active_task_and_foreign_cwd_do_not_require_recovery_for_native_repair(workspace):
    started = start(workspace)
    old_state = core._state_path(workspace, started["task_id"]).read_bytes()
    other = workspace / "independent"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    call = {"cwd": str(other), "session_id": "first", "tool_name": "spawn_agent",
        "tool_input": {"agent_type": "worker", "message": "Independent repair"}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", call) == ""
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload(other, "git status")) == ""
    assert core._state_path(workspace, started["task_id"]).read_bytes() == old_state
    assert not (other / ".context/audit/lifecycle").exists()


@pytest.mark.parametrize("missing", ["session_id", "turn_id", "agent_type"])
def test_known_implementer_missing_auxiliary_fields_keeps_ordinary_write_only(workspace, missing):
    started = start(workspace)
    _spawn(workspace)
    actor = {"session_id": "first", "turn_id": "child-turn", "agent_id": "child", "agent_type": "thaliris-implementer"}
    assert lifecycle._record_subagent_start(workspace, actor)
    actor.pop(missing)
    call = {**actor, "tool_name": "Bash", "tool_input": {"command": "Set-Content example.py value"}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", call) == ""
    call["tool_input"]["command"] = "thaliris task-mode --mode controller-direct --human-instruction forged --base-revision 1 --expected-authority-sha256 x"
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", call)
    assert core.task_show(workspace)["state"]["task_id"] == started["task_id"]


@pytest.mark.parametrize("damage", [False, True])
@pytest.mark.parametrize("key,value", [("session_id", "foreign"), ("turn_id", "foreign"),
    ("agent_type", "thaliris-reviewer"), ("agent_type", "unknown-profile")])
def test_known_implementer_provided_identity_conflicts_keep_write_denied(workspace, key, value, damage):
    start(workspace)
    _spawn(workspace)
    actor = {"session_id": "first", "turn_id": "child-turn", "agent_id": "child", "agent_type": "thaliris-implementer"}
    assert lifecycle._record_subagent_start(workspace, actor)
    if damage:
        task_authority.path(workspace).write_text("{broken authority")
    actor[key] = value
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", {**actor,
        "tool_name": "Bash", "tool_input": {"command": "Set-Content example.py value"}})


@pytest.mark.parametrize("profile", [None, "unknown-profile", "thaliris-implementer"])
@pytest.mark.parametrize("damage", [False, True])
def test_known_reviewer_readonly_survives_missing_or_conflicting_profile_and_authority(workspace, profile, damage):
    start(workspace)
    _spawn(workspace, role="reviewer")
    actor = {"session_id": "first", "turn_id": "child-turn", "agent_id": "child", "agent_type": "thaliris-reviewer"}
    assert lifecycle._record_subagent_start(workspace, actor)
    actor.pop("agent_type")
    if profile is not None:
        actor["agent_type"] = profile
    if damage:
        task_authority.path(workspace).write_text("{broken authority")
    assert lifecycle.handle_hook(workspace, "PreToolUse", {**actor,
        "tool_name": "Bash", "tool_input": {"command": "Get-Content example.py"}}) == ""
    for tool, inputs in (("Bash", {"command": "Set-Content example.py value"}),
            ("mcp__files__write_file", {"path": "example.py", "content": "value"})):
        assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", {**actor,
            "tool_name": tool, "tool_input": inputs})


@pytest.mark.parametrize("existing", ["foreign", "malformed", "directory"])
def test_native_agent_association_claim_never_overwrites_existing_bytes(workspace, existing):
    first = start(workspace)
    second = start(workspace)
    identity = lifecycle._identity_hash("collision-child")
    target = lifecycle._association_path(workspace, identity, "agent")
    target.parent.mkdir(parents=True, exist_ok=True)
    if existing == "directory":
        target.mkdir()
    else:
        target.write_text("bad map" if existing == "malformed" else json.dumps({"version": 1,
            "task_id": first["task_id"], "agent_id_hash": identity}))
    raw = target.read_bytes() if target.is_file() else None
    assert not lifecycle._claim_agent_association(workspace, second["task_id"], identity)
    _spawn(workspace)
    path = lifecycle._lifecycle_path(workspace, second["task_id"])
    pending = json.loads(path.read_bytes())["pending_authorized_spawn"]
    assert not lifecycle._record_subagent_start(workspace, {"session_id": "first", "turn_id": "child-turn",
        "agent_id": "collision-child", "agent_type": "thaliris-implementer"})
    ledger = json.loads(path.read_bytes())
    assert ledger["pending_authorized_spawn"] == pending
    assert not any(child["managed"] for child in ledger["children"])
    assert target.read_bytes() == raw if raw is not None else target.is_dir()


def test_interleaved_spawn_callback_cannot_upgrade_foreign_native_identity(workspace):
    first = start(workspace)
    second = start(workspace)
    call_b = _spawn(workspace, call="call-B")
    child_b = {"session_id": "first", "turn_id": "B-child-turn", "agent_id": "native-X", "agent_type": "thaliris-implementer"}
    assert lifecycle.handle_hook(workspace, "SubagentStart", child_b) == ""
    path_b = lifecycle._lifecycle_path(workspace, second["task_id"])
    pending_b = json.loads(path_b.read_bytes())["pending_authorized_spawn"]
    core.select_task(workspace, first["task_id"])
    lifecycle.associate_task(workspace, first["task_id"], lifecycle._identity_hash("fresh-session"),
        task_authority.digest(task_authority.path(workspace)))
    call_a = {"session_id": "fresh-session", "turn_id": "A-controller-turn", "tool_use_id": "call-A",
        "tool_name": "spawn_agent", "tool_input": {"agent_type": "thaliris-implementer", "fork_turns": "none", "message": "A handoff",
            **_model_selection("implementer")}}
    assert lifecycle.handle_hook(workspace, "PreToolUse", call_a) == ""
    assert lifecycle.handle_hook(workspace, "SubagentStart", {**child_b, "session_id": "fresh-session", "turn_id": "A-child-turn"}) == ""
    map_path = lifecycle._association_path(workspace, lifecycle._identity_hash("native-X"), "agent")
    original_map = map_path.read_bytes()
    path_a = lifecycle._lifecycle_path(workspace, first["task_id"])
    original_a = path_a.read_bytes()
    assert lifecycle.handle_hook(workspace, "PostToolUse", {**call_b,
        "tool_response": {"agent_id": "native-X", "nickname": None}}) == ""
    after_b = json.loads(path_b.read_bytes())
    assert after_b["pending_authorized_spawn"] == pending_b
    assert not any(child["managed"] for child in after_b["children"])
    assert map_path.read_bytes() == original_map
    assert path_a.read_bytes() == original_a


def test_concurrent_absent_native_association_claim_has_one_owner(workspace):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    first, second = start(workspace), start(workspace)
    identity = lifecycle._identity_hash("racing-native")
    ready = threading.Barrier(2)
    def claim(task_id):
        ready.wait(timeout=5)
        return lifecycle._claim_agent_association(workspace, task_id, identity)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (first["task_id"], second["task_id"])))
    assert sorted(results) == [False, True]
    owner = (first, second)[results.index(True)]["task_id"]
    other = (first, second)[results.index(False)]["task_id"]
    target = lifecycle._association_path(workspace, identity, "agent")
    raw = target.read_bytes()
    assert json.loads(raw)["task_id"] == owner
    assert not lifecycle._claim_agent_association(workspace, other, identity)
    assert target.read_bytes() == raw
