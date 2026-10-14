"""Bounded delegation scenarios plus scoped live nested Scanner evidence.

Direct-child wire provenance: isolated codex-cli 0.155.0-alpha.9.2 probe,
2026-09-25. Start/PreToolUse/Stop carry the child's agent_id and turn_id;
all share the root session_id. Child PreToolUse also has agent_type. Start
has neither parent_id nor spawn tool_use_id. The 2026-09-25 live managed CLI
probe verified exact reservation/Start/bound PreToolUse acceptance and parent
continuation for one CLI build. Grandchild events below remain contract-shaped
fixtures for other cases; raw Host wire-byte equality and other Host/Desktop
behavior remain UNKNOWN.
"""
from __future__ import annotations
from tests.host_maintenance_test_support import authorized_host_install, authorized_host_uninstall, legacy_file_hashes

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from pathlib import Path
import subprocess
import threading

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, lifecycle, roles, task_authority


@pytest.fixture
def active(tmp_path: Path, monkeypatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    home = tmp_path / "test-host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    agents = home / "agents"
    agents.mkdir(parents=True)
    for name, (model, effort, role) in roles.agent_profiles().items():
        (agents / name).write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path.parent / "external-task-authority")
    codex_adapter.init(tmp_path)
    started = core.task_start(tmp_path, "bounded scanner", None, None)
    session_hash = hashlib.sha256(b"root-session").hexdigest()
    task_authority.establish(tmp_path, core._load_state(tmp_path), {
        "human_instruction": "Exercise nested scanner lifecycle rules",
        "boundary": "Nested scanner test fixture",
        "invariants": "Preserve task authority and child lifecycle checks",
        "acceptance": "Selected lifecycle checks pass",
        "execution_mode": "delegated",
    }, session_hash)
    lifecycle.record_task_start_owner(tmp_path, started["task_id"], session_hash)
    return tmp_path


def event(**values):
    return {"session_id": "root-session", "turn_id": "root-turn", **values}


def identity(role="implementer", agent="executor"):
    return event(agent_id=agent, agent_type=f"thaliris-{role}", turn_id=f"{agent}-turn")


def spawn(actor=None, role="investigator", *, use_route_defaults=True, **overrides):
    model_pair = roles.ROLE_MODEL_ROUTING_DEFAULTS.get(role) if use_route_defaults else None
    selection = ({"model": model_pair[0], "reasoning_effort": model_pair[1]}
                 if model_pair is not None else {})
    selection.update(overrides)
    return {**(actor or event()), "tool_name": "spawn_agent", "tool_input": {
        "agent_type": f"thaliris-{role}", "fork_turns": "none", "message": "Selected facts only", **selection,
    }}


def state(root):
    task = core.task_show(root)["state"]["task_id"]
    return lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task), task)


def start(root, role="implementer", agent="executor", actor=None):
    model_pair = roles.ROLE_MODEL_ROUTING_DEFAULTS.get(role)
    request = spawn(actor, role, **(
        {"model": model_pair[0], "reasoning_effort": model_pair[1]}
        if model_pair is not None else {}
    ))
    assert lifecycle.handle_hook(root, "PreToolUse", request) == ""
    child = identity(role, agent)
    assert lifecycle._record_subagent_start(root, child)
    lifecycle.handle_hook(root, "PostToolUse", {**request, "tool_response": {"task_name": f"/root/{agent}"}})
    return child


def finish(root, child, observer=None, status="completed"):
    lifecycle.handle_hook(root, "SubagentStop", child)
    lifecycle.handle_hook(root, "PostToolUse", {**(observer or event()), "tool_name": "list_agents", "tool_response": {
        "agents": [{"agent_name": f'/root/{child["agent_id"]}', "agent_status": {status: "result"}}],
    }})


