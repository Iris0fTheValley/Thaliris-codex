"""Focused semantics for selected history-backed evidence/recovery fixes.

The V2 interrupted rows match the selected 2026-11-11 Controller observation;
completed result text is synthetic. These tests do not probe native wake ingress.
"""
import hashlib
import json
import shlex

import pytest

from thaliris import authority, core
from thaliris_codex import cli, codex_adapter, controller_instructions as guidance, lifecycle, task_authority
from tests.test_evidence_continuity_adapter import (
    evidence_task, _event, _invoke_hook_command, _observation, _register_requirement, _selected_message, _spawn,
    _preselect, _opaque_request, _protected_evidence_bytes,
)


def observe_native(root, rows, actor=None, call_id="native-status"):
    request = {**(actor or _event()), "tool_name": "list_agents", "tool_use_id": call_id, "tool_input": {}}
    lifecycle.handle_hook(root, "PreToolUse", request)
    lifecycle.handle_hook(root, "PostToolUse", {**request, "tool_response": {"agents": rows}})


def wait(root, actor=None):
    return lifecycle.handle_hook(root, "PreToolUse", {
        **(actor or _event()), "tool_name": "wait_agent", "tool_input": {"timeout_ms": 3600000}})


@pytest.mark.parametrize("mode", ["single-agent", "controller-direct", "delegated"])
def test_controller_local_hook_cli_cas_and_schema(evidence_task, capsys, mode):
    root, task_id = evidence_task
    # Test-only authority mode setup; production changes require human decisions.
    anchor = task_authority.read(root)
    anchor["contract"]["execution_mode"] = mode
    task_authority.write(root, anchor)
    _register_requirement(root)
    before = core.task_show(root)["state"]
    assert before["schema_version"] == core._STATE_SCHEMA_VERSION
    body = {**_observation("O-local", candidate="O2", requirement_refs=["R1"]), "base_revision": before["revision"]}
    command = f'thaliris --root "{root}" --task-id {task_id} task-observe --role controller --observation-json ' + shlex.quote(json.dumps(body))
    raw, _ = _invoke_hook_command(root, _event(), command)
    updated = json.loads(raw)["hookSpecificOutput"]["updatedInput"]["command"]
    assert "--controller-session-id-hash" in updated
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    after = core.task_show(root)["state"]
    local = core.task_get(root, "O-local")["object"]
    assert local["handoff_id"] is None and local["producer"] == "controller"
    assert local["provenance"] == "controller-local"
    assert not {"native_actor", "native_status", "submitted_by"} & local.keys()
    assert after["schema_version"] == core._STATE_SCHEMA_VERSION and after["revision"] == before["revision"] + 1
    assert task_authority.check(root)["contract"]["execution_mode"] == mode
    saved = core._state_path(root).read_bytes()
    with pytest.raises(core.ThalirisError, match="revision"):
        codex_adapter.task_observe(root, "controller", None, None, observation_json=json.dumps(body),
                                  controller_session_id_hash=anchor["origin_session_hash"])
    assert core._state_path(root).read_bytes() == saved


def test_local_provenance_refuses_missing_or_forged_context(evidence_task, monkeypatch):
    root, task_id = evidence_task
    _register_requirement(root)
    child, _ = _spawn(root, "investigator", "known-child", marker=_selected_message())
    state = core.task_show(root)["state"]
    owner = lifecycle.active_controller_owner(root, task_id)
    body = {**_observation("O-local", candidate="O2", requirement_refs=["R1"]), "base_revision": state["revision"]}
    saved = core._state_path(root).read_bytes()
    for changes in ({"candidate": None}, {"requirement_refs": []}, {"requirement_refs": ["unknown"]},
                    {"native_actor": "0" * 64}, {"native_status": "completed"}, {"handoff_id": None},
                    {"producer": "controller"}, {"provenance": "controller-local"}, {"base_revision": None}):
        with pytest.raises(ValueError):
            codex_adapter.task_observe(root, "controller", None, None, observation_json=json.dumps({**body, **changes}),
                                      controller_session_id_hash=owner)
    for session in (None, "0" * 64):
        with pytest.raises(ValueError):
            codex_adapter.task_observe(root, "controller", None, None, observation_json=json.dumps(body), controller_session_id_hash=session)
    command = f'thaliris --root "{root}" --task-id {task_id} task-observe --role controller --controller-session-id-hash {owner} --observation-json ' + shlex.quote(json.dumps(body))
    assert "deny" in _invoke_hook_command(root, child, command, readonly=True)[0]
    assert "deny" in _invoke_hook_command(root, _event(session_id="other"), command)[0]
    assert "THALIRIS_READONLY_ACTOR" in _invoke_hook_command(root, _event(), command, readonly=True)[0]
    monkeypatch.setattr(lifecycle, "_session_fenced", lambda root, actor: True)
    with pytest.raises(ValueError, match="unfenced owning Controller"):
        codex_adapter.task_observe(root, "controller", None, None, observation_json=json.dumps(body), controller_session_id_hash=owner)
    assert core._state_path(root).read_bytes() == saved


