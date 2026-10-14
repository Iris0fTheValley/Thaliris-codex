"""Default native model selection without task admission or reservation."""
import json
import subprocess

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, lifecycle, roles, task_authority


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "external")
    agents = home / "agents"
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = agents / name
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    codex_adapter.init(root)
    return root, home


def spawn(root, role="implementer", **selection):
    return {
        "session_id": "root-session",
        "turn_id": "root-turn",
        "cwd": str(root),
        "tool_name": "spawn_agent",
        "tool_input": {
            "agent_type": f"thaliris-{role}",
            "fork_turns": "none",
            "message": "Selected facts only",
            **selection,
        },
    }


def route(root, request):
    return json.loads(lifecycle.handle_hook(root, "PreToolUse", request))["hookSpecificOutput"]


def assert_no_reservation(root):
    assert not (root / ".context" / "audit" / "lifecycle").exists()


def assert_no_task_authority(root):
    assert not task_authority.path(root).exists()


@pytest.mark.parametrize("role", list(roles.ROLE_MODEL_ROUTING_DEFAULTS))
@pytest.mark.parametrize("inactive", [False, True], ids=["no-task", "inactive-task"])
def test_registered_roles_receive_defaults_without_managed_reservation(project, role, inactive):
    root, _home = project
    if inactive:
        started = core.task_start(root, "closed before routing", None, None)
        closed = core.task_close(root, started["revision"], expected_task_id=started["task_id"])
        assert closed["status"] == "DONE"

    request = spawn(root, role)
    original = dict(request["tool_input"])
    output = route(root, request)
    assert output["permissionDecision"] == "allow"
    assert output["updatedInput"]["model"] == roles.ROLE_MODEL_ROUTING_DEFAULTS[role][0]
    assert output["updatedInput"]["reasoning_effort"] == roles.ROLE_MODEL_ROUTING_DEFAULTS[role][1]
    assert request["tool_input"] == original
    assert_no_reservation(root)
    if inactive:
        assert core.task_show(root)["state"]["status"] == "DONE"
    else:
        assert_no_task_authority(root)


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        ({"model": None, "reasoning_effort": None}, {"model": "gpt-6-luna", "reasoning_effort": "max"}),
        ({"reasoning_effort": "low"}, {"model": "gpt-6-luna", "reasoning_effort": "low"}),
        ({"model": "gpt-5.6-luna"}, None),
        ({"model": "gpt-5.6-luna", "reasoning_effort": "medium"}, None),
    ],
)
def test_sparse_and_explicit_selection_preserve_native_omission_semantics(project, selection, expected):
    root, _home = project
    request = spawn(root, "implementer", **selection)
    original = dict(request["tool_input"])
    result = lifecycle.handle_hook(root, "PreToolUse", request)
    if expected is None:
        assert result == ""
        assert request["tool_input"] == original
    else:
        output = json.loads(result)["hookSpecificOutput"]["updatedInput"]
        assert {key: output[key] for key in expected} == expected
        assert request["tool_input"] == original
    assert_no_reservation(root)
    assert_no_task_authority(root)


def test_invalid_selection_is_refused_before_pre_admission_transform(project):
    root, _home = project
    request = spawn(root, "implementer", model="")
    before = dict(request["tool_input"])
    result = lifecycle.handle_hook(root, "PreToolUse", request)
    assert "ROLE_MODEL_ARGUMENT_INVALID" in result
    assert "updatedInput" not in result
    assert request["tool_input"] == before
    assert_no_reservation(root)


@pytest.mark.parametrize(
    "agent_type",
    ["explorer", "worker", "thaliris-focused-implementer-xhigh"],
)
def test_generic_and_static_profiles_keep_native_selection(project, agent_type):
    root, _home = project
    request = spawn(root, "implementer")
    request["tool_input"]["agent_type"] = agent_type
    original = dict(request["tool_input"])
    assert lifecycle.handle_hook(root, "PreToolUse", request) == ""
    assert request["tool_input"] == original
    assert_no_reservation(root)
    assert_no_task_authority(root)


def test_child_role_routes_only_after_existing_target_delegation_check(project):
    root, _home = project
    request = spawn(root, "investigator")
    request.update({"agent_id": "implementer-child", "agent_type": "thaliris-implementer"})
    result = json.loads(lifecycle.handle_hook(root, "PreToolUse", request))["hookSpecificOutput"]
    assert result["updatedInput"]["model"] == "gpt-6-luna"
    assert result["updatedInput"]["reasoning_effort"] == "max"
    assert_no_reservation(root)

    denied = spawn(root, "reviewer")
    denied.update({"agent_id": "implementer-child", "agent_type": "thaliris-implementer"})
    result = lifecycle.handle_hook(root, "PreToolUse", denied)
    assert "ROLE_SESSION_DELEGATION" in result
    assert "updatedInput" not in result
    assert_no_reservation(root)


@pytest.mark.parametrize(
    ("restriction", "reason"),
    [("readonly", "READONLY_ACTOR"), ("fenced", "FENCED_ACTOR")],
)
def test_restricted_pre_admission_actor_is_denied_before_default_selection(project, restriction, reason):
    root, _home = project
    request = spawn(root)
    request[restriction] = True
    result = lifecycle.handle_hook(root, "PreToolUse", request)
    assert reason in result
    assert "updatedInput" not in result
    assert_no_reservation(root)
    assert_no_task_authority(root)


def test_public_hook_routes_in_gitless_cwd_without_task_state(project, tmp_path, monkeypatch):
    _root, _home = project
    projectless = tmp_path / "projectless"
    projectless.mkdir()
    monkeypatch.chdir(projectless)
    request = spawn(projectless)
    result = lifecycle.handle_hook(projectless, "PreToolUse", request)
    output = json.loads(result)["hookSpecificOutput"]
    assert output["updatedInput"]["model"] == "gpt-6-luna"
    assert output["updatedInput"]["reasoning_effort"] == "max"
    assert not (projectless / ".git").exists()
    assert not core._state_path(projectless).exists()
    assert not (projectless / ".context" / "audit" / "lifecycle").exists()
    assert_no_task_authority(projectless)