@pytest.mark.parametrize("role", ["implementer", "focused-implementer", "reviewer"])
def test_executor_scanner_parent_binding_and_completion(active, role):
    parent = start(active, role)
    assert not lifecycle.managed_dependency_pending(active, parent)
    scanner = start(active, "investigator", "scanner", parent)
    assert lifecycle.managed_dependency_pending(active, parent)
    assert not lifecycle.managed_dependency_pending(active, scanner)
    children = state(active)["children"]
    assert [child["depth"] for child in children] == [1, 2]
    assert children[1]["parent_agent_id_hash"] == children[0]["agent_id_hash"]
    assert children[1]["parent_turn_id_hash"] == children[0]["turn_id_hash"]
    assert children[1]["root_handoff_id"] == children[0]["handoff_id"]
    assert children[1]["parent_role"] == role
    assert lifecycle.handle_hook(active, "PreToolUse", {**scanner, "tool_name": "read_file", "tool_input": {}}) == ""
    assert "DELEGATION" in lifecycle.handle_hook(active, "PreToolUse", spawn(scanner))
    assert "SCANNER_SLOT_ACTIVE" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent))
    finish(active, scanner, parent)
    assert not lifecycle.native_execution_closed(active)
    finish(active, parent)
    assert lifecycle.native_execution_closed(active)
    assert codex_adapter.task_close(active, core.task_show(active)["state"]["revision"])["status"] == "DONE"


@pytest.mark.parametrize(
    ("case", "field", "status"),
    [
        ("agent_id_mismatch", "agent_id", "MISMATCH"),
        ("agent_id_missing", "agent_id", "MISSING"),
        ("role_mismatch", "role", "MISMATCH"),
        ("role_missing", "role", "MISSING"),
        ("session_mismatch", "session", "MISMATCH"),
        ("session_missing", "session", "MISSING"),
        ("turn_mismatch", "turn", "MISMATCH"),
        ("turn_missing", "turn", "MISSING"),
        ("lifecycle_binding_missing", "lifecycle_binding", "MISSING"),
    ],
)
def test_ordinary_read_records_hash_only_identity_diagnostic(active, case, field, status):
    child = start(active, agent="private-executor-id")
    request = {**child, "tool_name": "read_file", "tool_input": {"path": "private-command-path"}}
    if case == "agent_id_mismatch":
        request["agent_id"] = "different-private-agent"
    elif case == "agent_id_missing":
        request.pop("agent_id")
    elif case == "role_mismatch":
        request["agent_type"] = "thaliris-reviewer"
    elif case == "role_missing":
        request.pop("agent_type")
    elif case == "session_mismatch":
        request["session_id"] = "different-private-session"
    elif case == "session_missing":
        request.pop("session_id")
    elif case == "turn_mismatch":
        request["turn_id"] = "different-private-turn"
    elif case == "turn_missing":
        request.pop("turn_id")
    elif case == "lifecycle_binding_missing":
        task_id = core.task_show(active)["state"]["task_id"]
        path = lifecycle._lifecycle_path(active, task_id)
        ledger = lifecycle._load_lifecycle(path, task_id)
        ledger["children"][0]["handoff_bound"] = False
        lifecycle._write_capture(path, ledger)

    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""

    session = request.get("session_id") or "unknown-session"
    session_dir = hashlib.sha256(session.encode("utf-8")).hexdigest()[:24]
    runtime = json.loads((active / ".context" / "audit" / session_dir / "runtime.json").read_text(encoding="utf-8"))
    diagnostic, = runtime["bound_role_session_denials"]
    assert diagnostic["field_status"][field] == status
    if status == "MISSING":
        assert field in diagnostic["missing_fields"]
    else:
        assert field not in diagnostic["missing_fields"]
    if status == "MISMATCH":
        assert field in diagnostic["mismatch_fields"]
    else:
        assert field not in diagnostic["mismatch_fields"]
    assert len(diagnostic["event_hash"]) == 64
    serialized = json.dumps(diagnostic)
    for raw in (
        "private-executor-id",
        "different-private-agent",
        "private-session",
        "private-turn",
        "private-command-path",
        "thaliris-reviewer",
    ):
        assert raw not in serialized


def test_unavailable_lifecycle_ledger_reports_unknown_identity_comparisons(active, monkeypatch):
    child = start(active, agent="private-executor-id")

    def unavailable_ledger(path, task_id, **kwargs):
        raise OSError("ledger unavailable")

    monkeypatch.setattr(lifecycle, "_load_lifecycle", unavailable_ledger)
    request = {**child, "tool_name": "read_file", "tool_input": {"path": "private-command-path"}}

    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""

    session_dir = hashlib.sha256(request["session_id"].encode("utf-8")).hexdigest()[:24]
    runtime = json.loads((active / ".context" / "audit" / session_dir / "runtime.json").read_text(encoding="utf-8"))
    diagnostic, = runtime["bound_role_session_denials"]
    assert diagnostic["field_status"] == {
        "agent_id": "UNKNOWN",
        "session": "UNKNOWN",
        "turn": "UNKNOWN",
        "role": "UNKNOWN",
        "lifecycle_binding": "UNKNOWN",
    }
    assert diagnostic["missing_fields"] == []
    assert diagnostic["mismatch_fields"] == []
    serialized = json.dumps(diagnostic)
    for raw in ("private-executor-id", "root-session", "executor-turn", "private-command-path", "thaliris-implementer"):
        assert raw not in serialized

    write = {**child, "tool_name": "exec_command", "tool_input": {"cmd": "Set-Content ordinary.txt value"}}
    assert "BOUND_ROLE_SESSION_REQUIRED" in lifecycle.handle_hook(active, "PreToolUse", write)


