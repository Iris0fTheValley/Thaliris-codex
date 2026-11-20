"""MCP delegation guard for Thaliris children and demotion of agent-started (foreign) sessions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from thaliris_codex import cli, codex_bootstrap, foreign_session, roles
from thaliris_codex.lifecycle import handle_hook
import thaliris_codex.lifecycle as lifecycle_module
from tests.test_single_handoff import _owned_task_start, hook_payload, repo, spawn_start

_REAL_ASSURANCE = lifecycle_module._controller_actor_assurance
SPAWN_TOOL = "mcp__claude__claude_delegate"
READ_TOOLS = ("mcp__claude__bridge_health", "mcp__codex__codex_output", "mcp__files__read_file", "mcp__x__list_things")
MARKERS = (("AGENT_BRIDGE_DEPTH", "1"), ("AGENT_BRIDGE_DEPTH", "3"), ("THALIRIS_FOREIGN_CHILD", "1"))


@pytest.fixture(autouse=True)
def hypothetical_controller_contract(monkeypatch, tmp_path):
    """Same synthetic Controller seam as the lifecycle tests; a foreign marker must still demote."""
    original = lifecycle_module._controller_actor_assurance
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "isolated-host"))
    monkeypatch.delenv("AGENT_BRIDGE_DEPTH", raising=False)
    monkeypatch.delenv("THALIRIS_FOREIGN_CHILD", raising=False)
    monkeypatch.setattr(lifecycle_module, "_controller_actor_assurance", lambda payload:
                        "CONTROLLER" if original(payload) == "UNKNOWN" else original(payload))


def _decision(output: str) -> tuple[str, str]:
    if not output:
        return "", ""
    specific = json.loads(output)["hookSpecificOutput"]
    return specific.get("permissionDecision", ""), specific.get("permissionDecisionReason", "")


def _child_call(root: Path, agent_id: str, agent_type: str, tool: str) -> tuple[str, str]:
    return _decision(handle_hook(root, "PreToolUse", hook_payload(
        agent_id=agent_id, agent_type=agent_type, tool_name=tool, tool_input={"prompt": "do it"})))


def _bash(root: Path, command: str, **extra: object) -> tuple[str, str]:
    return _decision(handle_hook(root, "PreToolUse", {
        "session_id": "foreign-session", "turn_id": "foreign-turn", "tool_name": "Bash",
        "tool_input": {"command": command}, **extra}))


def _bound_roles() -> list[tuple[str, str, bool]]:
    result = []
    for role in roles.role_choices():
        binding = roles.get_codex_binding(role)
        if binding is not None and binding.native_profile is not None:
            result.append((role, binding.native_profile, binding.repo_write_allowed))
    return result


def test_classification_mirrors_the_sibling_adapter() -> None:
    for name in ("mcp__claude__claude_delegate", "mcp__codex__codex_publish", "mcp__s__run_job", "mcp__s__bashTool",
                 "mcp__s__shell_exec", "mcp__s__schedule_it", "mcp__s__spawnAgent"):
        assert foreign_session.mcp_class(name) == "spawn", name
    for name in ("mcp__codex__codex_task", "mcp__s__write_file", "mcp__s__edit", "mcp__s__create_x", "mcp__s__deleteIt",
                 "mcp__s__cancel"):
        assert foreign_session.mcp_class(name) == "mutating", name
    for name in READ_TOOLS + ("mcp__s__search", "mcp__s__fetch_url", "mcp__s__queryDb", "mcp__s__get_status"):
        assert foreign_session.mcp_class(name) == "read", name
    assert foreign_session.mcp_class("mcp__s__frobnicate") == "unknown"
    # Spawn words win over read words.
    assert foreign_session.mcp_class("mcp__s__get_and_run") == "spawn"


@pytest.mark.parametrize(("role", "profile", "writes"), _bound_roles())
def test_bound_role_cannot_call_spawn_mcp_tools(tmp_path: Path, role: str, profile: str, writes: bool) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "mcp guard", None, None)
    spawn_start(root, "child-1", profile)
    decision, reason = _child_call(root, "child-1", profile, SPAWN_TOOL)
    assert decision == "deny", role
    assert SPAWN_TOOL in reason and "Thaliris dispatch" in reason
    for tool in READ_TOOLS:
        assert _child_call(root, "child-1", profile, tool) == ("", ""), (role, tool)
    unknown = _child_call(root, "child-1", profile, "mcp__s__frobnicate")
    mutating = _child_call(root, "child-1", profile, "mcp__s__remove_all_tasks")
    if writes:
        assert unknown == ("", "")
        assert mutating == ("", "")
    else:
        assert unknown[0] == "deny" and "mcp__s__frobnicate" in unknown[1]
        assert mutating[0] == "deny"


def test_named_acceptance_cases(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "mcp guard", None, None)
    spawn_start(root, "reviewer-1", "thaliris-reviewer")
    spawn_start(root, "impl-1", "thaliris-implementer")
    assert _child_call(root, "reviewer-1", "thaliris-reviewer", SPAWN_TOOL)[0] == "deny"
    assert _child_call(root, "impl-1", "thaliris-implementer", SPAWN_TOOL)[0] == "deny"
    assert _child_call(root, "reviewer-1", "thaliris-reviewer", "mcp__claude__bridge_health") == ("", "")
    assert _child_call(root, "reviewer-1", "thaliris-reviewer", "mcp__s__frobnicate")[0] == "deny"
    # The Controller (no agent identity) is unaffected, spawn-class tools included.
    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name=SPAWN_TOOL, tool_input={"prompt": "do it"})) == ""


def test_claimed_role_without_a_binding_is_unverified_and_read_only(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "mcp guard", None, None)
    # No spawn, no binding: agent_type alone grants no write standing.
    assert _child_call(root, "ghost-1", "thaliris-implementer", SPAWN_TOOL)[0] == "deny"
    assert _child_call(root, "ghost-1", "thaliris-implementer", "mcp__s__frobnicate")[0] == "deny"
    assert _child_call(root, "ghost-1", "thaliris-implementer", "mcp__claude__bridge_health") == ("", "")


def test_generic_native_subagent_of_an_ordinary_session_is_unaffected(tmp_path: Path) -> None:
    root = repo(tmp_path)
    assert _child_call(root, "gen-1", "explorer", SPAWN_TOOL) == ("", "")


@pytest.mark.parametrize(("name", "value"), MARKERS)
def test_foreign_session_subagents_get_the_read_only_mcp_rule(tmp_path: Path, monkeypatch, name: str, value: str) -> None:
    root = repo(tmp_path)
    monkeypatch.setenv(name, value)
    assert _child_call(root, "gen-1", "explorer", SPAWN_TOOL)[0] == "deny"
    assert _child_call(root, "gen-1", "explorer", "mcp__s__frobnicate")[0] == "deny"
    health = _child_call(root, "gen-1", "explorer", "mcp__claude__bridge_health")
    if name == "THALIRIS_FOREIGN_CHILD":
        assert health[0] == "deny" and "XHOST_FOREIGN_CHILD_READONLY" in health[1]
    else:
        assert health == ("", "")


@pytest.mark.parametrize(("name", "value"), MARKERS)
def test_foreign_session_cannot_run_authority_commands_at_the_hook(tmp_path: Path, monkeypatch, name: str, value: str) -> None:
    root = repo(tmp_path)
    monkeypatch.setenv(name, value)
    for command in (
        "thaliris task-start goal", "thaliris task-associate --session-id x", "thaliris task-recover-authority",
        "thaliris task-mode --mode single-agent", "thaliris task-evidence-register", "thaliris task-judge",
        "thaliris task-observe --role implementer", "thaliris task-verify --check c1", "thaliris task-close",
        "thaliris task-dispose-dependency", "thaliris task-abandon", "thaliris codex-install",
        "thaliris codex-maintenance-plan", "thaliris codex-model-catalog-refresh", "thaliris init",
        # Shell syntax that hides the direct invocation is refused too.
        "env -u AGENT_BRIDGE_DEPTH thaliris task-start goal",
        "cd . && thaliris task-start goal",
    ):
        decision, reason = _bash(root, command)
        expected_reason = "XHOST_FOREIGN_CHILD_READONLY" if name == "THALIRIS_FOREIGN_CHILD" else "THALIRIS_FOREIGN_SESSION"
        assert decision == "deny" and expected_reason in reason, command
    for command in ("thaliris task-status", "thaliris doctor", "thaliris version", "thaliris task-show", "echo hi"):
        decision, reason = _bash(root, command)
        assert "THALIRIS_FOREIGN_SESSION" not in reason, command
    decision, reason = _bash(root, "thaliris codex-bootstrap")
    if name == "THALIRIS_FOREIGN_CHILD":
        assert decision == "deny" and "XHOST_FOREIGN_CHILD_READONLY" in reason
    else:
        assert decision == "" and reason == ""


def test_foreign_session_cannot_spawn_managed_children(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    monkeypatch.setenv("AGENT_BRIDGE_DEPTH", "1")
    for agent_type in ("thaliris-reviewer", "thaliris-implementer"):
        decision, reason = _decision(handle_hook(root, "PreToolUse", hook_payload(
            tool_name="spawn_agent",
            tool_input={"fork_turns": "none", "agent_type": agent_type, "message": "handoff"})))
        assert decision == "deny" and "THALIRIS_FOREIGN_SESSION" in reason


def test_foreign_session_start_gets_a_short_note_and_no_controller_navigation(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    payload = {"session_id": "foreign-session", "source": "startup", "cwd": str(root)}
    normal = json.loads(handle_hook(root, "SessionStart", payload))["hookSpecificOutput"]["additionalContext"]
    assert ".agent-memory/INDEX.md" in normal
    monkeypatch.setenv("AGENT_BRIDGE_DEPTH", "1")
    foreign = json.loads(handle_hook(root, "SessionStart", {**payload, "session_id": "foreign-2"}))["hookSpecificOutput"]["additionalContext"]
    assert "unmanaged foreign session" in foreign and len(foreign) < 600
    assert ".agent-memory" not in foreign and "Controller guidance" not in foreign
    assert not (lifecycle_module._session_dir(root, {"session_id": "foreign-2"}) / "runtime.json").exists()


def test_bound_child_is_judged_by_its_binding_not_the_marker(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "mcp guard", None, None)
    spawn_start(root, "child-1", "thaliris-implementer")
    bound = hook_payload(agent_id="child-1", agent_type="thaliris-implementer", tool_name="Bash", tool_input={"command": "echo"})
    monkeypatch.setenv("AGENT_BRIDGE_DEPTH", "1")
    assert lifecycle_module._foreign_session(root, bound) is None
    unbound = hook_payload(agent_id="ghost", agent_type="thaliris-implementer", tool_name="Bash", tool_input={"command": "echo"})
    assert lifecycle_module._foreign_session(root, unbound) == "AGENT_BRIDGE_DEPTH>0"
    assert lifecycle_module._foreign_session(root, hook_payload(tool_name="Bash")) == "AGENT_BRIDGE_DEPTH>0"


def test_normal_user_session_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    assert lifecycle_module._foreign_session(root, hook_payload(tool_name="Bash")) is None
    for command in ("thaliris task-start goal", "thaliris task-close", "thaliris codex-install"):
        assert "THALIRIS_FOREIGN_SESSION" not in _bash(root, command)[1], command
    # Zero or empty depth and a false marker never demote.
    for name, value in (("AGENT_BRIDGE_DEPTH", "0"), ("AGENT_BRIDGE_DEPTH", ""), ("THALIRIS_FOREIGN_CHILD", "0"),
                        ("THALIRIS_FOREIGN_CHILD", "")):
        monkeypatch.setenv(name, value)
        assert foreign_session.marker() is None, (name, value)
        monkeypatch.delenv(name)
    assert handle_hook(root, "PreToolUse", hook_payload(tool_name=SPAWN_TOOL, tool_input={})) == ""
    assert json.loads(handle_hook(root, "SessionStart", {"session_id": "s", "source": "startup", "cwd": str(root)}))
    assert foreign_session.marker({}) is None


def test_marker_only_lowers_authority(monkeypatch) -> None:
    assert foreign_session.marker({"AGENT_BRIDGE_DEPTH": "2"}) == "AGENT_BRIDGE_DEPTH>0"
    assert foreign_session.marker({"AGENT_BRIDGE_DEPTH": " 1 "}) == "AGENT_BRIDGE_DEPTH>0"
    assert foreign_session.marker({"AGENT_BRIDGE_DEPTH": "garbage"}) == "AGENT_BRIDGE_DEPTH=unreadable"
    assert foreign_session.marker({"THALIRIS_FOREIGN_CHILD": "1"}) == "THALIRIS_FOREIGN_CHILD=1"
    assert foreign_session.marker({"AGENT_BRIDGE_DEPTH": "-1"}) is None
    # Neither value is consulted by the actor assurance: nothing here can mint Controller standing.
    monkeypatch.setenv("AGENT_BRIDGE_DEPTH", "1")
    monkeypatch.setenv("THALIRIS_FOREIGN_CHILD", "1")
    assert _REAL_ASSURANCE({}) == "UNKNOWN"
    assert _REAL_ASSURANCE({"session_id": "s"}) == "UNKNOWN"


def test_runner_command_set_covers_every_child_denied_control_operation() -> None:
    assert lifecycle_module._CHILD_CONTEXT_MUTATIONS <= foreign_session.DENIED_COMMANDS
    assert {"task-start", "task-associate", "task-recover-authority", "task-mode", "task-evidence-register", "task-judge",
            "task-observe", "task-close", "task-dispose-dependency", "task-abandon", "codex-install",
            "codex-maintenance-plan", "codex-model-catalog-refresh"} <= foreign_session.DENIED_COMMANDS
    for read_only in ("task-status", "task-show", "task-get", "doctor", "version", "catalog", "document-get",
                      "audit-hook", "codex-bootstrap", "controller-instructions"):
        assert read_only not in foreign_session.DENIED_COMMANDS


@pytest.mark.parametrize(("name", "value"), MARKERS)
def test_runner_refuses_authority_commands_in_a_foreign_session(tmp_path: Path, monkeypatch, capsys, name: str, value: str) -> None:
    root = repo(tmp_path)
    monkeypatch.setenv(name, value)
    for argv in (["task-start", "goal"], ["task-close", "--base-revision", "1"], ["codex-install", "--maintenance-contract", "contract.json"],
                 ["task-start", "goal", "--authority-contract", str(tmp_path / "contract.json")],
                 ["task-observe", "--role", "implementer", "--observation-json", "{}"], ["task-verify", "--role", "implementer", "--check", "c1"], ["codex-model-catalog-refresh"]):
        code = cli.main(["--root", str(root), *argv])
        out = capsys.readouterr().out
        assert code == 2, argv
        assert "THALIRIS_FOREIGN_SESSION" in out, argv
    assert not (root / ".context" / "state.json").exists()
    # Read-only status and diagnostics remain available.
    assert cli.main(["--root", str(root), "version"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_runner_bootstrap_in_a_foreign_session_returns_a_note_without_guidance_or_init(tmp_path: Path, monkeypatch, capsys) -> None:
    root = repo(tmp_path)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts)
    monkeypatch.setenv("AGENT_BRIDGE_DEPTH", "1")
    assert cli.main(["--root", str(root), "codex-bootstrap"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "FOREIGN_SESSION_UNMANAGED" and out["init_invoked"] is False
    assert out["controller_actor_assurance"] == "UNKNOWN"
    assert not any(key.startswith("controller_guidance") or key == "content" for key in out)
    assert codex_bootstrap.bootstrap(root) == foreign_session.bootstrap_note()
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts) == before


def test_normal_runner_session_is_unchanged(tmp_path: Path, capsys) -> None:
    root = repo(tmp_path)
    assert cli.main(["--root", str(root), "version"]) == 0
    capsys.readouterr()
    assert cli.main(["--root", str(root), "task-status"]) in {0, 2, 3}
    assert "THALIRIS_FOREIGN_SESSION" not in capsys.readouterr().out
