"""Codex cross-Host reservation, checked launcher tickets and foreign hook policy."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import socket
import time
import uuid

from thaliris import authority, core

from . import foreign_session, lifecycle, task_authority

READONLY_ROLES = ("investigator", "reviewer", "reasoning-specialist")
CLAUDE_DEFAULT_MODEL = {"investigator": "haiku", "reviewer": "sonnet", "reasoning-specialist": "sonnet"}
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
ROLE_GUIDANCE = {
    "investigator": "Verify selected facts with exact sources and identify decision-changing unknowns.",
    "reviewer": "Review the selected behavior and report defects or missing evidence with their source and impact.",
    "reasoning-specialist": "Evaluate the selected constraints, evidence, and viable choices. Report the basis and limits of your conclusion.",
}
HANDOFF = r"handoff-[0-9a-f]{32}"
TASK_ENV = "THALIRIS_TASK_ID"
HANDOFF_ENV = "THALIRIS_HANDOFF_ID"
TICKET_LIFETIME_NS = 120_000_000_000
DIRECT_RUNS = "xhost_direct_runs"


def handoff_in(state, handoff_id):
    return next((item for item in state.get("evidence_continuity", {}).get("handoffs", [])
                 if item.get("id") == handoff_id and item.get("executor_host")), None)


def live_handoffs(state):
    return [item for item in state.get("evidence_continuity", {}).get("handoffs", [])
            if item.get("executor_host") == "claude" and item.get("run_state") in core.FOREIGN_LIVE_RUN_STATES]


def _require_controller(root, owner_hash):
    task_id = core.selected_task(root)
    anchor = task_authority.check(root)
    if (task_id is None or anchor is None or not _controller_session_matches(root, task_id, owner_hash)
            or owner_hash in anchor["fenced_sessions"] or lifecycle._session_fenced(root, owner_hash)):
        raise ValueError("XHOST_CONTROLLER_REQUIRED: an intact ACTIVE task and its owning Codex session are required")
    contract = anchor["contract"]
    if contract["execution_mode"] == "single-agent" or contract.get("execution_constraint") is not None:
        raise ValueError("XHOST_ROUTE_REFUSED: this task's frozen execution policy does not authorize a Claude child")


def _controller_session_matches(root, task_id, session_hash):
    if not isinstance(session_hash, str) or re.fullmatch(r"[0-9a-f]{64}", session_hash) is None:
        return False
    path = lifecycle._association_path(root, session_hash)
    if path.is_file():
        value = json.loads(path.read_bytes())
        return isinstance(value, dict) and value.get("version") == 1 and value.get("task_id") == task_id
    return lifecycle.active_controller_owner(root, task_id) == session_hash


def _controller_hook_session(payload):
    if (lifecycle._controller_actor_assurance(payload) == "CHILD" or payload.get("readonly") is True
            or payload.get("fenced") is True):
        raise ValueError("XHOST_CONTROLLER_REQUIRED")
    return lifecycle._session_id_hash(payload)


def pinned_controller_command(payload):
    tool = payload.get("tool_name") or payload.get("tool")
    command = lifecycle._bash_command(payload)
    if tool not in ("Bash", "exec_command", "functions.exec_command") or command is None:
        return False
    runner = lifecycle._trusted_installed_runner()
    if runner is None:
        return False
    direct = command.lstrip()
    if direct.startswith("& "):
        direct = direct[2:].lstrip()
    program = lifecycle._absolute_command_token(direct)
    return program is not None and Path(program).resolve() == runner


def issue_reservation_ticket(root, payload):
    task_id = core.selected_task(root)
    session_hash = _controller_hook_session(payload)
    ticket = secrets.token_hex(32)
    with task_authority._lock(root):
        _require_controller(root, session_hash)
        path = lifecycle._lifecycle_path(root, task_id)
        ledger = lifecycle._load_lifecycle(path, task_id)
        now = time.time_ns()
        tickets = {key: value for key, value in ledger.get("xhost_reservations", {}).items()
                   if type(value.get("expiry")) is int and value["expiry"] >= now}
        tickets[core.foreign_session_hash(ticket)] = {"session_hash": session_hash, "expiry": now + TICKET_LIFETIME_NS}
        ledger["xhost_reservations"] = tickets
        lifecycle._write_capture(path, ledger)
    return ticket


def reserve_from_hook(root, *, role, base_revision, input_file, ticket):
    task_id = core.selected_task(root)
    if task_id is None or not isinstance(ticket, str) or re.fullmatch(r"[0-9a-f]{64}", ticket) is None:
        raise ValueError("XHOST_CONTROLLER_TICKET_REQUIRED")
    with task_authority._lock(root):
        path = lifecycle._lifecycle_path(root, task_id)
        ledger = lifecycle._load_lifecycle(path, task_id)
        item = ledger.get("xhost_reservations", {}).pop(core.foreign_session_hash(ticket), None)
        if not isinstance(item, dict) or item["expiry"] < time.time_ns():
            raise ValueError("XHOST_CONTROLLER_TICKET_REQUIRED")
        owner_hash = item["session_hash"]
        _require_controller(root, owner_hash)
        lifecycle._write_capture(path, ledger)
    return reserve(root, role=role, base_revision=base_revision,
                   selection=core._read_input(input_file), owner_hash=owner_hash)


def reserve(root, *, role, base_revision, selection, owner_hash):
    required = {"candidate", "requirement_refs", "prompt"}
    if (role not in READONLY_ROLES or not isinstance(selection, dict) or not required <= set(selection)
            or set(selection) - required - {"claude_model", "claude_effort"}):
        raise ValueError("XHOST_HANDOFF_REQUIRED: supply a read-only role and exactly candidate, requirement_refs, and prompt")
    if not isinstance(selection["prompt"], str) or not selection["prompt"].strip():
        raise ValueError("XHOST_HANDOFF_REQUIRED: prompt must contain the selected handoff")
    model = selection.get("claude_model", CLAUDE_DEFAULT_MODEL[role])
    effort = selection.get("claude_effort")
    if (not isinstance(model, str) or re.fullmatch(r"(?:haiku|sonnet|opus|fable|claude-[a-z0-9.-]{1,70})(?:\[1m\])?", model) is None
            or effort is not None and effort not in CLAUDE_EFFORTS):
        raise ValueError("XHOST_CLAUDE_EXECUTION_INVALID")
    identifier = f"handoff-{uuid.uuid4().hex}"
    with task_authority._lock(root):
        _require_controller(root, owner_hash)
        state = core._load_state(root, active=True)
        core.check_revision(state, base_revision)
        record = {key: selection[key] for key in ("candidate", "requirement_refs")}
        record.update(id=identifier, parent_handoff_id=None, producer=role)
        refs = json.dumps(record["requirement_refs"], ensure_ascii=False)
        prompt = ("You are a read-only Thaliris " + role + ". Use only the selected handoff below. "
                  + ROLE_GUIDANCE[role] + " Do not delegate, amend the task, or run verification commands. "
                  "After your substantive findings, finish with a fenced `thaliris-claims` block. Its body is `none` "
                  "or JSON {\"claims\":[{\"requirement\":\"<ref>\",\"polarity\":\"supports|contradicts|unknown\","
                  "\"text\":\"<fact>\",\"evidence\":\"<path:line>\",\"basis\":\"read|inference\"}]}. "
                  f"Use only these selected requirement refs: {refs}.\n\n" + selection["prompt"])
        settings = json.dumps({"model": model, "effort": effort}, separators=(",", ":"))
        result = core.reserve_foreign_handoff(state, record, executor_host="claude", prompt=settings + "\n" + prompt, root=root)
        lifecycle._write_evidence_reservation(root, state, lifecycle._lifecycle_path(root, state["task_id"]), None)
    return {"ok": True, "task_id": state["task_id"], "revision": state["revision"], "foreign": result,
            "launch_args": ["xhost-run", "--handoff", identifier]}


def result(root, handoff_id):
    with task_authority._lock(root):
        task_authority.check(root, enforce_execution_constraint=False)
        state = core._load_state(root)
        text = core.foreign_body(root, state, handoff_id, "result")
        handoff = handoff_in(state, handoff_id)
        return {"ok": True, "task_id": state["task_id"], "handoff_id": handoff_id, "kind": "result",
                "sha256": handoff["result_sha256"], "run_state": handoff["run_state"], "role": handoff["producer"],
                "candidate": handoff["candidate"], "executor_host": handoff["executor_host"], "text": text}


def issue_launch_ticket(root, handoff_id, payload):
    task_id = core.selected_task(root)
    session_hash = _controller_hook_session(payload)
    if not isinstance(handoff_id, str) or re.fullmatch(HANDOFF, handoff_id) is None:
        raise ValueError("XHOST_HANDOFF_REQUIRED: supply the exact reserved handoff ID")
    with task_authority._lock(root):
        _require_controller(root, session_hash)
        path = lifecycle._lifecycle_path(root, task_id)
        ledger = lifecycle._load_lifecycle(path, task_id)
        state = core._load_state(root, active=True)
        handoff = handoff_in(state, handoff_id)
        if handoff is None or handoff["executor_host"] != "claude" or handoff["run_state"] != "reserved":
            raise ValueError("XHOST_RESERVATION_REQUIRED: launch requires the exact unlaunched Claude handoff")
        live = {row["id"] for row in live_handoffs(state)}
        launches = {key: value for key, value in ledger.get(DIRECT_RUNS, {}).items() if key in live}
        ticket = secrets.token_hex(32)
        launches[handoff_id] = {"ticket_hash": core.foreign_session_hash(ticket),
            "session_hash": session_hash, "issued_at": time.time_ns()}
        ledger[DIRECT_RUNS] = launches
        lifecycle._write_capture(path, ledger)
    return ticket


def selector_path(session_hash):
    return Path.home() / ".thaliris" / "xhost-sessions" / (session_hash + ".json")


def has_selector(session_hash):
    return session_hash is not None and (selector_path(session_hash).exists() or authority._is_link(selector_path(session_hash)))


def publish_selector(root, task_id, handoff_id, session_hash):
    path = selector_path(session_hash)
    if path.exists() or any(authority._is_link(target) for target in (path, *path.parents)):
        raise ValueError("XHOST_SESSION_SELECTOR_UNSAFE")
    data = {"root": str(root), "task_id": task_id, "handoff_id": handoff_id}
    core._atomic_write(path, (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))


def _selector(session_hash):
    path = selector_path(session_hash)
    if any(authority._is_link(target) for target in (path, *path.parents)):
        raise ValueError("XHOST_SESSION_SELECTOR_UNSAFE")
    with path.open("rb") as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError("XHOST_SESSION_SELECTOR_INVALID")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"root", "task_id", "handoff_id"}:
        raise ValueError("XHOST_SESSION_SELECTOR_INVALID")
    return data


@contextmanager
def _selection(root, task_id):
    prior = core.selected_task(root)
    core.select_task(root, task_id)
    try:
        yield
    finally:
        core.select_task(root, prior)


def incoming(root, payload):
    """Return None for an ordinary Hook, otherwise a strictly deny-only classification."""
    hints = [os.environ.get(TASK_ENV), os.environ.get(HANDOFF_ENV)]
    marked = foreign_session.marker(os.environ) == f"{foreign_session.MARKER_ENV}=1"
    session_hash = lifecycle._session_id_hash(payload)
    if session_hash is None:
        return {"live": False} if marked else None
    try:
        try:
            data = _selector(session_hash)
        except FileNotFoundError:
            if not marked:
                return None
            return {"live": False}
        if any(hints) and hints != [data["task_id"], data["handoff_id"]]:
            return {"live": False}
        selected_root = Path(data["root"])
        task_id = data["task_id"]
        if (not isinstance(task_id, str) or str(uuid.UUID(task_id)) != task_id
                or not selected_root.is_absolute() or selected_root.resolve() != root):
            return {"live": False}
        identifier = core._bounded_label(data["handoff_id"], "foreign handoff ID")
        with _selection(root, task_id):
            state = core._load_state(root)
            foreign = handoff_in(state, identifier)
            if (foreign is None or foreign.get("executor_host") != "codex"
                    or foreign.get("foreign_session_hash") != session_hash or state.get("task_id") != task_id
                    or foreign.get("producer") not in READONLY_ROLES):
                return {"live": False}
            binding, changed = core.bind_foreign_session(state, session_hash)
            if not changed and binding is not None and binding["handoff_id"] == identifier:
                return {**binding, "live": binding["run_state"] == "bound" and state.get("status") == "ACTIVE"}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        pass
    return {"live": False}


def _inside(root, base, name):
    if not isinstance(name, str) or not name or any(ord(character) < 32 for character in name):
        return False
    candidate = Path(name)
    return (":" not in name[len(candidate.drive):] and (not candidate.drive or candidate.is_absolute())
            and (base / candidate).resolve().is_relative_to(root))


def _inspection_dynamic_tool(root, payload):
    tool = payload.get("tool_name") or payload.get("tool")
    arguments = payload.get("tool_input")
    if not isinstance(arguments, dict):
        return False
    if tool == "read_file":
        expected = {"path", "start_line"}
        line = arguments.get("start_line", 1)
        if "path" not in arguments or type(line) is not int or line < 1:
            return False
    elif tool == "list_files":
        expected = {"path"}
    elif tool == "search_files":
        expected = {"query", "path"}
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return False
    else:
        return False
    try:
        return set(arguments) <= expected and _inside(root, root, arguments.get("path", "."))
    except (OSError, ValueError, TypeError, RuntimeError):
        return False


def incoming_hook(root, event, payload):
    binding = incoming(root, payload)
    if binding is None:
        return None
    if event == "PreToolUse":
        if binding["live"] and payload.get("fenced") is not True and _inspection_dynamic_tool(root, payload):
            return ""
        return lifecycle._permission_deny("XHOST_FOREIGN_CHILD_READONLY: only exact live foreign children may use the dedicated inspection tools")
    if event == "SessionStart":
        note = ("This is a read-only foreign Thaliris child. Use the supplied handoff and return its claims in FINAL."
                if binding["live"] else "This foreign Thaliris session has no live, exact handoff binding.")
        return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": note}})
    return ""


def cancel(state, handoff_id, cause):
    """Under the dispatching adapter's task lock, mark cancellation before result commit."""
    handoff = handoff_in(state, handoff_id)
    if handoff is None or handoff.get("executor_host") != "claude" or handoff["run_state"] not in core.FOREIGN_LIVE_RUN_STATES:
        return False
    return core.cancel_foreign_run(state, handoff_id, cause)[1]