@pytest.mark.parametrize("wrong_agent", [False, True])
def test_bound_child_pretool_waits_for_concurrent_context_operation(active, monkeypatch, wrong_agent):
    child = start(active)
    request = {**child, "tool_name": "Bash", "tool_input": {"command": "thaliris task-status"}}
    if wrong_agent:
        request["agent_id"] = "different-agent"
    original_lock = core._lock
    attempting_lock = threading.Event()

    @contextmanager
    def observed_lock(root):
        if threading.current_thread() is not threading.main_thread():
            attempting_lock.set()
        with original_lock(root):
            yield

    monkeypatch.setattr(core, "_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with core._lock(active):
            result = pool.submit(lifecycle.handle_hook, active, "PreToolUse", request)
            assert attempting_lock.wait(timeout=5)
            with pytest.raises(FutureTimeoutError):
                result.result(timeout=0.2)
        decision = json.loads(result.result(timeout=5))["hookSpecificOutput"]
        assert decision["permissionDecision"] == "allow"
        assert decision["updatedInput"]["command"].startswith("thaliris task-status ")


def message(actor, target=None, tool_name="send_message"):
    tool_input = {"message": "decision-changing fact"}
    if target is not None:
        tool_input["target"] = target
    return {**actor, "tool_name": tool_name, "tool_input": tool_input}


def test_bound_child_messages_only_root(active):
    child = start(active)
    assert lifecycle.handle_hook(active, "PreToolUse", message(child, "/root")) == ""
    for target in (None, "", "root", "/root/peer", "executor"):
        assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message(child, target))
    for target in (0, ["/root"]):
        assert "deny" in lifecycle.handle_hook(active, "PreToolUse", {**child, "tool_name": "send_message", "tool_input": {"target": target, "message": "fact"}})
    for tool_name in ("followup_task", "send_input"):
        assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message(child, "/root", tool_name))
    assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message({**child, "turn_id": "spoof"}, "/root"))
    # A root call to an unknown native target is native coordination; it
    # neither reuses a managed child nor grants task-control authority.
    assert lifecycle.handle_hook(active, "PreToolUse", message(event(), "/root")) == ""


def test_nested_child_messages_only_exact_parent(active):
    parent = start(active)
    scanner = start(active, "investigator", "scanner", parent)
    for target in ("executor", "/root/executor"):
        assert lifecycle.handle_hook(active, "PreToolUse", message(scanner, target)) == ""
    for target in (None, "", "/root", "scanner", "/root/scanner", "/root/peer"):
        assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message(scanner, target))
    for tool_name in ("followup_task", "send_input"):
        assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message(scanner, "executor", tool_name))
    assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message({**scanner, "agent_id": "spoof"}, "executor"))


def test_nested_message_with_missing_parent_task_name_and_ambiguous_target(active):
    request = spawn(role="implementer")
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    parent = identity()
    assert lifecycle._record_subagent_start(active, parent)
    assert state(active)["children"][0]["task_name_hash"] is None
    scanner = start(active, "investigator", "scanner", parent)
    assert lifecycle.handle_hook(active, "PreToolUse", message(scanner, "executor")) == ""
    assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message(scanner, "/root/executor"))
    task = core.task_show(active)["state"]["task_id"]
    path = lifecycle._lifecycle_path(active, task)
    capture = state(active)
    capture["children"][1]["task_name_hash"] = capture["children"][0]["agent_id_hash"]
    lifecycle._write_capture(path, capture)
    assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message(scanner, "executor"))


def test_nested_child_cannot_message_bound_peer(active):
    parent = start(active)
    first = start(active, "investigator", "first", parent)
    finish(active, first, parent)
    second = start(active, "investigator", "second", parent)
    for target in ("first", "/root/first"):
        assert "deny" in lifecycle.handle_hook(active, "PreToolUse", message(second, target))
    assert lifecycle.handle_hook(active, "PreToolUse", message(second, "/root/executor")) == ""


