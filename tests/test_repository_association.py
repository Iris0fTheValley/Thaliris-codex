from __future__ import annotations

import json
import subprocess

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, lifecycle, repository_association, task_authority
from tests.test_evidence_continuity_adapter import (
    evidence_task, _event, _identity, _register_requirement, _selected_message,
)


@pytest.mark.parametrize("evidence_task", ["git", "nongit"], indirect=True)
def test_parent_workspace_routes_spawn_start_wait_and_readonly_to_exact_task(evidence_task):
    root, task_id = evidence_task
    _register_requirement(root)
    sibling = root.parent / (root.name + "-second-managed-repo")
    if (root / ".git").exists():
        subprocess.run(["git", "init", "-q", str(sibling)], check=True)
    else:
        sibling.mkdir()
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
    lifecycle.handle_hook(root.parent, "PostToolUse", {**request,
        "tool_response": {"agent_id": child["agent_id"], "nickname": None}})
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
    assert not (root.parent / ".git").exists()


@pytest.mark.parametrize("evidence_task", ["git", "nongit"], indirect=True)
def test_ambiguous_session_refuses_parent_but_exact_repository_and_child_remain_selected(evidence_task):
    root, task_id = evidence_task
    other = root.parent / (root.name + "-other")
    if (root / ".git").exists():
        subprocess.run(["git", "init", "-q", str(other)], check=True)
    else:
        other.mkdir()
    codex_adapter.init(other)
    other_task = core.task_start(other, "independent", None, None)["task_id"]
    lifecycle._write_session_association(other, other_task, lifecycle._identity_hash("evidence-controller-session"))
    event = _event(cwd=str(root.parent), tool_name="spawn_agent", tool_input={"agent_type": "thaliris-investigator", "fork_turns": "none"})
    assert "REPOSITORY_ASSOCIATION_UNKNOWN" in lifecycle.handle_hook(root.parent, "PreToolUse", event)
    assert repository_association.resolve(event, root) == root
    assert repository_association.resolve(event, other) == other
    assert lifecycle._claim_agent_association(root, task_id, lifecycle._identity_hash("exact-child"))
    assert repository_association.resolve({**event, "agent_id": "exact-child"}, root.parent) == root


@pytest.mark.parametrize("evidence_task", ["git", "nongit"], indirect=True)
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


def _second_session_repository(root, *, nested=False):
    other = root / "nested managed repo" if nested else root.parent / (root.name + "-other")
    other.mkdir()
    if (root / ".git").exists():
        subprocess.run(["git", "init", "-q", str(other)], check=True)
    codex_adapter.init(other)
    task = core.task_start(other, "independent", None, None)["task_id"]
    owner = lifecycle._identity_hash("evidence-controller-session")
    task_authority.establish(other, core._load_state(other), task_authority.read(root)["contract"], owner)
    lifecycle.record_task_start_owner(other, task, owner)
    return other, task


@pytest.mark.parametrize("style", ["separate", "equals"])
def test_explicit_root_selects_associated_nested_repo_at_both_hook_boundaries(evidence_task, style):
    root, _ = evidence_task
    nested, task = _second_session_repository(root, nested=True)
    argument = f'--root "{nested}"' if style == "separate" else f'--root="{nested}"'
    request = _event(cwd=str(root), tool_name="Bash", tool_input={
        "command": f'thaliris {argument} --task-id {task} task-evidence-register --role controller --base-revision 1 --input existing.json'})
    assert lifecycle._associated_repository_root(root, request) == nested
    # The owner/session bound to the nested task remains usable; routing to
    # the parent would reject this operation as CONTROLLER_ACTOR_UNKNOWN.
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", request)
    assert "deny" not in lifecycle._pre_tool_output(request, root)
    assert core.selected_task(nested) == task


def test_explicit_root_never_overrides_exact_child_or_adds_unassociated_root(evidence_task):
    root, task = evidence_task
    other, _ = _second_session_repository(root)
    assert lifecycle._claim_agent_association(root, task, lifecycle._identity_hash("exact-child"))
    request = _event(cwd=str(root), tool_name="Bash", tool_input={"command": f'thaliris --root "{other}" task-status'})
    child_request = {**request, "agent_id": "exact-child"}
    with pytest.raises(ValueError, match="CONFLICT"):
        lifecycle._associated_repository_root(root, child_request)
    assert "deny" in lifecycle.handle_hook(root, "PreToolUse", child_request)
    unknown = root.parent / "unassociated"
    unknown.mkdir()
    request["tool_input"]["command"] = f'thaliris --root "{unknown}" task-status'
    with pytest.raises(ValueError, match="CONFLICT"):
        lifecycle._associated_repository_root(root, request)


