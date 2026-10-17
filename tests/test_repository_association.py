from __future__ import annotations

import json
import subprocess

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, lifecycle, repository_association, task_authority
from tests.test_evidence_continuity_adapter import (
    evidence_task, _event, _identity, _register_requirement, _selected_message,
)


def test_parent_workspace_routes_spawn_start_wait_and_readonly_to_exact_task(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    sibling = root.parent / (root.name + "-second-managed-repo")
    subprocess.run(["git", "init", "-q", str(sibling)], check=True)
    codex_adapter.init(sibling)
    sibling_before = (sibling / ".codex/thaliris.json").read_bytes()
    request = _event(cwd=str(root.parent), tool_name="spawn_agent", tool_input={
        "agent_type": "thaliris-investigator", "fork_turns": "none", "message": _selected_message(),
    })
    raw = lifecycle.handle_hook(root.parent, "PreToolUse", request)
    assert "updatedInput" in raw, raw
    routed = json.loads(raw)["hookSpecificOutput"]["updatedInput"]
    assert routed["model"] == "gpt-6-luna" and routed["reasoning_effort"] == "max"
    child = {**_identity("investigator", "parent-workspace-child"), "cwd": str(root.parent)}
    lifecycle.handle_hook(root.parent, "SubagentStart", child)
    lifecycle.handle_hook(root.parent, "PostToolUse", {**request, "tool_response": {"task_name": "/root/parent-workspace-child"}})
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)
    assert ledger["sequence"] > 0 and len(ledger["children"]) == 1
    record = ledger["children"][0]
    assert record["managed"] and record["handoff_bound"]
    assert core.task_get(root, record["handoff_id"])["object"]["requirement_refs"] == ["R1"]
    denied = lifecycle.handle_hook(root.parent, "PreToolUse", {**child, "tool_name": "Bash",
        "tool_input": {"command": f'thaliris --root "{root}" task-close --base-revision 3'}})
    assert "deny" in denied, denied
    lifecycle.handle_hook(root.parent, "PostToolUse", _event(cwd=str(root.parent), tool_name="list_agents",
        tool_response={"agents": [{"agent_name": "/root/parent-workspace-child", "agent_status": {"completed": "local result"}}]}))
    saved = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id), task_id)["children"][0]
    assert lifecycle._native_execution_terminal(saved)
    assert (sibling / ".codex/thaliris.json").read_bytes() == sibling_before
    assert not (root.parent / ".codex/thaliris.json").exists()


def test_ambiguous_session_refuses_parent_but_exact_repository_and_child_remain_selected(evidence_task):
    root, task_id = evidence_task
    other = root.parent / (root.name + "-other")
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    codex_adapter.init(other)
    other_task = core.task_start(other, "independent", None, None)["task_id"]
    lifecycle._write_session_association(other, other_task, lifecycle._identity_hash("evidence-controller-session"))
    event = _event(cwd=str(root.parent), tool_name="spawn_agent", tool_input={"agent_type": "thaliris-investigator", "fork_turns": "none"})
    assert "REPOSITORY_ASSOCIATION_UNKNOWN" in lifecycle.handle_hook(root.parent, "PreToolUse", event)
    assert repository_association.resolve(event, root) == root
    assert repository_association.resolve(event, other) == other
    assert lifecycle._claim_agent_association(root, task_id, lifecycle._identity_hash("exact-child"))
    assert repository_association.resolve({**event, "agent_id": "exact-child"}, root.parent) == root


def test_stale_navigation_never_adopts_another_repository(evidence_task):
    root, _ = evidence_task
    path = lifecycle._association_path(root, lifecycle._identity_hash("evidence-controller-session"))
    path.unlink()
    raw = lifecycle.handle_hook(root.parent, "PreToolUse", _event(cwd=str(root.parent), tool_name="spawn_agent",
        tool_input={"agent_type": "thaliris-investigator", "fork_turns": "none"}))
    assert "REPOSITORY_ASSOCIATION_UNKNOWN" in raw


def test_unmanaged_without_navigation_keeps_generic_passthrough(tmp_path):
    event = {"session_id": "unmanaged-session", "cwd": str(tmp_path), "tool_name": "spawn_agent",
             "tool_input": {"fork_turns": "none", "message": "ordinary native work"}}
    assert lifecycle.handle_hook(tmp_path, "PreToolUse", event) == ""


def test_trampoline_no_longer_exits_before_actor_navigation():
    script = lifecycle.host_hook_script_bytes().decode("ascii")
    assert "thaliris_find_activation_marker" not in script
    assert "THALIRIS_PREFLIGHT" in script and "audit-hook" in script