def signal_cancel(launch):
    endpoint = launch.get("endpoint") if isinstance(launch, dict) else None
    if not isinstance(endpoint, dict):
        return
    windows_event = endpoint.get("event")
    if os.name == "nt" and isinstance(windows_event, str) and re.fullmatch(r"Local\\Thaliris-XHost-[0-9a-f]{64}", windows_event):
        # Kernel event cancellation remains available when the Controller tool
        # runs under a filesystem sandbox without a network grant.
        from ctypes import WinDLL
        from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR
        kernel = WinDLL("kernel32", use_last_error=True)
        kernel.OpenEventW.argtypes, kernel.OpenEventW.restype = (DWORD, BOOL, LPCWSTR), HANDLE
        kernel.SetEvent.argtypes, kernel.SetEvent.restype = (HANDLE,), BOOL
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = (HANDLE,), BOOL
        event = kernel.OpenEventW(2, False, windows_event)  # EVENT_MODIFY_STATE
        if event:
            try:
                kernel.SetEvent(event)
            finally:
                kernel.CloseHandle(event)
    elif (type(endpoint.get("port")) is int and 0 < endpoint["port"] < 65536
            and isinstance(endpoint.get("nonce"), str) and re.fullmatch(r"[0-9a-f]{64}", endpoint["nonce"])):
        try:
            with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=1.0) as connection:
                connection.sendall(endpoint["nonce"].encode("ascii"))
        except (OSError, KeyError, TypeError, ValueError):
            # The launcher may have exited. Cancellation is a ledger fact;
            # this send never supplies external termination proof.
            pass