def test_contract_diagnostic_is_bounded_and_does_not_echo_values():
    with pytest.raises(core.ThalirisError) as caught:
        authority.validate_contract({"human_instruction": "secret", "scope": "private", "invariants": [], "acceptance": "ok",
                                     **{f"unknown-{i}": "private" for i in range(25)}})
    details = caught.value.details
    assert details["missing_fields"] == ["boundary"]
    assert details["invalid_fields"] == ["invariants"]
    assert details["unknown_field_count"] == 26 and len(details["unknown_fields"]) == 16
    assert "private" not in json.dumps(caught.value.to_dict()) and "secret" not in json.dumps(details)


def test_dispatch_and_close_diagnostics_preserve_pending_and_cas(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    _preselect(root)
    for reserved in (False, True):
        if reserved:
            assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", _opaque_request())
        before = _protected_evidence_bytes(root, task_id)
        with pytest.raises(core.ThalirisError) as caught:
            _preselect(root)
        assert caught.value.code == "EVIDENCE_DISPATCH_PENDING"
        details = caught.value.details
        assert details["kind"] == ("authorized-reservation" if reserved else "unconsumed-selection")
        assert details["selection"]["expected_agent_type"] == "thaliris-implementer"
        assert details["reservation_cancelled"] is False
        assert details["expected_lifecycle_sha256"] == task_authority.digest(lifecycle._lifecycle_path(root, task_id))
        assert _protected_evidence_bytes(root, task_id) == before
        if not reserved:
            assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in wait(root)
    assert "THALIRIS_WAIT_DEPENDENCY_UNKNOWN" in wait(root)
    lifecycle.handle_hook(root, "PostToolUse", {**_opaque_request(), "tool_response": {"error": "dispatch or cleanup failed"}})
    assert "THALIRIS_WAIT_DEPENDENCY_UNKNOWN" in wait(root)
    lifecycle.handle_hook(root, "PostToolUse", {**_opaque_request(), "tool_response": {"agent_id": "pending-native-id", "nickname": None}})
    assert wait(root) == ""  # exact native identity, still awaiting Start/result
    before = _protected_evidence_bytes(root, task_id)
    with pytest.raises(core.ThalirisError) as caught:
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])
    assert caught.value.code == "TASK_NATIVE_EXECUTION_RISK"
    diagnostic = caught.value.details
    assert diagnostic["blockers"][0]["kind"] == "authorized-reservation"
    assert diagnostic["blockers"][0]["handoff_id"]
    assert diagnostic["base_revision"] == core.task_show(root)["state"]["revision"]
    assert _protected_evidence_bytes(root, task_id) == before


def test_empty_and_ended_native_dependencies_do_not_enter_long_wait(evidence_task):
    root, _ = evidence_task
    assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in wait(root)
    _register_requirement(root)
    for name in ("completed", "interrupted"):
        _spawn(root, "investigator", name, marker=_selected_message())
    assert wait(root) == ""
    observe_native(root, [{"agent_name": "/root", "agent_status": "running"},
                          {"agent_name": "/root/completed", "agent_status": {"completed": "fixture result"}},
                          {"agent_name": "/root/interrupted", "agent_status": "interrupted"}])
    decision = wait(root)
    assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in decision
    assert "external process termination remains UNKNOWN" in decision
    # not_found cannot erase terminal facts.
    observe_native(root, [{"agent_name": "/root/interrupted", "agent_status": "not_found"}], call_id="absent")
    assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in wait(root)


