"""Foreign (agent-started) sessions and MCP tools that delegate to other agents.

Two small, pure policies live here; ``lifecycle`` and ``cli`` apply them.

Foreign sessions. A Codex session started by another agent (for example
``codex exec`` launched by an MCP bridge) is not the user's Controller. Its
environment may carry ``AGENT_BRIDGE_DEPTH`` (bridge nesting depth) or
``THALIRIS_FOREIGN_CHILD=1``. An environment value can only LOWER authority:
it demotes the session to an unmanaged foreign actor and never mints a
Controller, a child binding or any other grant. Hook processes and runner
invocations inherit the Host process environment, so both read it directly.

MCP tools. Codex names an MCP tool ``mcp__<server>__<tool>``. A Thaliris child
must not spawn or delegate to agents, or run commands, outside Thaliris
management; the classification is a conservative word heuristic over the tool
part of the name, not a sandbox.
"""
from __future__ import annotations

import os
import re
from typing import Mapping

DEPTH_ENV = "AGENT_BRIDGE_DEPTH"
MARKER_ENV = "THALIRIS_FOREIGN_CHILD"
_MARKER_TRUE = frozenset({"1", "true", "yes", "on"})

# Runner commands that establish or use Controller authority, change task state or
# mutate the Host or project integration. A foreign session may run none of
# them. Read-only status and diagnostics (task-status, task-show, task-get,
# artifact-get, catalog, document-get, doctor, stale, memory-status,
# milestone-check, identity-status/get/trace, version, runtime-check,
# controller-instructions) stay available; ``audit-hook`` is the Host's own
# transport and is never refused here. ``codex-bootstrap`` answers with a short
# unmanaged-session note instead of guidance.
DENIED_COMMANDS = frozenset({
    "xhost-reserve", "xhost-run", "xhost-result",
    "task-start", "task-associate", "task-recover-authority", "task-recover-state", "task-mode",
    "task-update", "task-artifact", "task-close", "task-promote", "task-abandon", "task-dispose-dependency",
    "task-evidence-register", "task-judge", "task-check", "task-observe", "task-verify", "document-maintain",
    "init", "rollback", "uninstall", "codex-install", "codex-uninstall", "codex-maintenance-plan",
    "codex-model-catalog-refresh",
    "identity-amend", "identity-challenge", "identity-relate", "identity-note", "identity-suggest",
})

NOTE = ("This is an unmanaged foreign session: it was started by another agent, so it is UNKNOWN and not a Thaliris "
        "Controller. Thaliris task control, managed children and Host maintenance are unavailable here; ordinary "
        "workspace work and read-only status remain available. Delegation must go through Thaliris dispatch.")


def marker(environ: Mapping[str, str] | None = None) -> str | None:
    """Name the environment marker that demotes this process, or None.

    A positive ``AGENT_BRIDGE_DEPTH`` or ``THALIRIS_FOREIGN_CHILD=1`` demotes. An
    unparseable non-empty depth also demotes (an unreadable value fails toward
    less authority); absent, empty or ``0`` does not.
    """
    environ = os.environ if environ is None else environ
    if str(environ.get(MARKER_ENV, "")).strip().lower() in _MARKER_TRUE:
        return f"{MARKER_ENV}=1"
    depth = str(environ.get(DEPTH_ENV, "")).strip()
    if not depth:
        return None
    try:
        return f"{DEPTH_ENV}>0" if int(depth) > 0 else None
    except ValueError:
        return f"{DEPTH_ENV}=unreadable"


def bootstrap_note() -> dict[str, object]:
    """The only answer a foreign session gets from ``codex-bootstrap``: no init, no guidance."""
    return {"ok": True, "status": "FOREIGN_SESSION_UNMANAGED", "init_invoked": False,
            "session_restart_required": False, "ordinary_workspace_work_allowed": True,
            "controller_actor_assurance": "UNKNOWN", "managed_control_authority": "UNAVAILABLE", "note": NOTE}


def command_denial(command: str) -> str:
    return (f"THALIRIS_FOREIGN_SESSION: `{command}` is refused in an unmanaged foreign session (started by another "
            "agent); it is UNKNOWN and holds no Controller or child standing. Delegation must go through Thaliris "
            "dispatch by the owning Controller.")


_COMMAND_TEXT = re.compile("|".join(re.escape(name) for name in sorted(DENIED_COMMANDS, key=len, reverse=True)))


def mentions_denied_command(text: str) -> str | None:
    """A denied runner command named in shell text that also names the runner.

    Defence in depth for the hook: a command that is not a direct canonical runner
    call (``env -u ... thaliris task-start``) is not parsed as one, but a foreign
    session may not smuggle a denied command through shell syntax either.
    """
    lowered = text.casefold()
    if "thaliris" not in lowered:
        return None
    for match in _COMMAND_TEXT.finditer(lowered):
        before = lowered[match.start() - 1] if match.start() else " "
        after = lowered[match.end()] if match.end() < len(lowered) else " "
        if not (before.isalnum() or before in "-_") and not (after.isalnum() or after in "-_"):
            return match.group(0)
    return None


# --- MCP tool classification -------------------------------------------------------------------------------------
# Deny words win over allow words. Spawning (delegate/publish/spawn/exec/run/bash/shell/schedule) is refused for
# every child, writing roles included.
_MCP_SPAWN = ("delegate", "publish", "spawn", "exec", "run", "bash", "shell", "schedul")
_MCP_MUTATING = ("task", "write", "edit", "create", "delete", "cancel")
_MCP_READ = frozenset({"read", "get", "list", "search", "fetch", "query", "status", "health", "wait", "output"})
_MCP_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def is_mcp_tool(tool_name: object) -> bool:
    return isinstance(tool_name, str) and tool_name.startswith("mcp__")


def mcp_tool_part(tool_name: str) -> str:
    parts = tool_name.split("__", 2)
    return parts[2] if len(parts) == 3 and parts[0] == "mcp" else tool_name


def mcp_class(tool_name: str) -> str:
    """``spawn``, ``mutating``, ``read`` or ``unknown`` for an MCP tool name."""
    words = [word.lower() for word in _MCP_WORDS.findall(mcp_tool_part(tool_name))]
    if any(word.startswith(_MCP_SPAWN) for word in words):
        return "spawn"
    if any(word.startswith(_MCP_MUTATING) for word in words):
        return "mutating"
    if any(word in _MCP_READ or (word.endswith("s") and word[:-1] in _MCP_READ) for word in words):
        return "read"
    return "unknown"


def mcp_denial(tool_name: str, writes: bool | None) -> str | None:
    """Why a Thaliris child may not call this MCP tool, or None.

    ``writes`` is the child's verified role permission. A writing role is refused
    only agent-spawning and command-running tools. A read-only or unverified
    (``None``) role may call only read-classified tools; unknown tools are refused.
    """
    kind = mcp_class(tool_name)
    if kind == "spawn":
        return (f"THALIRIS_MCP_DELEGATION: MCP tool `{tool_name}` spawns or delegates to agents or runs commands "
                "outside Thaliris management; Thaliris children must not create unmanaged agents. Delegation must "
                "go through Thaliris dispatch (the Controller's native spawn with a fresh `thaliris-*` role). "
                "Return the need in your final report.")
    if writes is not True and kind != "read":
        return (f"THALIRIS_MCP_NOT_READ_ONLY: MCP tool `{tool_name}` is not classified read-only ({kind}); a "
                "non-writing or unverified Thaliris child may call only read-only MCP tools (names with read, get, "
                "list, search, fetch, query, status, health, wait or output). Delegation must go through Thaliris "
                "dispatch; return the need in your final report.")
    return None