@pytest.mark.parametrize("role", ["investigator", "curator", "reasoning-specialist", "verifier"])
def test_non_executor_delegation_denied(active, role):
    parent = start(active, role)
    assert "DELEGATION" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent))
    assert state(active)["pending_authorized_spawn"] is None


@pytest.mark.parametrize("target", ["implementer", "focused-implementer", "reviewer", "curator", "reasoning-specialist", "verifier"])
def test_executor_only_delegates_scanner(active, target):
    parent = start(active)
    assert "DELEGATION" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent, target))


@pytest.mark.parametrize("field", ["agent_id", "agent_type", "turn_id", "session_id"])
@pytest.mark.parametrize("missing", [True, False])
def test_nested_exact_parent_identity_fails_closed(active, field, missing):
    parent = start(active)
    request = spawn(parent)
    if missing:
        request.pop(field)
    else:
        request[field] = "wrong"
    assert "deny" in lifecycle.handle_hook(active, "PreToolUse", request)
    assert state(active)["pending_authorized_spawn"] is None


def test_start_consumes_only_exact_reservation_and_requires_own_identity(active):
    parent = start(active)
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent)) == ""
    for changes in ({"session_id": "wrong"}, {"turn_id": None}, {"agent_id": "executor"}, {"agent_type": "thaliris-curator"}):
        assert not lifecycle._record_subagent_start(active, {**identity("investigator", "scanner"), **changes})
        assert state(active)["pending_authorized_spawn"] is not None
    # A previously rejected identity is never rebound; use a fresh native ID.
    scanner = identity("investigator", "fresh-scanner")
    assert lifecycle._record_subagent_start(active, scanner)
    for key in ("agent_id", "agent_type", "turn_id", "session_id"):
        assert "deny" in lifecycle.handle_hook(active, "PreToolUse", {**scanner, key: "wrong", "tool_name": "apply_patch", "tool_input": {}})


def test_parent_stop_before_scanner_start_is_not_terminal_evidence(active):
    parent = start(active)
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent)) == ""
    lifecycle.handle_hook(active, "SubagentStop", parent)
    parent_record = state(active)["children"][0]
    assert "terminal_state" not in parent_record
    assert parent_record["native_terminal_status"] is None
    assert isinstance(parent_record["stop_observed"], int)
    assert lifecycle._record_subagent_start(active, identity("investigator", "scanner"))
    assert state(active)["pending_authorized_spawn"] is None
    finish(active, parent)
    assert not lifecycle.native_execution_closed(active)


def test_spawn_return_is_correlated_to_authorized_parent(active):
    parent = start(active)
    request = spawn(parent)
    request["tool_use_id"] = "nested-spawn-call"
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    scanner = identity("investigator", "scanner")
    assert lifecycle._record_subagent_start(active, scanner)
    for wrong in ({**event()}, {**parent, "turn_id": "wrong"}, parent):
        lifecycle.handle_hook(active, "PostToolUse", {**wrong, "tool_name": "spawn_agent", "tool_response": {"task_name": "/wrong"}})
        assert state(active)["children"][-1]["task_name_hash"] is None
    lifecycle.handle_hook(active, "PostToolUse", {**request, "tool_response": {"task_name": "/root/scanner"}})
    assert state(active)["children"][-1]["task_name_hash"] == lifecycle._identity_hash("/root/scanner")


@pytest.mark.parametrize("role", ["implementer", "focused-implementer", "reviewer"])
def test_parent_wait_preserves_event_duration_with_pending_scanner(active, monkeypatch, role):
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {"status": "PASS", "effective_max_wait_timeout_ms": 60000})
    parent = start(active, role)
    wait_input = {"timeout_ms": 10_000, "future_argument": {"keep": True}}
    wait = {**parent, "tool_name": "wait_agent", "tool_input": wait_input}
    assert codex_adapter.audit_hook(active, "PreToolUse", wait) == ""
    assert wait["tool_input"] == wait_input
    scanner = start(active, "investigator", "scanner", parent)
    assert codex_adapter.audit_hook(active, "PreToolUse", wait) == ""
    assert wait["tool_input"] == wait_input
    finish(active, scanner, parent)
    assert codex_adapter.audit_hook(active, "PreToolUse", wait) == ""


