"""Session continuity after native turn reuse and Host restart.

A reused native child, a stale selection or an identity collision must stay a
local conflict: it is named, it can be disposed by the owning Controller, and
the disposal never grants the reused or disposed actor any authority.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, task_authority
from thaliris_codex import lifecycle as lifecycle_module
from tests.test_single_handoff import (  # noqa: F401  (autouse fixture import)
    _owned_task_start, handle_hook, hook_payload, hypothetical_controller_contract, lifecycle, reconcile, repo, spawn_start,
)
from tests.test_evidence_continuity_adapter import (  # noqa: F401  (fixture import)
    _event, _opaque_request, _preselect, _protected_evidence_bytes, _register_requirement, _spawn, evidence_task,
)


def _spawn_request(message: str = "next handoff") -> dict[str, object]:
    return hook_payload(tool_name="spawn_agent", tool_input={"fork_turns": "none", "agent_type": "worker", "message": message})


def _reason(raw: str) -> str:
    return json.loads(raw)["hookSpecificOutput"].get("permissionDecisionReason", "") if raw else ""


def _allowed(raw: str) -> bool:
    return not raw or json.loads(raw)["hookSpecificOutput"].get("permissionDecision") != "deny"


def _dispose_from_denial(root, denial: str, reason: str = "Controller abandons the reused child") -> dict[str, object]:
    """Run exactly the local disposal the refusal named."""
    match = re.search(r"task-dispose-dependency (--handoff-id|--conflict-id) (\S+) --base-revision (\d+)"
                      r" --expected-lifecycle-sha256 ([0-9a-f]{64})", denial)
    assert match, denial
    selector, value, revision, digest = match.groups()
    keyword = {"--handoff-id": {"handoff_id": value}, "--conflict-id": {"handoff_id": None, "conflict_id": value}}[selector]
    return lifecycle_module.task_dispose_dependency(root, base_revision=int(revision), expected_lifecycle=digest,
                                                    reason=reason, **keyword)


def _child(agent_id: str = "child", **values: object) -> dict[str, object]:
    return hook_payload(agent_id=agent_id, agent_type="worker", **values)


def test_followup_to_managed_child_is_refused_before_it_starts_a_new_turn(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "followup reuses a native child", None, None)
    spawn_start(root, "child")
    before = lifecycle(root)
    denied = handle_hook(root, "PreToolUse", hook_payload(tool_name="followup_task",
        tool_input={"target": "child", "message": "more work"}))
    assert "THALIRIS_FOLLOWUP_NEW_TURN" in _reason(denied)
    assert "send_message" in _reason(denied) and 'fork_turns="none"' in _reason(denied)
    # The same-turn supplement path to a live child is kept.
    assert handle_hook(root, "PreToolUse", hook_payload(tool_name="send_message",
        tool_input={"target": "child", "message": "selected supplemental fact"})) == ""
    # An unknown native target is ordinary coordination, not a managed child.
    assert handle_hook(root, "PreToolUse", hook_payload(tool_name="followup_task",
        tool_input={"target": "ordinary-native", "message": "ordinary"})) == ""
    after = lifecycle(root)
    assert after["children"] == before["children"] and after["pending_authorized_spawn"] is None


def test_new_turn_conflict_is_local_and_disposal_restores_the_next_dispatch(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "reused child conflict stays local", None, None)
    spawn_start(root, "child")
    spawn_start(root, "sibling")
    handoff = lifecycle(root)["children"][0]["handoff_id"]

    # A native followup (for example from an older Controller) runs a new turn.
    new_turn = {"turn_id": "child-new-turn"}
    assert _allowed(handle_hook(root, "PreToolUse", _child(tool_name="Bash", tool_input={"command": "Get-Content a.py"}, **new_turn)))
    child = lifecycle(root)["children"][0]
    assert child["native_status_conflict"] is True and child["native_turn_identity_unknown"] is True
    # The new turn never inherits the old handoff's grants.
    assert not _allowed(handle_hook(root, "PreToolUse", _child(tool_name="Bash", tool_input={"command": "Set-Content a.py x"}, **new_turn)))
    assert not _allowed(handle_hook(root, "PreToolUse", _child(tool_name="Bash",
        tool_input={"command": "thaliris task-observe --role implementer --observation-json {}"}, **new_turn)))
    # The unrelated bound sibling keeps its own grants.
    assert _allowed(handle_hook(root, "PreToolUse", _child("sibling", tool_name="Bash", tool_input={"command": "Set-Content b.py y"})))

    denied = _reason(handle_hook(root, "PreToolUse", _spawn_request()))
    assert denied.startswith("THALIRIS_NATIVE_IDENTITY_COLLISION")
    assert f"child handoff {handoff}" in denied and "native turn identity UNKNOWN" in denied
    assert lifecycle(root)["pending_authorized_spawn"] is None
    assert not lifecycle_module.native_execution_closed(root)

    result = _dispose_from_denial(root, denied)
    assert result["management_disposition"] == "ABANDONED_DEPENDENCY" and result["native_execution"] == "UNKNOWN"
    disposed = lifecycle(root)["children"][0]
    # History stays: the conflict and UNKNOWN turn are not erased or "terminated".
    assert disposed["native_status_conflict"] is True and disposed["native_turn_identity_unknown"] is True
    assert disposed["native_terminal_status"] is None

    assert _allowed(handle_hook(root, "PreToolUse", _spawn_request("post-disposal handoff")))
    assert lifecycle(root)["pending_authorized_spawn"]["payload_hash"] == hashlib.sha256(b"post-disposal handoff").hexdigest()
    # Disposal grants nothing back to either turn of the disposed actor.
    for turn in ({}, new_turn):
        for command in ("Set-Content a.py x", "thaliris task-observe --role implementer --observation-json {}"):
            assert "THALIRIS_ABANDONED_ROLE_SESSION" in _reason(handle_hook(root, "PreToolUse",
                _child(tool_name="Bash", tool_input={"command": command}, **turn)))
    assert _allowed(handle_hook(root, "PreToolUse", _child("sibling", tool_name="Bash", tool_input={"command": "Set-Content b.py z"})))


def test_disposed_conflict_lets_close_proceed_but_undisposed_conflict_still_blocks(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "close after disposal", None, None)
    spawn_start(root, "child")
    reconcile(root, "child", {"completed": "result"})
    reconcile(root, "child", "running")
    assert lifecycle(root)["children"][0]["native_status_conflict"] is True
    assert not lifecycle_module.native_execution_closed(root)
    denied = _reason(handle_hook(root, "PreToolUse", _spawn_request()))
    _dispose_from_denial(root, denied, "native status conflict accepted as abandoned")
    assert lifecycle_module.native_execution_closed(root)


def test_collision_without_handoff_is_disposed_by_exact_conflict_id_and_kept_as_history(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "duplicate start collision", None, None)
    spawn_start(root, "child")
    # A second Start for the same actor and turn, with no reservation pending.
    assert handle_hook(root, "SubagentStart", _child()) == ""
    state = lifecycle(root)
    assert state["identity_collisions"][-1]["pending_handoff_id"] is None
    reconcile(root, "child", {"completed": "result"})
    assert not lifecycle_module.native_execution_closed(root)

    denied = _reason(handle_hook(root, "PreToolUse", _spawn_request()))
    assert "--conflict-id collision-" in denied
    conflict_id = re.search(r"--conflict-id (collision-[0-9a-f]{24})", denied).group(1)
    task_id = core.selected_task(root) or core.task_show(root)["state"]["task_id"]
    path = lifecycle_module._lifecycle_path(root, task_id)
    revision = core.task_show(root)["state"]["revision"]
    with pytest.raises(ValueError, match="CONFLICT_NOT_FOUND"):
        lifecycle_module.task_dispose_dependency(root, None, revision, task_authority.digest(path), "wrong id",
                                                 conflict_id="collision-" + "0" * 24)
    with pytest.raises(ValueError, match="exactly one"):
        lifecycle_module.task_dispose_dependency(root, state["children"][0]["handoff_id"], revision,
                                                 task_authority.digest(path), "both", conflict_id=conflict_id)
    result = _dispose_from_denial(root, denied, "duplicate Start is not a new dispatch")
    assert result["disposed_collision_ids"] == [conflict_id]
    after = lifecycle(root)
    collision = after["identity_collisions"][-1]
    assert collision["management_disposition"] == "ABANDONED_DEPENDENCY" and collision["agent_id_hash"]
    assert [item["kind"] for item in after["dependency_dispositions"]] == ["collision"]
    # The live actor of a different, undisposed handoff is not silently fenced.
    assert after["dependency_dispositions"][0]["agent_fenced"] is False
    assert after["children"][0].get("management_disposition") is None
    assert lifecycle_module.native_execution_closed(root)
    assert _allowed(handle_hook(root, "PreToolUse", _spawn_request("after collision disposal")))
    # A disposed record cannot be disposed again by its id.
    with pytest.raises(ValueError, match="CONFLICT_NOT_FOUND"):
        lifecycle_module.task_dispose_dependency(root, None, core.task_show(root)["state"]["revision"],
            task_authority.digest(path), "again", conflict_id=conflict_id)


def test_handoff_disposal_covers_the_collision_observed_for_its_reservation(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "collision during reservation", None, None)
    spawn_start(root, "reused-id")
    reconcile(root, "reused-id", {"completed": "first result"})
    second = _spawn_request("second handoff")
    assert handle_hook(root, "PreToolUse", second) == ""
    handle_hook(root, "PostToolUse", {**second, "tool_response": {"agent_id": "reused-id", "nickname": None}})
    handle_hook(root, "SubagentStart", _child("reused-id"))
    state = lifecycle(root)
    pending = state["pending_authorized_spawn"]["handoff_id"]
    assert state["identity_collisions"][-1]["pending_handoff_id"] == pending
    task_id = core.task_show(root)["state"]["task_id"]
    path = lifecycle_module._lifecycle_path(root, task_id)
    result = lifecycle_module.task_dispose_dependency(root, pending, core.task_show(root)["state"]["revision"],
        task_authority.digest(path), "second dispatch collided")
    assert len(result["disposed_collision_ids"]) == 1
    after = lifecycle(root)
    assert after["pending_authorized_spawn"] is None
    assert {item["kind"] for item in after["dependency_dispositions"]} == {"pending", "collision"}
    assert lifecycle_module.native_execution_closed(root)
    assert _allowed(handle_hook(root, "PreToolUse", _spawn_request("third handoff")))


def test_owner_cancels_and_replaces_an_unconsumed_selection(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    _preselect(root, "investigator")
    owner = lifecycle_module._identity_hash("evidence-controller-session")
    refused = _reason(lifecycle_module.handle_hook(root, "PreToolUse", _opaque_request("reviewer")))
    assert refused.startswith("THALIRIS_EVIDENCE_DISPATCH_CONFLICT") and "cancel_next_dispatch" in refused
    with pytest.raises(ValueError, match="already pending"):
        _preselect(root, "reviewer")
    source = root / "cancel.json"
    replacement = {"role": "reviewer", "expected_agent_type": "thaliris-reviewer", "candidate": "C5", "requirement_refs": ["R1"]}
    source.write_text(json.dumps({"cancel_next_dispatch": {"reason": "route to Reviewer instead"},
                                  "next_dispatch": replacement}), encoding="utf-8")
    before = _protected_evidence_bytes(root, task_id)
    for wrong in (None, lifecycle_module._identity_hash("other-session")):
        with pytest.raises(ValueError, match="owning Controller"):
            codex_adapter.task_evidence_register(root, "controller", core.task_show(root)["state"]["revision"], str(source), wrong)
    assert _protected_evidence_bytes(root, task_id) == before
    for invalid in ({"cancel_next_dispatch": {}}, {"cancel_next_dispatch": {"reason": " "}},
                    {"cancel_next_dispatch": {"reason": "x", "role": "reviewer"}}):
        bad = root / "bad-cancel.json"
        bad.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError, match="reason"):
            codex_adapter.task_evidence_register(root, "controller", core.task_show(root)["state"]["revision"], str(bad), owner)
    result = codex_adapter.task_evidence_register(root, "controller", core.task_show(root)["state"]["revision"], str(source), owner)
    assert result["next_dispatch"]["role"] == "reviewer"
    ledger = lifecycle_module._load_lifecycle(lifecycle_module._lifecycle_path(root, task_id), task_id)
    assert ledger["next_evidence_dispatch"]["role"] == "reviewer"
    history = ledger["evidence_dispatch_cancellations"]
    assert history[-1]["selection"]["role"] == "investigator" and history[-1]["reason"] == "route to Reviewer instead"
    # The replacement is consumed exactly once by its matching spawn.
    assert _allowed(lifecycle_module.handle_hook(root, "PreToolUse", _opaque_request("reviewer")))
    ledger = lifecycle_module._load_lifecycle(lifecycle_module._lifecycle_path(root, task_id), task_id)
    assert "next_evidence_dispatch" not in ledger
    handoff = ledger["pending_authorized_spawn"]["handoff_id"]
    registered = next(item for item in core._load_state(root)["evidence_continuity"]["handoffs"] if item["id"] == handoff)
    assert registered["candidate"] == "C5"


def test_cancel_only_withdraws_selection_and_allows_registration_again(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    owner = lifecycle_module._identity_hash("evidence-controller-session")
    source = root / "cancel-only.json"
    source.write_text(json.dumps({"cancel_next_dispatch": {"reason": "no selection"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="no unconsumed"):
        codex_adapter.task_evidence_register(root, "controller", core.task_show(root)["state"]["revision"], str(source), owner)
    _preselect(root, "investigator")
    revision = core.task_show(root)["state"]["revision"]
    result = codex_adapter.task_evidence_register(root, "controller", revision, str(source), owner)
    assert result["cancelled_next_dispatch"]["role"] == "investigator"
    assert core.task_show(root)["state"]["revision"] == revision + 1
    ledger = lifecycle_module._load_lifecycle(lifecycle_module._lifecycle_path(root, task_id), task_id)
    assert "next_evidence_dispatch" not in ledger and ledger["pending_authorized_spawn"] is None
    # Without a selection, any permitted Controller dispatch proceeds again.
    _preselect(root, "reviewer")
    assert _allowed(lifecycle_module.handle_hook(root, "PreToolUse", _opaque_request("reviewer")))


def test_children_cannot_cancel_a_selection(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    child, _handoff = _spawn(root, "implementer", "selection-canceller")
    _preselect(root, "investigator")
    command = f'thaliris --root "{root}" task-evidence-register --role controller --base-revision 9 --input cancel.json'
    assert not _allowed(lifecycle_module.handle_hook(root, "PreToolUse", {**child, "tool_name": "Bash", "tool_input": {"command": command}}))


def test_reused_v2_child_followup_is_refused_and_selection_survives(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    _child_identity, _handoff = _spawn(root, "implementer", "impl-1")
    _preselect(root, "investigator")
    denied = lifecycle_module.handle_hook(root, "PreToolUse", _event(tool_name="followup_task",
        tool_input={"target": "/root/impl-1", "message": "more"}))
    assert "THALIRIS_FOLLOWUP_NEW_TURN" in _reason(denied)
    assert _allowed(lifecycle_module.handle_hook(root, "PreToolUse", _opaque_request("investigator")))


def test_stale_controller_session_hash_names_the_current_source(evidence_task):
    root, task_id = evidence_task
    command = (f'thaliris --root "{root}" --task-id {task_id} task-evidence-register --role controller'
               " --base-revision 9 --input x.json --controller-session-id-hash " + "0" * 64)
    denied = _reason(lifecycle_module.handle_hook(root, "PreToolUse", _event(tool_name="Bash", tool_input={"command": command})))
    assert denied.startswith("THALIRIS_EVIDENCE_DISPATCH_CONFLICT") and "Omit --controller-session-id-hash" in denied