def test_close_unbound_conflict_selector_is_exact_after_disposed_child(evidence_task):
    root, task_id = evidence_task
    _, first = _spawn(root, "investigator", "retired")
    _spawn(root, "investigator", "unbound")
    path = lifecycle._lifecycle_path(root, task_id)
    lifecycle.task_dispose_dependency(root, first, core.task_show(root)["state"]["revision"],
                                      task_authority.digest(path), "explicit fixture dependency decision")
    ledger = lifecycle._load_lifecycle(path, task_id)
    second = ledger["children"][1]
    second.pop("handoff_id")
    second["native_status_conflict"] = True
    lifecycle._write_capture(path, ledger)
    expected = lifecycle._conflict_id("child", 1, second["agent_id_hash"])
    with pytest.raises(core.ThalirisError) as caught:
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])
    details = caught.value.details
    blocker = next(row for row in details["blockers"] if row["kind"] == "child-native-execution-unresolved")
    assert blocker["conflict_id"] == expected
    lifecycle.task_dispose_dependency(root, None, details["base_revision"], details["expected_lifecycle_sha256"],
                                      "explicit exact conflict decision", blocker["conflict_id"])
    assert lifecycle.native_execution_closed(root)
    assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in wait(root)


def test_reused_or_missing_identity_is_unknown_not_completion(evidence_task):
    root, task_id = evidence_task
    child, _ = _spawn(root, "investigator", "reuse")
    observe_native(root, [{"agent_name": "/root/reuse", "agent_status": "not_found"}])
    assert "THALIRIS_WAIT_DEPENDENCY_UNKNOWN" in wait(root)
    for i, status in enumerate(("running", "interrupted", "running", {"completed": "late old result"})):
        observe_native(root, [{"agent_name": "/root/reuse", "agent_status": status}], call_id=f"status-{i}")
    assert "THALIRIS_WAIT_DEPENDENCY_UNKNOWN" in wait(root)
    assert not lifecycle.native_execution_closed(root)
    assert "deny" in _invoke_hook_command(root, {**child, "turn_id": "new-turn"}, "Set-Content source.py changed")[0]
    diagnostic = lifecycle.native_execution_diagnostic(root)
    assert diagnostic["blockers"] and diagnostic["expected_lifecycle_sha256"] == task_authority.digest(lifecycle._lifecycle_path(root, task_id))


def test_nested_wait_only_uses_direct_dependencies(evidence_task):
    root, _ = evidence_task
    parent, _ = _spawn(root, "implementer", "executor")
    assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in wait(root, parent)
    scanner, _ = _spawn(root, "investigator", "scanner", parent=parent)
    assert wait(root, parent) == ""
    observe_native(root, [{"agent_name": "/root/scanner", "agent_status": "interrupted"}], actor=parent)
    assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in wait(root, parent)
    assert wait(root) == ""  # the Controller still needs its executor


@pytest.mark.parametrize("conflict", ["reused-turn", "identity-collision"])
def test_nested_wait_ignores_attributed_sibling_conflict_but_spawn_and_close_do_not(evidence_task, conflict):
    root, task_id = evidence_task
    parent, _ = _spawn(root, "implementer", "parent-a")
    _spawn(root, "investigator", "scanner-a", parent=parent)
    sibling, _ = _spawn(root, "implementer", "parent-b")
    assert wait(root, parent) == ""
    # Real identity ingestion, not a patched _bound_child_record or authority.
    lifecycle.handle_hook(root, "SubagentStart", {
        **sibling, **({"turn_id": "parent-b-reused-turn"} if conflict == "reused-turn" else {})})
    path = lifecycle._lifecycle_path(root, task_id)
    before = lifecycle._load_lifecycle(path, task_id)
    assert lifecycle._undisposed_identity_conflicts(before)
    assert wait(root, parent) == ""
    assert "scope=direct-dependency" in wait(root)
    assert "THALIRIS_NATIVE_IDENTITY_COLLISION" in lifecycle.handle_hook(root, "PreToolUse", {
        **_event(), "tool_name": "spawn_agent", "tool_input": {
            "agent_type": "thaliris-implementer", "fork_turns": "none", "message": "new handoff"}})
    assert not lifecycle.native_execution_closed(root)
    with pytest.raises(core.ThalirisError, match="native"):
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])
    after = lifecycle._load_lifecycle(path, task_id)
    for field in ("children", "identity_collisions", "pending_authorized_spawn"):
        assert after.get(field) == before.get(field)