@pytest.mark.parametrize("role", ["implementer", "focused-implementer", "reviewer"])
def test_scanner_slot_reuse_preserves_exact_parent_and_allows_bound_root_sibling(active, role):
    parent = start(active, role)
    # A bound independent sibling does not occupy this parent's Scanner slot.
    curator = start(active, "curator", "independent-curator")
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent)) == ""
    assert "UNBOUND_DISPATCH_PENDING" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent))
    scanner = identity("investigator", "first-scanner")
    assert lifecycle._record_subagent_start(active, scanner)
    lifecycle.handle_hook(active, "PostToolUse", {**spawn(parent), "tool_response": {"task_name": "/root/first-scanner"}})
    lifecycle.handle_hook(active, "SubagentStop", scanner)
    # Optional Stop cannot release the slot without native terminal evidence.
    assert "SCANNER_SLOT_ACTIVE" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent))
    finish(active, scanner, parent)
    second = start(active, "investigator", "second-scanner", parent)
    assert [child["depth"] for child in state(active)["children"]] == [1, 1, 2, 2]
    assert "SCANNER_SLOT_ACTIVE" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent))
    assert "DELEGATION" in lifecycle.handle_hook(active, "PreToolUse", spawn(second))
    finish(active, second, parent)
    finish(active, parent)
    finish(active, curator)
    assert lifecycle.native_execution_closed(active)


def test_active_or_pending_descendant_prevents_close(active):
    parent = start(active)
    scanner = start(active, "investigator", "scanner", parent)
    finish(active, parent)
    assert not lifecycle.native_execution_closed(active)
    # A bound Scanner keeps its own identity after the parent terminates.
    assert lifecycle.handle_hook(active, "PreToolUse", {**scanner, "tool_name": "read_file", "tool_input": {}}) == ""
    finish(active, scanner)
    assert lifecycle.native_execution_closed(active)


def test_latest_scanner_failure_does_not_replace_successful_parent(active):
    parent = start(active)
    scanner = start(active, "investigator", "scanner", parent)
    finish(active, scanner, parent, "errored")
    finish(active, parent)
    assert lifecycle.native_execution_closed(active)


def test_terminal_scanner_and_failed_parent_resolve_execution_only(active):
    parent = start(active)
    scanner = start(active, "investigator", "scanner", parent)
    finish(active, scanner, parent)
    finish(active, parent, status="errored")
    children = state(active)["children"]
    assert {child["native_terminal_status"] for child in children} == {"completed", "errored"}
    assert lifecycle.native_execution_closed(active)


def test_nested_native_terminal_retires_pending_without_granting_managed_child(active):
    parent = start(active)
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent)) == ""
    native_name = "/root/scanner-failed"
    lifecycle.handle_hook(active, "PostToolUse", {**spawn(parent), "tool_response": {"task_name": native_name}})
    lifecycle.handle_hook(active, "PostToolUse", {**parent, "tool_name": "list_agents", "tool_response": {"agents": [{"agent_name": native_name, "agent_status": "shutdown"}]}})
    retired = state(active)
    assert retired["pending_authorized_spawn"] is None
    terminal = next(child for child in retired["children"] if child.get("task_name_hash") == lifecycle._identity_hash(native_name))
    assert terminal["managed"] is False and terminal["handoff_bound"] is False
    assert terminal["native_terminal_status"] == "shutdown"
    assert not lifecycle.native_execution_closed(active)  # the parent Implementer is still running
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent)) == ""


@pytest.mark.parametrize("overrides", [{"model": "gpt-6-luna"}, {"reasoning_effort": "xhigh"},
    {"thinking": "xhigh"}, {"model_reasoning_effort": "xhigh"}, {"model": "gpt-6-astra", "reasoning_effort": "high"}])
def test_native_model_selection_preserves_managed_handoff(active, overrides):
    model_pair = roles.ROLE_MODEL_ROUTING_DEFAULTS["implementer"]
    selection = {"model": model_pair[0], "reasoning_effort": model_pair[1]}
    selection.update(overrides)
    request = spawn(role="implementer", **selection)
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    assert state(active)["pending_authorized_spawn"]["expected_agent_type"] == "thaliris-implementer"
    assert lifecycle._record_subagent_start(active, identity())
    assert state(active)["children"][0]["handoff_bound"] is True


def test_nested_scanner_native_sol_selection_keeps_exact_parent(active):
    parent = start(active)
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent, model="gpt-6.1-sol", reasoning_effort="high")) == ""
    assert state(active)["pending_authorized_spawn"]["parent_agent_id_hash"] == lifecycle._identity_hash(parent["agent_id"])


