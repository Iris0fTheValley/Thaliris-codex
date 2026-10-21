"""Exact official native activity evidence; task names never prove identity."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, codex_app_server, lifecycle
from tests.test_evidence_continuity_adapter import (
    evidence_task, _event, _identity, _register_requirement, _selected_message, _observation,
)

THREAD = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"
CHILD = "33333333-3333-4333-8333-333333333333"
CALL = "call_native_spawn_contract"
NAME = "/root/contract_child"


@pytest.mark.parametrize("event", ["PreModelRequest", "PostModelRequest", "FutureModelEvent"])
def test_unregistered_model_events_cannot_record_child_completion(evidence_task, monkeypatch, event):
    root, task_id = evidence_task
    _register_requirement(root)
    monkeypatch.setattr(codex_app_server, "native_spawn_identity", lambda *_args, **_kwargs: CHILD)
    spawn, child = request(), _identity("implementer", CHILD)
    lifecycle.handle_hook(root, "PreToolUse", spawn)
    lifecycle.handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"task_name": NAME}})
    lifecycle.handle_hook(root, "SubagentStart", child)
    before = {path.relative_to(root): path.read_bytes()
              for path in (root / ".context").rglob("*") if path.is_file()}
    assert lifecycle.handle_hook(root, event, {**child, "cwd": str(root), "model": "gpt-6-luna",
        "status": "completed", "token_usage": {"input_tokens": 3, "output_tokens": 1}}) == ""
    after = {path.relative_to(root): path.read_bytes()
             for path in (root / ".context").rglob("*") if path.is_file()}
    assert after == before
    assert not lifecycle.native_execution_closed(root)


def activity(**changes):
    return {"turnId": TURN, "item": {"type": "subAgentActivity", "kind": "started",
        "id": CALL, "agentThreadId": CHILD, "agentPath": NAME, **changes},
        "startedAtMs": 1792345184895, "completedAtMs": 1792345184895}


class NativeReader:
    def __init__(self, pages, **facts):
        self.pages = iter(pages)
        self.calls = []
        self.facts = {"cli_version": "codex-cli 0.162.0-alpha.17.2",
                      "daemon_home_matches_requested": "YES", **facts}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def connection_facts(self):
        return self.facts

    def request(self, method, params):
        assert method == "thread/items/list"
        self.calls.append(params)
        return next(self.pages)


def resolve(monkeypatch, pages, *, payload=None, **facts):
    reader = NativeReader(pages, **facts)
    monkeypatch.setattr(codex_app_server, "_native_lifecycle_client", lambda _home: reader)
    result = codex_app_server.native_spawn_identity(Path("unused"), payload or {
        "session_id": THREAD, "turn_id": TURN, "tool_use_id": CALL}, NAME)
    return result, reader


def test_native_activity_matches_exact_call_in_exact_parent_turn(monkeypatch):
    result, reader = resolve(monkeypatch, [{"data": [activity()], "nextCursor": None}])
    assert result == CHILD
    assert reader.calls == [{"threadId": THREAD, "turnId": TURN, "limit": 64, "sortDirection": "desc"}]


def test_native_activity_uses_exact_nested_parent_and_paginates_once_per_page(monkeypatch):
    result, reader = resolve(monkeypatch, [
        {"data": [], "nextCursor": "next"}, {"data": [activity()], "nextCursor": None}],
        payload={"session_id": CHILD, "agent_id": THREAD, "turn_id": TURN, "tool_use_id": CALL})
    assert result == CHILD
    assert [call["threadId"] for call in reader.calls] == [THREAD, THREAD]
    assert reader.calls[1]["cursor"] == "next"


@pytest.mark.parametrize("change", [
    {"id": "wrong-call"}, {"kind": "completed"}, {"type": "collabAgentToolCall"},
    {"agentPath": "/root/same-name-other-parent"}, {"agentThreadId": NAME},
    {"agentThreadId": THREAD}, {"agentThreadId": None},
])
def test_native_activity_refuses_wrong_or_incomplete_edge(monkeypatch, change):
    assert resolve(monkeypatch, [{"data": [activity(**change)]}])[0] is None


@pytest.mark.parametrize("page", [
    {"data": [activity(), activity()]}, {"data": [dict(activity(), turnId="wrong-turn")]},
    {"data": "wrong-shape"}, {"data": [None]}, {"data": [], "nextCursor": {}},
])
def test_native_activity_refuses_ambiguous_or_malformed_native_data(monkeypatch, page):
    assert resolve(monkeypatch, [page])[0] is None


@pytest.mark.parametrize("version", ["codex-cli 0.162.0", "codex-cli 0.163.0-alpha.10.2", "UNKNOWN"])
def test_native_activity_accepts_exact_edge_independently_of_reader_version(monkeypatch, version):
    assert resolve(monkeypatch, [{"data": [activity()]}], cli_version=version)[0] == CHILD


def test_native_activity_refuses_wrong_or_unknown_home(monkeypatch):
    assert resolve(monkeypatch, [], daemon_home_matches_requested="NO")[0] is None
    assert resolve(monkeypatch, [], daemon_home_matches_requested="UNKNOWN")[0] is None


def test_native_activity_refuses_repeating_cursor(monkeypatch):
    assert resolve(monkeypatch, [{"data": [], "nextCursor": "repeat"}] * 2)[0] is None


@pytest.mark.parametrize("fields,expected", [
    ({}, ("UNKNOWN", "UNKNOWN")),
    ({"model": None, "reasoningEffort": None}, ("UNKNOWN", "UNKNOWN")),
    ({"model": "gpt-6.1-sol", "reasoningEffort": "high"}, ("MATCH", "MATCH")),
    ({"model": "unexpected-model", "reasoningEffort": "low"}, ("MISMATCH", "MISMATCH")),
    ({"model": {}, "reasoningEffort": 1}, ("INVALID", "INVALID")),
])
def test_optional_routing_observations_never_authorize_or_reject_identity(monkeypatch, fields, expected):
    reader = NativeReader([{"data": [activity(**fields)]}])
    monkeypatch.setattr(codex_app_server, "_native_lifecycle_client", lambda _home: reader)
    observation = {}
    spawn = {**request(), "session_id": THREAD, "turn_id": TURN}
    assert codex_app_server.native_spawn_identity(Path("unused"), spawn, NAME,
        routing_observation=observation) == CHILD
    assert (observation["model"]["status"], observation["reasoningEffort"]["status"]) == expected


def test_invalid_edge_cannot_publish_routing_observation(monkeypatch):
    reader = NativeReader([{"data": [activity(agentPath="/root/forged", model="gpt-6.1-sol")]}])
    monkeypatch.setattr(codex_app_server, "_native_lifecycle_client", lambda _home: reader)
    observation = {}
    assert codex_app_server.native_spawn_identity(Path("unused"), {
        "session_id": THREAD, "turn_id": TURN, "tool_use_id": CALL}, NAME,
        routing_observation=observation) is None
    assert observation == {}


@pytest.mark.parametrize("selection,fields,expected", [
    ({"agent_type": "thaliris-implementer", "model": "gpt-6.1-sol"},
        {"model": "gpt-6.1-sol", "reasoningEffort": "medium"}, ("MATCH", "UNKNOWN")),
    ({"agent_type": "thaliris-focused-implementer"},
        {"model": "gpt-6.1-sol", "reasoningEffort": "high"}, ("MATCH", "MATCH")),
])
def test_routing_observations_preserve_inherited_effort_and_fixed_profile_bindings(monkeypatch, selection, fields, expected):
    reader = NativeReader([{"data": [activity(**fields)]}])
    monkeypatch.setattr(codex_app_server, "_native_lifecycle_client", lambda _home: reader)
    observation = {}
    assert codex_app_server.native_spawn_identity(Path("unused"), {
        "session_id": THREAD, "turn_id": TURN, "tool_use_id": CALL, "tool_input": selection}, NAME,
        routing_observation=observation) == CHILD
    assert (observation["model"]["status"], observation["reasoningEffort"]["status"]) == expected


def test_posttool_records_routing_mismatch_without_changing_hook_binding(evidence_task, monkeypatch):
    root, task_id = evidence_task
    _register_requirement(root)
    spawn = request()
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", spawn)
    # Synthetic fixture identities are not UUIDs, so exercise the lifecycle
    # observation transport independently of the UUID reader tests above.
    def observe(_home, _payload, _name, *, routing_observation):
        routing_observation.update({"model": {"status": "MISMATCH", "observed": "unexpected-model",
            "expected": "gpt-6.1-sol"}, "reasoningEffort": {"status": "MISMATCH", "observed": "low", "expected": "high"}})
        return CHILD
    monkeypatch.setattr(codex_app_server, "native_spawn_identity", observe)
    lifecycle.handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"task_name": NAME}})
    lifecycle.handle_hook(root, "SubagentStart", _identity("implementer", CHILD))
    state = ledger(root, task_id)
    assert state["children"][-1]["managed"] is True
    assert state["native_routing_observations"][-1]["routing"]["model"]["status"] == "MISMATCH"
    report = codex_adapter.doctor(root)["lifecycle_reconciliation"]
    assert report["recorded_routing_status_counts"]["model"]["MISMATCH"] == 1
    assert "unexpected-model" not in json.dumps(report)


def request():
    return _event(tool_name="collaborationspawn_agent", tool_use_id=CALL, tool_input={
        "agent_type": "thaliris-implementer", "fork_turns": "none", "message": _selected_message(),
        "model": "gpt-6.1-sol", "reasoning_effort": "high"})


def ledger(root, task_id):
    return lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)


@pytest.mark.parametrize("start_first", [False, True])
@pytest.mark.parametrize("reused", [False, True])
def test_exact_v2_edge_restores_write_observation_and_nested_scanner(evidence_task, monkeypatch, start_first, reused):
    root, task_id = evidence_task
    _register_requirement(root)
    monkeypatch.setattr(lifecycle, "_dispatch_identity_required", lambda *_args: reused)
    seen = []
    monkeypatch.setattr(codex_app_server, "native_spawn_identity",
        lambda home, payload, name, **_kwargs: seen.append((home, payload["tool_use_id"], name)) or CHILD)
    spawn, child = request(), _identity("implementer", CHILD)
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", spawn)
    if start_first:
        lifecycle.handle_hook(root, "SubagentStart", child)
        assert ledger(root, task_id)["children"][-1]["managed"] is False
    lifecycle.handle_hook(root, "PostToolUse", {**spawn, "tool_response": json.dumps({"task_name": NAME})})
    if not start_first:
        lifecycle.handle_hook(root, "SubagentStart", child)
    record = ledger(root, task_id)["children"][-1]
    assert seen == [(codex_adapter._codex_home(), CALL, NAME)]
    assert record["managed"] is True and record["handoff_bound"] is True
    assert record["native_identity_source"] == "app_server_subagent_activity"
    assert ledger(root, task_id)["pending_authorized_spawn"] is None
    write = {**child, "tool_name": "Bash", "tool_input": {"command": "Set-Content src/accepted.txt accepted"}}
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", write)
    assert codex_adapter.task_observe(root, "implementer", record["handoff_id"], lifecycle._identity_hash(CHILD),
        observation_json=json.dumps(_observation("O-native-edge")))["ok"]
    nested = {**child, "tool_name": "spawn_agent", "tool_use_id": "nested-call", "tool_input": {
        "agent_type": "thaliris-investigator", "fork_turns": "none", "message": "Read only selected code",
        "model": "gpt-6.1-sol", "reasoning_effort": "high"}}
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", nested)
    assert ledger(root, task_id)["pending_authorized_spawn"]["parent_agent_id_hash"] == record["agent_id_hash"]


def test_name_and_single_pending_never_bind_without_native_edge(evidence_task, monkeypatch):
    root, task_id = evidence_task
    _register_requirement(root)
    monkeypatch.setattr(codex_app_server, "native_spawn_identity", lambda *_args, **_kwargs: None)
    spawn = request()
    lifecycle.handle_hook(root, "PreToolUse", spawn)
    lifecycle.handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"task_name": NAME}})
    child = _identity("implementer", CHILD)
    lifecycle.handle_hook(root, "SubagentStart", child)
    record = ledger(root, task_id)["children"][-1]
    assert record["managed"] is False and record["handoff_bound"] is False
    assert ledger(root, task_id)["pending_authorized_spawn"] is not None
    assert "deny" in lifecycle.handle_hook(root, "PreToolUse", {**child,
        "tool_name": "Bash", "tool_input": {"command": "Set-Content x changed"}})
    report = codex_adapter.doctor(root)
    assert report["managed_readiness"]["subagent_start_observed"] == "YES"
    assert report["managed_readiness"]["explicit_handoff_binding_observed"] == "UNKNOWN"


def test_wrong_dispatch_callback_does_not_query_or_consume_reservation(evidence_task, monkeypatch):
    root, task_id = evidence_task
    _register_requirement(root)
    monkeypatch.setattr(codex_app_server, "native_spawn_identity", lambda *_args, **_kwargs: pytest.fail("wrong dispatch queried native identity"))
    spawn = request()
    lifecycle.handle_hook(root, "PreToolUse", spawn)
    before = deepcopy(ledger(root, task_id)["pending_authorized_spawn"])
    for changes in ({"tool_use_id": "old-call"}, {"turn_id": "old-turn"}, {"session_id": "old-session"}):
        lifecycle.handle_hook(root, "PostToolUse", {**spawn, **changes, "tool_response": {"task_name": NAME}})
        assert ledger(root, task_id)["pending_authorized_spawn"] == before


def test_doctor_keeps_recent_decoded_shapes_per_tool_without_wait_inference(evidence_task, monkeypatch):
    root, _ = evidence_task
    for _ in range(12):
        lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="Bash", tool_response="private shell output"))
    monkeypatch.setattr(codex_adapter, "host_wait_mode", lambda *_args: {"status": "UNKNOWN"})
    lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="collaborationwait_agent",
        tool_response=json.dumps({"message": "private wake message", "timed_out": False})))
    lifecycle.handle_hook(root, "PostToolUse", _event(tool_name="collaborationlist_agents",
        tool_response=json.dumps({"agents": [{"agent_name": NAME, "agent_status": "running"}]})))
    report = codex_adapter.doctor(root)
    schemas = report["lifecycle_reconciliation"]["tool_response_schemas"]
    assert schemas["wait_agent"]["response_type"] == "str"
    assert schemas["wait_agent"]["response_keys"] == ["message", "timed_out"]
    assert schemas["list_agents"]["agent_entry_keys"] == ["agent_name", "agent_status"]
    assert report["lifecycle_reconciliation"]["PostToolUse_source_schema_support"] == "PASS"
    assert report["managed_readiness"]["spawn_pretool_observed"] == "UNKNOWN"
    assert "private" not in json.dumps(schemas) and NAME not in json.dumps(schemas)


def test_reused_child_pretool_without_start_cannot_close_from_old_snapshot(evidence_task, monkeypatch):
    root, task_id = evidence_task
    _register_requirement(root)
    monkeypatch.setattr(codex_app_server, "native_spawn_identity", lambda *_args, **_kwargs: CHILD)
    spawn, child = request(), _identity("implementer", CHILD)
    lifecycle.handle_hook(root, "PreToolUse", spawn)
    lifecycle.handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"task_name": NAME}})
    lifecycle.handle_hook(root, "SubagentStart", child)
    completion = _event(tool_name="list_agents", tool_response={"agents": [
        {"agent_name": NAME, "agent_status": {"completed": "old FINAL"}}]})
    lifecycle.handle_hook(root, "PostToolUse", completion)
    assert lifecycle.native_execution_closed(root)
    original = ledger(root, task_id)["children"][-1]
    reused = {**child, "turn_id": "second-native-turn", "tool_name": "Bash",
              "tool_input": {"command": "Get-Content native-marker.txt"}}
    lifecycle.handle_hook(root, "PreToolUse", reused)
    lifecycle.handle_hook(root, "PostToolUse", completion)
    record = ledger(root, task_id)["children"][-1]
    assert record["turn_id_hash"] == original["turn_id_hash"]
    assert record["handoff_id"] == original["handoff_id"]
    assert record["native_turn_identity_unknown"] is True
    assert not lifecycle.native_execution_closed(root)
    assert "deny" in lifecycle.handle_hook(root, "PreToolUse", {**reused,
        "tool_input": {"command": "Set-Content denied.txt changed"}})


def test_same_name_new_dispatch_cannot_inherit_old_call_or_completion(evidence_task, monkeypatch):
    root, task_id = evidence_task
    _register_requirement(root)
    old, fresh = CHILD, "44444444-4444-4444-8444-444444444444"
    monkeypatch.setattr(codex_app_server, "native_spawn_identity",
        lambda _home, payload, _name, **_kwargs: old if payload["tool_use_id"] == CALL else fresh)
    first = request()
    lifecycle.handle_hook(root, "PreToolUse", first)
    lifecycle.handle_hook(root, "PostToolUse", {**first, "tool_response": {"task_name": NAME}})
    lifecycle.handle_hook(root, "SubagentStart", _identity("implementer", old))
    completed = _event(tool_name="list_agents", tool_response={"agents": [
        {"agent_name": NAME, "agent_status": {"completed": "old FINAL"}}]})
    lifecycle.handle_hook(root, "PostToolUse", completed)
    second = {**request(), "tool_use_id": "fresh-call"}
    lifecycle.handle_hook(root, "PreToolUse", second)
    pending = deepcopy(ledger(root, task_id)["pending_authorized_spawn"])
    lifecycle.handle_hook(root, "PostToolUse", {**first, "tool_response": {"task_name": NAME}})
    assert ledger(root, task_id)["pending_authorized_spawn"] == pending
    lifecycle.handle_hook(root, "PostToolUse", {**second, "tool_response": {"task_name": NAME}})
    lifecycle.handle_hook(root, "SubagentStart", _identity("implementer", fresh))
    records = ledger(root, task_id)["children"]
    assert all(record["managed"] and record["handoff_bound"] for record in records)
    assert records[0]["handoff_id"] != records[1]["handoff_id"]
    lifecycle.handle_hook(root, "PostToolUse", completed)
    assert ledger(root, task_id)["children"][-1]["native_terminal_status"] is None
    assert not lifecycle.native_execution_closed(root)


@pytest.mark.parametrize("tool,response", [
    ("list_agents", {"agents": [{"agent_name": NAME, "agent_status": {"completed": "stale"}}]}),
    ("interrupt_agent", {"previous_status": {"completed": "stale"}}),
    ("wait_agent", {"status": {CHILD: {"completed": "stale"}}, "timed_out": False}),
])
def test_reused_session_status_requires_exact_current_task_pretool(evidence_task, monkeypatch, tool, response):
    root, task_id = evidence_task
    _register_requirement(root)
    monkeypatch.setattr(lifecycle, "_dispatch_identity_required", lambda *_args: True)
    monkeypatch.setattr(codex_app_server, "native_spawn_identity", lambda *_args, **_kwargs: None)
    spawn = request()
    lifecycle.handle_hook(root, "PreToolUse", spawn)
    lifecycle.handle_hook(root, "PostToolUse", {**spawn,
        "tool_response": {"agent_id": CHILD, "nickname": None}} if tool == "wait_agent" else
        {**spawn, "tool_response": {"task_name": NAME}})
    pending = deepcopy(ledger(root, task_id)["pending_authorized_spawn"])
    call = _event(tool_name=tool, tool_use_id="current-status-call", tool_input={
        "target": NAME, "targets": [CHILD]})
    # A stale result cannot acquire a current task association from session or name.
    lifecycle.handle_hook(root, "PostToolUse", {**call, "turn_id": "old-A-turn", "tool_response": response})
    assert ledger(root, task_id)["pending_authorized_spawn"] == pending
    lifecycle.handle_hook(root, "PreToolUse", call)
    for changes in ({"tool_use_id": "old-call"}, {"turn_id": "old-A-turn"}):
        lifecycle.handle_hook(root, "PostToolUse", {**call, **changes, "tool_response": response})
        assert ledger(root, task_id)["pending_authorized_spawn"] == pending
    lifecycle.handle_hook(root, "PostToolUse", {**call, "tool_response": response})
    assert ledger(root, task_id)["pending_authorized_spawn"] is None