def test_controller_wait_ignores_conflict_in_grandchild_but_parent_wait_does_not(evidence_task):
    root, _ = evidence_task
    parent, _ = _spawn(root, "implementer", "executor")
    scanner, _ = _spawn(root, "investigator", "scanner", parent=parent)
    lifecycle.handle_hook(root, "SubagentStart", {**scanner, "turn_id": "reused-scanner-turn"})
    assert wait(root) == ""
    assert "scope=direct-dependency" in wait(root, parent)


@pytest.mark.parametrize("conflict", ["reused-turn", "identity-collision"])
def test_v1_wait_scopes_conflicts_to_explicit_direct_targets(evidence_task, conflict):
    root, _ = evidence_task
    _spawn(root, "implementer", "target-a")
    sibling, _ = _spawn(root, "implementer", "target-b")
    lifecycle.handle_hook(root, "SubagentStart", {
        **sibling, **({"turn_id": "reused-b"} if conflict == "reused-turn" else {})})
    def targeted(targets):
        return lifecycle.handle_hook(root, "PreToolUse", {
            **_event(), "tool_name": "wait_agent", "tool_input": {"targets": targets}})
    assert targeted(["target-a"]) == ""
    assert "scope=direct-dependency" in targeted(["target-b"])
    assert "scope=target-selection" in targeted(["unassociated"])
    assert "THALIRIS_WAIT_NO_UNFINISHED_DEPENDENCY" in targeted([])


def test_exact_v1_actor_target_survives_name_reuse_without_accepting_stale_v2_status(evidence_task):
    root, task_id = evidence_task
    _spawn(root, "implementer", "old-actor")
    observe_native(root, [{"agent_name": "/root/old-actor", "agent_status": {"completed": "old result"}}])
    _spawn(root, "implementer", "fresh-actor")
    path = lifecycle._lifecycle_path(root, task_id)
    state = lifecycle._load_lifecycle(path, task_id)
    # A fresh dispatch can reuse a V2 name with a distinct exact native actor;
    # test_native_spawn_identity covers its real-shaped native dispatch edge.
    state["children"][1]["task_name_hash"] = state["children"][0]["task_name_hash"]
    lifecycle._write_capture(path, state)
    assert lifecycle.handle_hook(root, "PreToolUse", {**_event(), "tool_name": "wait_agent",
        "tool_input": {"targets": ["fresh-actor"]}}) == ""
    assert "scope=direct-dependency" in wait(root)
    observe_native(root, [{"agent_name": "/root/old-actor", "agent_status": {"completed": "stale result"}}], call_id="stale")
    after = lifecycle._load_lifecycle(path, task_id)
    assert after["children"][1]["native_terminal_status"] is None
    assert after["children"][0]["native_terminal_status"] == "completed"


@pytest.mark.parametrize("actor", ["original-caller", "reused-caller", "scanner"])
def test_wait_refuses_caller_or_ancestor_conflict_without_unmanaged_fallthrough(evidence_task, actor):
    root, _ = evidence_task
    parent, _ = _spawn(root, "implementer", "executor")
    scanner, _ = _spawn(root, "investigator", "scanner", parent=parent)
    lifecycle.handle_hook(root, "SubagentStart", {**parent, "turn_id": "reused-executor-turn"})
    caller = {"original-caller": parent, "reused-caller": {**parent, "turn_id": "reused-executor-turn"},
              "scanner": scanner}[actor]
    decision = wait(root, caller)
    assert "THALIRIS_WAIT_DEPENDENCY_UNKNOWN" in decision
    assert ("scope=ancestor" if actor == "scanner" else "scope=caller") in decision
    assert "deny" in _invoke_hook_command(root, caller, "Set-Content source.py changed", readonly=actor == "scanner")[0]