def test_nested_scanner_cannot_select_astra_without_controller_handoff(active):
    parent = start(active)
    assert "DELEGATION" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent, model="gpt-6-astra", reasoning_effort="xhigh"))
    assert state(active)["pending_authorized_spawn"] is None


@pytest.mark.parametrize("field", ["model", "reasoning_effort", "thinking", "model_reasoning_effort"])
def test_top_level_fallback_native_model_selection_is_authorized(active, field):
    model_pair = roles.ROLE_MODEL_ROUTING_DEFAULTS["implementer"]
    selection = {"model": model_pair[0], "reasoning_effort": model_pair[1]}
    selection[field] = "gpt-6-astra" if field == "model" else "xhigh"
    request = event(
        tool_name="spawn_agent",
        agentType="thaliris-implementer",
        fork_turns="none",
        message="Selected facts only",
        **selection,
    )
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    assert state(active)["pending_authorized_spawn"]["expected_agent_type"] == "thaliris-implementer"


@pytest.mark.parametrize("role", list(roles.ROLE_MODEL_ROUTING_DEFAULTS))
def test_managed_spawn_supplies_default_pair_in_updated_input(active, role):
    request = spawn(role=role, use_route_defaults=False)
    original = dict(request["tool_input"])
    result = json.loads(lifecycle.handle_hook(active, "PreToolUse", request))
    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "allow"
    assert output["updatedInput"]["model"] == roles.ROLE_MODEL_ROUTING_DEFAULTS[role][0]
    assert output["updatedInput"]["reasoning_effort"] == roles.ROLE_MODEL_ROUTING_DEFAULTS[role][1]
    assert request["tool_input"] == original
    assert state(active)["pending_authorized_spawn"]["role"] == role


def test_partial_managed_model_selection_preserves_native_omission_semantics(active):
    model_only = spawn(role="implementer", use_route_defaults=False, model="gpt-5.6-luna")
    assert lifecycle.handle_hook(active, "PreToolUse", model_only) == ""
    assert "reasoning_effort" not in model_only["tool_input"]
    assert state(active)["pending_authorized_spawn"]["expected_agent_type"] == "thaliris-implementer"

    # Retire the pending reservation by binding its expected child before making
    # the next independent dispatch.
    assert lifecycle._record_subagent_start(active, identity())
    effort_only = spawn(role="reviewer", use_route_defaults=False, reasoning_effort="medium")
    output = json.loads(lifecycle.handle_hook(active, "PreToolUse", effort_only))["hookSpecificOutput"]
    assert output["updatedInput"]["model"] == roles.ROLE_MODEL_ROUTING_DEFAULTS["reviewer"][0]
    assert output["updatedInput"]["reasoning_effort"] == "medium"
    assert effort_only["tool_input"]["reasoning_effort"] == "medium"


def test_null_model_fields_are_native_omissions_and_bad_values_do_not_reserve(active):
    omitted = spawn(role="investigator", use_route_defaults=False, model=None, reasoning_effort=None)
    output = json.loads(lifecycle.handle_hook(active, "PreToolUse", omitted))["hookSpecificOutput"]
    assert output["updatedInput"]["model"] == "gpt-6-luna"
    assert output["updatedInput"]["reasoning_effort"] == "max"
    assert lifecycle._record_subagent_start(active, identity("investigator", "investigator-child"))

    for field, value in (("model", ""), ("model", 6), ("reasoning_effort", []), ("reasoning_effort", " ")):
        request = spawn(role="implementer", use_route_defaults=False, **{field: value})
        before = state(active)
        denied = lifecycle.handle_hook(active, "PreToolUse", request)
        assert "ROLE_MODEL_ARGUMENT_INVALID" in denied
        assert state(active) == before


def test_nested_scanner_uses_investigator_default_after_exact_parent_checks(active):
    parent = start(active)
    request = spawn(parent, "investigator", use_route_defaults=False)
    output = json.loads(lifecycle.handle_hook(active, "PreToolUse", request))["hookSpecificOutput"]
    assert output["updatedInput"]["model"] == "gpt-6-luna"
    assert output["updatedInput"]["reasoning_effort"] == "max"
    pending = state(active)["pending_authorized_spawn"]
    assert pending["parent_agent_id_hash"] == lifecycle._identity_hash(parent["agent_id"])