def test_stale_other_record_still_refuses_explicit_root(evidence_task):
    root, _ = evidence_task
    other, _ = _second_session_repository(root)
    lifecycle._association_path(other, lifecycle._identity_hash("evidence-controller-session")).unlink()
    request = _event(cwd=str(root), tool_name="Bash", tool_input={"command": f'thaliris --root "{root}" task-status'})
    with pytest.raises((ValueError, OSError)):
        lifecycle._associated_repository_root(root, request)


@pytest.mark.parametrize("argument", [
    '--root "$env:WORKSPACE"', "--root '$HOME'", '--root "%WORKSPACE%"',
    '--root "!WORKSPACE!"', '--root "~"', '--root "one" --root "two"',
    '--root=', '--root --pretty', '--root "one"\'two\'',
])
def test_root_disambiguation_rejects_nonliteral_missing_and_duplicate_values(argument):
    request = {"tool_input": {"command": f"thaliris {argument} task-status"}}
    with pytest.raises(ValueError, match="REPOSITORY_ASSOCIATION_INVALID_CLI_ROOT"):
        lifecycle._direct_context_root(request)


@pytest.mark.parametrize("command", [
    'echo thaliris --root elsewhere task-status',
    'thaliris task-get "--root elsewhere"',
    'thaliris --root elsewhere task-status; echo extra',
    'thaliris --root elsewhere task-status $(echo extra)',
])
def test_root_disambiguation_only_reads_standalone_global_cli_option(command):
    assert lifecycle._direct_context_root({"tool_input": {"command": command}}) is None


def test_relative_root_uses_shell_workdir_instead_of_git_toplevel(evidence_task):
    root, _ = evidence_task
    nested, _ = _second_session_repository(root, nested=True)
    workdir = nested / "subdirectory"
    workdir.mkdir()
    request = _event(cwd=str(root), tool_name="Bash", tool_input={
        "command": 'thaliris --root ".." task-status', "workdir": str(workdir)})
    assert lifecycle._associated_repository_root(root, request) == nested


def test_relative_workdir_root_is_idempotent_across_both_hook_routing_passes(evidence_task):
    root, _ = evidence_task
    nested, task = _second_session_repository(root, nested=True)
    request = _event(cwd=str(root), tool_name="Bash", tool_input={
        "command": "thaliris --root . task-status", "workdir": nested.name})

    assert lifecycle._associated_repository_root(root, request) == nested
    assert lifecycle._associated_repository_root(nested, request) == nested
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", request)
    assert "deny" not in lifecycle._pre_tool_output(request, nested)
    assert core.selected_task(nested) == task


def test_unassociated_root_does_not_route_by_cli_task_id(evidence_task):
    root, task = evidence_task
    request = _event(cwd=str(root), tool_name="Bash", tool_input={
        "command": f'thaliris --root "{root.parent}" --task-id {task} task-status'})
    with pytest.raises(ValueError, match="CONFLICT"):
        lifecycle._associated_repository_root(root, request)


def test_equals_root_cannot_turn_path_bytes_into_a_task_option():
    request = {"tool_input": {"command": 'thaliris --root="folder --task-id forged" task-status'}}
    assert lifecycle._direct_context_option(request, {"--task-id"}, digest_only=False) is None
    assert str(lifecycle._direct_context_root(request)) == "folder --task-id forged"


@pytest.mark.parametrize("style", ["separate", "equals"])
def test_public_controller_retrieval_keeps_exact_root_syntax(style):
    argument = '--root "some directory"' if style == "separate" else '--root="some directory"'
    request = {"tool_name": "Bash", "tool_input": {"command": f'thaliris {argument} controller-instructions --resident'}}
    assert lifecycle._exact_standalone_controller_instructions_request(request)


def test_explicit_root_cannot_disambiguate_conflicting_child_associations(evidence_task):
    root, task = evidence_task
    other, other_task = _second_session_repository(root)
    actor = lifecycle._identity_hash("multiply-associated-child")
    assert lifecycle._claim_agent_association(root, task, actor)
    assert lifecycle._claim_agent_association(other, other_task, actor)
    request = _event(agent_id="multiply-associated-child", cwd=str(root))
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        repository_association.resolve(request, root, requested_root=root)


def test_explicit_current_directory_keeps_unassociated_read_navigation(tmp_path):
    request = {"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {
        "command": f'thaliris --root "{tmp_path}" task-status'}}
    assert lifecycle._associated_repository_root(tmp_path, request) == tmp_path
    assert lifecycle.handle_hook(tmp_path, "PreToolUse", request) == ""