@pytest.mark.parametrize("kind", ["unknown-actor", "no-participants", "overflow", "unrecorded", "malformed", "unknown-handoff", "handoff-only"])
def test_wait_keeps_unattributable_collision_unknown_with_bounded_diagnosis(evidence_task, kind):
    root, task_id = evidence_task
    parent, _ = _spawn(root, "implementer", "executor")
    _spawn(root, "investigator", "scanner", parent=parent)
    sibling, sibling_handoff = _spawn(root, "implementer", "sibling")
    path = lifecycle._lifecycle_path(root, task_id)
    state = lifecycle._load_lifecycle(path, task_id)
    known = {"agent_id_hash": lifecycle._identity_hash(sibling["agent_id"])}
    collision = {
        "unknown-actor": {"agent_id_hash": lifecycle._identity_hash("unknown")},
        "no-participants": {"private-native-text": "private" * 10000},
        "overflow": {"overflow": lifecycle._COLLISION_OVERFLOW, "first_unrecorded": known, "unrecorded_count": 2},
        "unknown-handoff": {**known, "pending_handoff_id": "unassociated-handoff"},
        "handoff-only": {"pending_handoff_id": sibling_handoff},
        "unrecorded": known,
        "malformed": "private" * 10000,
    }[kind]
    state["identity_collisions"] = [collision]
    if kind == "unrecorded":
        state[lifecycle._UNRECORDED_COLLISIONS] = 1
    lifecycle._write_capture(path, state)
    decision = wait(root, parent)
    assert "THALIRIS_WAIT_DEPENDENCY_UNKNOWN" in decision and "scope=unattributed" in decision
    assert "private" not in decision and len(decision) < 1100


@pytest.mark.parametrize("mutation", ["child-turn", "child-role", "child-root", "caller-root", "duplicate-name", "missing-identity", "malformed-identity"])
def test_wait_does_not_hide_ambiguous_relevant_association(evidence_task, mutation):
    root, task_id = evidence_task
    parent, _ = _spawn(root, "implementer", "executor")
    _spawn(root, "investigator", "scanner", parent=parent)
    _spawn(root, "implementer", "sibling")
    path = lifecycle._lifecycle_path(root, task_id)
    state = lifecycle._load_lifecycle(path, task_id)
    caller, scanner, sibling = state["children"]
    if mutation == "duplicate-name":
        sibling["task_name_hash"] = scanner["task_name_hash"]
    elif mutation == "missing-identity":
        for key in ("agent_id_hash", "native_agent_id_hash", "task_name_hash"):
            scanner.pop(key, None)
    elif mutation == "malformed-identity":
        scanner["task_name_hash"] = ["invalid"]
    elif mutation == "caller-root":
        caller["root_handoff_id"] = "unassociated-handoff"
    else:
        scanner[{"child-turn": "parent_turn_id_hash", "child-role": "parent_role", "child-root": "root_handoff_id"}[mutation]] = "unassociated"
    lifecycle._write_capture(path, state)
    decision = wait(root, parent)
    assert "THALIRIS_WAIT_DEPENDENCY_UNKNOWN" in decision
    scope = ("direct-dependency" if mutation in {"duplicate-name", "missing-identity", "malformed-identity"}
             else "caller" if mutation == "caller-root" else "unattributed")
    assert f"scope={scope}" in decision


@pytest.mark.parametrize("mutation", ["identity", "association"])
def test_conflicting_record_needs_proof_before_being_classified_unrelated(evidence_task, mutation):
    root, task_id = evidence_task
    parent, _ = _spawn(root, "implementer", "executor")
    _spawn(root, "investigator", "scanner", parent=parent)
    sibling, _ = _spawn(root, "implementer", "sibling")
    lifecycle.handle_hook(root, "SubagentStart", {**sibling, "turn_id": "reused-sibling"})
    path = lifecycle._lifecycle_path(root, task_id)
    state = lifecycle._load_lifecycle(path, task_id)
    row = state["children"][-1]
    for key in (("agent_id_hash", "native_agent_id_hash", "task_name_hash") if mutation == "identity" else ("root_handoff_id",)):
        row.pop(key, None)
    lifecycle._write_capture(path, state)
    assert "scope=unattributed" in wait(root, parent)