def test_denied_managed_spawn_does_not_return_defaults_or_reserve(active):
    verifier = start(active, role="verifier", agent="verifier-child")
    request = spawn(verifier, "investigator", use_route_defaults=False)
    before = state(active)
    denied = lifecycle.handle_hook(active, "PreToolUse", request)
    assert "DELEGATION" in denied
    assert state(active) == before


def test_readonly_actor_denial_precedes_model_default_and_reservation(active):
    request = spawn(role="implementer", use_route_defaults=False)
    request["readonly"] = True
    before = state(active)
    denied = lifecycle.handle_hook(active, "PreToolUse", request)
    assert "READONLY_ACTOR" in denied
    assert state(active) == before


def test_generic_native_spawn_remains_unmanaged_and_gets_no_thaliris_default(active):
    request = event(tool_name="spawn_agent", tool_input={
        "agent_type": "explorer", "fork_turns": "none", "message": "ordinary native work",
    })
    before = state(active)
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    assert state(active) == before
    assert "model" not in request["tool_input"]
    assert "reasoning_effort" not in request["tool_input"]


def test_model_routing_does_not_edit_user_profile_or_host_config(active, tmp_path, monkeypatch):
    home = tmp_path / "host"
    agents = home / "agents"
    agents.mkdir(parents=True)
    profile = agents / "thaliris-implementer.toml"
    profile_bytes = b'name = "thaliris-implementer"\ndescription = "user role"\ndeveloper_instructions = "user-owned"\n'
    profile.write_bytes(profile_bytes)
    config = home / "config.toml"
    config_bytes = b"# user Host configuration\n[notice]\nlevel = 3\n"
    config.write_bytes(config_bytes)
    monkeypatch.setenv("CODEX_HOME", str(home))

    request = spawn(role="implementer", use_route_defaults=False)
    output = json.loads(lifecycle.handle_hook(active, "PreToolUse", request))["hookSpecificOutput"]
    assert output["updatedInput"]["model"] == "gpt-6-luna"
    assert roles.agent_profiles()["thaliris-implementer.toml"][:2] == (None, None)
    assert profile.read_bytes() == profile_bytes
    assert config.read_bytes() == config_bytes


@pytest.mark.parametrize("role", ["investigator", "implementer"])
def test_top_level_fallback_explicit_luna_max_pair_is_authorized(active, role):
    model, effort = roles.ROLE_MODEL_ROUTING_DEFAULTS[role]
    request = event(
        tool_name="spawn_agent",
        agentType=f"thaliris-{role}",
        fork_turns="none",
        message="Selected facts only",
        model=model,
        reasoning_effort=effort,
    )
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    assert state(active)["pending_authorized_spawn"]["expected_agent_type"] == f"thaliris-{role}"


@pytest.mark.parametrize("role", ["focused-implementer", "reasoning-specialist"])
def test_controller_selects_static_exceptional_profile(active, role):
    profile = f"thaliris-{role}-xhigh"
    assert roles.resolve_native_profile(profile).id == role
    assert roles.agent_profiles()[profile + ".toml"] == ("gpt-6-astra", "xhigh", role)
    request = spawn(role=role, use_route_defaults=False)
    request["tool_input"]["agent_type"] = profile
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    parent = {**identity(role), "agent_type": profile}
    assert lifecycle._record_subagent_start(active, parent)
    assert state(active)["children"][0]["role"] == role
    if role == "focused-implementer":
        assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent)) == ""
    else:
        assert "DELEGATION" in lifecycle.handle_hook(active, "PreToolUse", spawn(parent))


@pytest.mark.parametrize("role", ["focused-implementer", "reasoning-specialist"])
def test_executor_cannot_select_exceptional_profile(active, role):
    parent = start(active)
    request = spawn(parent, role, use_route_defaults=False)
    request["tool_input"]["agent_type"] += "-xhigh"
    assert "DELEGATION" in lifecycle.handle_hook(active, "PreToolUse", request)
    default = (Path(__file__).parent / "fixtures" / f"phase2-{'reasoning-specialist' if role == 'focused-implementer' else role}.toml").read_bytes()
    assert codex_adapter._agent_profile_state(default, f"thaliris-{role}-xhigh.toml") == "user"


@pytest.mark.parametrize("role", ["focused-implementer", "reasoning-specialist"])
def test_static_exceptional_profile_still_rejects_per_spawn_model_override(active, role):
    profile = f"thaliris-{role}-xhigh"
    request = spawn(role=role, use_route_defaults=False)
    request["tool_input"]["agent_type"] = profile
    request["tool_input"]["model"] = "gpt-6-astra"
    request["tool_input"]["reasoning_effort"] = "xhigh"
    assert "ROLE_MODEL_OVERRIDE" in lifecycle.handle_hook(active, "PreToolUse", request)
    assert state(active)["pending_authorized_spawn"] is None


def test_previous_flat_lifecycle_state_is_not_nested_authority(active):
    start(active)
    task = core.task_show(active)["state"]["task_id"]
    path = lifecycle._lifecycle_path(active, task)
    previous = state(active)
    previous["version"] = 11
    path.write_text(json.dumps(previous), encoding="utf-8")
    assert not lifecycle.native_execution_closed(active)
    assert "deny" in lifecycle.handle_hook(active, "PreToolUse", spawn(identity()))


@pytest.mark.parametrize("kind", ["profile", "alias", "filename"])
def test_registry_identity_uniqueness(monkeypatch, kind):
    kwargs = {"native_profile": "new", "profile_filename": "new.toml"}
    kwargs[{"profile": "native_profile", "alias": "native_aliases", "filename": "profile_filename"}[kind]] = {
        "profile": "thaliris-investigator", "alias": ("luna",), "filename": "thaliris-investigator.toml",
    }[kind]
    monkeypatch.setitem(roles.ROLE_REGISTRY, "new", (roles.RoleSpec("new", "test"), roles.CodexExecutionBinding(**kwargs)))
    with pytest.raises(ValueError, match="duplicate"):
        roles.role_choices()


def test_independent_phase_two_profile_migration_and_user_edits(tmp_path, monkeypatch, pinned_test_thaliris):
    # Exact generator at immutable 5e6554196d27c4d6bc87c2a8008bd3c37ef01b31:
    # roles blob 481aba1ef66448238f1b00ff4b58eba3f28f9605;
    # adapter blob 880d5a9753220bcf09f27bc34890e411ccee17c4.
    # Fixtures are fixed UTF-8/LF bytes, never reconstructed from current HEAD.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    codex_adapter.init(tmp_path)
    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    host_agents = host_home / "agents"
    host_agents.mkdir(parents=True)
    for role, digest in roles._PHASE_TWO_PROFILE_HASHES.items():
        value = (Path(__file__).parent / "fixtures" / f"phase2-{role}.toml").read_bytes()
        assert hashlib.sha256(value).hexdigest() == digest
        name = f"thaliris-{role}.toml"
        assert codex_adapter._agent_profile_state(value, name) == "legacy"
        assert codex_adapter._agent_profile_state(value + b"\n# user edit\n", name) == "user"
        (host_agents / name).write_bytes(value)
    packs = (Path(__file__).parent / "fixtures" / "phase2-role-packs.md").read_bytes()
    assert hashlib.sha256(packs).hexdigest() == "0a51833bf936b14053c08a6502a6a1d27ecd1518263e7eea5c4e43f53fa1c5f1"
    assert codex_adapter._role_pack_state(packs) == "legacy"
    (tmp_path / "docs" / "thaliris-role-packs.md").write_bytes(packs)
    install = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes=legacy_file_hashes(
            host_home, [f"agents/thaliris-{role}.toml" for role in roles._PHASE_TWO_PROFILE_HASHES]
        ),
    )
    assert install["host_profile_definition_present"] == "YES"
    assert install["host_role_catalog_status"] == "HOST_ROLE_CATALOG_UNKNOWN"
    migrated = {f"thaliris-{role}.toml" for role in roles._PHASE_TWO_PROFILE_HASHES}
    assert {f"agents/{name}" for name in migrated} <= set(install["files"])
    for name in host_agents.glob("thaliris-*.toml"):
        assert codex_adapter._agent_profile_state(name.read_bytes(), name.name) == "current"
    result = codex_adapter.init(tmp_path)
    assert result["agent_profile_changed"] is False
    assert not (tmp_path / ".codex" / "agents").exists()
    assert (tmp_path / "docs" / "thaliris-role-packs.md").read_text(encoding="utf-8") == codex_adapter.render_role_packs()


def test_profile_quotes_remain_valid_toml():
    import tomllib
    for name, (model, effort, role) in roles.agent_profiles().items():
        parsed = tomllib.loads(codex_adapter._agent_profile(name.removesuffix(".toml"), role, model, effort).decode())
        assert parsed["developer_instructions"] == roles.profile_instructions(role, name.removesuffix(".toml"))