def test_nested_reservation_is_local_and_collision_cannot_hide_its_other_participant(evidence_task):
    root, task_id = evidence_task
    parent, _ = _spawn(root, "implementer", "parent-a")
    scanner, _ = _spawn(root, "investigator", "scanner-a", parent=parent)
    sibling, _ = _spawn(root, "implementer", "parent-b")
    request = {**sibling, "tool_name": "spawn_agent", "tool_input": {
        "agent_type": "thaliris-investigator", "fork_turns": "none", "message": "selected scanner"}}
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", request)
    assert wait(root, parent) == ""
    assert "reserved dispatch has no observable native identity" in wait(root, sibling)
    lifecycle.handle_hook(root, "PostToolUse", {**request, "tool_response": {
        "agent_id": "scanner-b", "nickname": None}})
    assert wait(root, sibling) == ""
    path = lifecycle._lifecycle_path(root, task_id)
    state = lifecycle._load_lifecycle(path, task_id)
    pending = state["pending_authorized_spawn"]
    # Both collision selectors matter: an unrelated reservation cannot hide
    # the already running native dependency of the current caller.
    state["identity_collisions"] = [{"pending_handoff_id": pending["handoff_id"],
                                     "agent_id_hash": lifecycle._identity_hash(scanner["agent_id"])}]
    lifecycle._write_capture(path, state)
    assert "scope=direct-dependency" in wait(root, parent)
    assert "scope=direct-dependency" in wait(root, sibling)


def test_resident_chunks_reassemble_exact_unicode_delivery(monkeypatch):
    monkeypatch.setattr(guidance, "resident", lambda runner: "字😀e\u0301\n" * 31 + runner)
    chunks = []
    offset, digest = 0, None
    while offset is not None:
        row = guidance.resident_chunk("runner", offset=offset, limit=7, expected_sha256=digest)
        digest = row["controller_guidance_sha256"]
        assert row["complete_acknowledgement"] is False
        chunks.append(row["content"])
        offset = row["next_offset"]
    delivery = "".join(chunks)
    assert delivery == guidance.delivered_resident("runner")
    assert hashlib.sha256(delivery.encode()).hexdigest() == row["delivery_sha256"]
    assert len(delivery.encode()) == row["delivery_utf8_bytes"]
    assert row["controller_guidance_utf8_bytes"] == len(guidance.resident("runner").encode())
    assert "THALIRIS CONTROLLER GUIDANCE END" in delivery
    with pytest.raises(core.ThalirisError, match="digest differs"):
        guidance.resident_chunk("changed-runner", offset=7, limit=7, expected_sha256=digest)
    with pytest.raises(ValueError, match="continuation requires"):
        guidance.resident_chunk("runner", offset=7, limit=7)


def test_chunk_cli_preserves_full_default_and_rejects_invalid_options(tmp_path, capsys):
    args = ["--root", str(tmp_path), "controller-instructions"]
    assert cli.main(args + ["--resident"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert "GUIDANCE END" in full["content"]
    assert cli.main(args + ["--resident", "--offset", "0", "--limit", "11"]) == 0
    chunk = json.loads(capsys.readouterr().out)
    assert full["content"][:11] == chunk["content"]
    assert full["controller_guidance_sha256"] == chunk["controller_guidance_sha256"]
    assert cli.main(args + ["--section", "routing", "--offset", "0", "--limit", "11"]) != 0
    command = "thaliris controller-instructions --resident --offset 0 --limit 6000"
    assert lifecycle._exact_standalone_controller_instructions_request({"tool_name": "Bash", "tool_input": {"command": command}})
    assert not lifecycle._exact_standalone_controller_instructions_request({"tool_name": "Bash", "tool_input": {"command": command + " --surprise x"}})
