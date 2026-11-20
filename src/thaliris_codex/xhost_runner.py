"""Deterministic Claude subprocess owner for one Codex cross-Host handoff."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid

from thaliris import core

from . import foreign_session, lifecycle, task_authority, xhost

TIMEOUTS = {"investigator": 180, "reviewer": 480, "reasoning-specialist": 600}
_LINE_LIMIT = 2 * 1024 * 1024


class _WindowsJob:
    """Kill every member when the launcher closes or loses its job handle."""

    def __init__(self):
        from ctypes import Structure, WinDLL, c_int64, c_size_t, get_last_error, pointer, sizeof, WinError
        from ctypes.wintypes import BOOL, DWORD, HANDLE, LPVOID, UINT

        class Limits(Structure):
            _fields_ = [("process_time", c_int64), ("job_time", c_int64), ("flags", DWORD), ("min_working_set", c_size_t),
                        ("max_working_set", c_size_t), ("active_processes", DWORD), ("affinity", c_size_t),
                        ("priority", DWORD), ("scheduling", DWORD)]

        class Accounting(Structure):
            _fields_ = [(field, c_int64) for field in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(Structure):
            _fields_ = [("basic", Limits), ("io", Accounting), ("process_memory_limit", c_size_t),
                        ("job_memory_limit", c_size_t), ("peak_process", c_size_t), ("peak_job", c_size_t)]

        kernel = WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = (LPVOID, LPVOID), HANDLE
        kernel.SetInformationJobObject.argtypes, kernel.SetInformationJobObject.restype = (HANDLE, UINT, LPVOID, DWORD), BOOL
        kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = (HANDLE, HANDLE), BOOL
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = (HANDLE,), BOOL
        self._handle = kernel.CreateJobObjectW(None, None)
        self._kernel = kernel
        self._error = lambda: WinError(get_last_error())
        if not self._handle:
            raise self._error()
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(self._handle, 9, pointer(limits), sizeof(limits)):
            error = self._error()
            self.close()
            raise error

    def assign(self, process):
        if not self._kernel.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise self._error()

    def close(self):
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


@contextmanager
def _owned_process(argv, root, environment):
    job = _WindowsJob() if os.name == "nt" else None
    process = None
    try:
        process = subprocess.Popen(argv, cwd=root, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=job is None)
        if job is not None:
            try:
                job.assign(process)
            except OSError:
                process.kill()
                raise
        # The prompt is still withheld. Windows kills child jobs on parent
        # disappearance, and POSIX limits our signals to this process group.
        yield process
    finally:
        if job is not None:
            job.close()
        elif process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process is not None:
            process.wait(timeout=10)
            process.stdout.close()
            process.stdin.close()


@contextmanager
def _windows_cancel_listener(events, stop):
    from ctypes import WinDLL, WinError, get_last_error
    from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR, LPVOID

    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes, kernel.CreateEventW.restype = (LPVOID, BOOL, BOOL, LPCWSTR), HANDLE
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = (HANDLE, DWORD), DWORD
    kernel.SetEvent.argtypes, kernel.SetEvent.restype = (HANDLE,), BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = (HANDLE,), BOOL
    name = "Local\\Thaliris-XHost-" + secrets.token_hex(32)
    event = kernel.CreateEventW(None, True, False, name)
    if not event:
        raise WinError(get_last_error())

    def receive():
        if kernel.WaitForSingleObject(event, 0xFFFFFFFF) == 0:
            _publish(events, stop, ("cancel", None))

    worker = threading.Thread(target=receive, daemon=True)
    try:
        worker.start()
        yield {"event": name}
    finally:
        stop.set()
        kernel.SetEvent(event)
        if worker.ident is not None:
            worker.join()
        kernel.CloseHandle(event)


@contextmanager
def _cancel_listener(events, stop):
    if os.name == "nt":
        with _windows_cancel_listener(events, stop) as endpoint:
            yield endpoint
        return
    nonce = secrets.token_hex(32)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def receive():
            try:
                while True:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(1.0)
                        try:
                            with connection.makefile("rb") as stream:
                                data = stream.read(len(nonce))
                        except OSError:
                            continue
                        if secrets.compare_digest(data, nonce.encode("ascii")):
                            _publish(events, stop, ("cancel", None))
                            return
            except OSError:
                pass

        threading.Thread(target=receive, daemon=True).start()
        try:
            yield {"port": listener.getsockname()[1], "nonce": nonce}
        finally:
            stop.set()
            try:
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _consume_and_prebind(root, handoff_id, ticket, session_id, endpoint):
    if not isinstance(ticket, str) or re.fullmatch(r"[0-9a-f]{64}", ticket) is None:
        raise ValueError("XHOST_LAUNCH_TICKET_REQUIRED")
    task_id = core.selected_task(root)
    with task_authority._lock(root):
        anchor = task_authority.check(root)
        if anchor is None or task_id is None:
            raise ValueError("XHOST_TASK_AUTHORITY_REQUIRED")
        state = core._load_state(root, active=True)
        path = lifecycle._lifecycle_path(root, task_id)
        ledger = lifecycle._load_lifecycle(path, task_id)
        launch = ledger.get(xhost.DIRECT_RUNS, {}).get(handoff_id)
        if not isinstance(launch, dict) or launch.get("ticket_hash") != core.foreign_session_hash(ticket):
            raise ValueError("XHOST_LAUNCH_TICKET_REQUIRED")
        if not 0 <= time.time_ns() - launch["issued_at"] <= xhost.TICKET_LIFETIME_NS:
            raise ValueError("XHOST_LAUNCH_TICKET_EXPIRED")
        xhost._require_controller(root, launch["session_hash"])
        handoff = xhost.handoff_in(state, handoff_id)
        if handoff is None or handoff["executor_host"] != "claude" or handoff["producer"] not in xhost.READONLY_ROLES:
            raise ValueError("XHOST_RESERVATION_REQUIRED")
        body = core.foreign_body(root, state, handoff_id, "prompt")
        settings, _, prompt = body.partition("\n")
        options = json.loads(settings)
        if not prompt or not isinstance(options, dict) or set(options) != {"model", "effort"}:
            raise ValueError("XHOST_FOREIGN_PROMPT_INVALID")
        foreign_hash = core.foreign_session_hash(session_id)
        core.register_foreign_launch(state, handoff_id, foreign_hash, launch["session_hash"])
        binding, changed = core.bind_foreign_session(state, foreign_hash)
        if not changed or binding is None or binding["handoff_id"] != handoff_id:
            raise ValueError("XHOST_FOREIGN_PREBIND_FAILED")
        xhost.publish_selector(root, task_id, handoff_id, foreign_hash)
        launch.pop("ticket_hash")
        launch["endpoint"] = endpoint
        lifecycle._write_evidence_reservation(root, state, path, ledger)
        return prompt, options, handoff["producer"]


def _claude_command(executable, session_id, config, options):
    args = [executable, "-p", "--session-id", session_id, "--tools", "Read,Grep,Glob",
            "--strict-mcp-config", "--mcp-config", str(config), "--permission-mode", "dontAsk",
            "--output-format", "stream-json", "--verbose", "--no-session-persistence", "--model", options["model"]]
    if options["effort"] is not None:
        args.extend(("--effort", options["effort"]))
    return args


def _subscription(executable, root, env):
    try:
        status = subprocess.run([executable, "auth", "status", "--json"], cwd=root, env=env,
                                capture_output=True, check=True, timeout=5)
        info = json.loads(status.stdout)
        return (isinstance(info, dict) and info.get("loggedIn") is True
                and info.get("apiProvider") == "firstParty" and info.get("authMethod") == "claude.ai")
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _publish(events, stop, item):
    while not stop.is_set():
        try:
            events.put(item, timeout=1.0)
            return
        except queue.Full:
            continue


def _events(process, events, stop):
    try:
        while not stop.is_set():
            raw = process.stdout.readline(_LINE_LIMIT + 1)
            if not raw:
                break
            if len(raw) > _LINE_LIMIT:
                _publish(events, stop, ("protocol", None))
                return
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if isinstance(event, dict):
                _publish(events, stop, ("event", event))
    except (OSError, ValueError):
        pass
    finally:
        _publish(events, stop, ("eof", None))


def _feed(process, prompt):
    try:
        with process.stdin as handle:
            handle.write(prompt.encode("utf-8"))
    except OSError:
        pass


class _ClaudeOutput:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result = None
        self.partial = ""
        self.tool_ids = set()
        self.auth = "unknown"
        self.subscription = False
        self.saw_init = False

    def accept(self, event):
        if event.get("session_id") != self.session_id:
            return False
        if event.get("type") == "system" and event.get("subtype") == "init":
            tools = event.get("tools")
            source = event.get("apiKeySource")
            if source in ("ANTHROPIC_API_KEY", "apiKeyHelper"):
                self.auth = "metered"
            elif source == "none" and self.subscription:
                self.auth = "subscription-notional"
            if (not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools)
                    or set(tools) != {"Read", "Grep", "Glob"} or event.get("mcp_servers") != []):
                return False
            self.saw_init = True
        if event.get("type") == "assistant" and isinstance(event.get("message"), dict):
            content = event["message"].get("content")
            if isinstance(content, list):
                texts = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                        if block.get("name") not in {"Read", "Grep", "Glob"}:
                            return False
                        self.tool_ids.add(block["id"])
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        texts.append(block["text"])
                if texts:
                    self.partial = "\n".join(texts)
        if event.get("type") == "result":
            self.result = event
        return True

    def usage(self, effort):
        result = self.result or {}
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        model_usage = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}

        def count(value):
            return value if type(value) is int and 0 <= value <= core.LANE_COUNTER_MAX else None

        models = [(count(detail.get("outputTokens")) or 0, model) for model, detail in model_usage.items()
                  if isinstance(detail, dict) and isinstance(model, str) and 0 < len(model) <= 128]
        model = max(models)[1] if models else None
        inputs = [count(usage.get(field)) for field in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
        input_tokens = count(sum(value or 0 for value in inputs)) if inputs[0] is not None else None
        output_tokens = count(usage.get("output_tokens"))
        total = count(input_tokens + output_tokens) if input_tokens is not None and output_tokens is not None else None
        cost = result.get("total_cost_usd")
        return dict(model=model, effort=effort, input_tokens=input_tokens, output_tokens=output_tokens,
                    total_tokens=total, cost_usd=cost if type(cost) in (int, float) and math.isfinite(cost) and 0 <= cost <= 1e9 else None,
                    cost_basis=self.auth, duration_ms=count(result.get("duration_ms")), tool_uses=count(len(self.tool_ids)))


def _collect(process, events, stop, output, timeout):
    deadline = time.monotonic() + timeout
    threading.Thread(target=_events, args=(process, events, stop), daemon=True).start()
    threading.Thread(target=lambda: _publish(events, stop, ("exit", process.wait())), daemon=True).start()
    eof = False
    exit_code = None
    while True:
        try:
            kind, event = events.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            return "timeout"
        if kind == "eof":
            eof = True
        elif kind == "exit":
            exit_code = event
        elif kind == "cancel":
            return "cancelled"
        elif kind == "protocol" or not output.accept(event):
            output.result = None
            output.partial = ""
            return "protocol"
        if eof and exit_code is not None:
            success = exit_code == 0 and output.saw_init and output.result is not None and output.result.get("is_error") is False
            return "completed" if success else "failed"
        if time.monotonic() >= deadline:
            return "timeout"


def _settle(root, handoff_id, status, result_text, usage):
    with task_authority._lock(root):
        if task_authority.check(root, enforce_execution_constraint=False) is None:
            raise ValueError("XHOST_TASK_AUTHORITY_REQUIRED")
        state = core._load_state(root, active=True)
        handoff = xhost.handoff_in(state, handoff_id)
        if handoff is None:
            raise ValueError("XHOST_RESERVATION_REQUIRED")
        if handoff["run_state"] == "cancelled":
            return {"handoff_id": handoff_id, "run_state": "cancelled"}
        if status != "completed" and not result_text:
            result, changed = core.cancel_foreign_run(state, handoff_id, "Claude runner " + status)
            if not changed:
                return result
        else:
            result = core.record_foreign_result(state, handoff_id, result_text, None, usage,
                                                outcome="completed" if status == "completed" else "failed", root=root)
        lifecycle._write_evidence_reservation(root, state, lifecycle._lifecycle_path(root, state["task_id"]), None)
        return result


def _start_if_live(stack, root, handoff_id, argv, environment, prompt):
    with task_authority._lock(root):
        if task_authority.check(root) is None:
            return None
        state = core._load_state(root, active=True)
        handoff = xhost.handoff_in(state, handoff_id)
        if handoff is None or handoff["run_state"] != "bound":
            return None
        process = stack.enter_context(_owned_process(argv, root, environment))
        threading.Thread(target=_feed, args=(process, prompt), daemon=True).start()
        return process


def _claude_executable(root):
    path = shutil.which("claude")
    if path is not None:
        executable = Path(path).resolve(strict=True)
        if executable.is_file() and not executable.is_relative_to(root) and (os.name != "nt" or executable.suffix.lower() == ".exe"):
            return str(executable)
    return None


def run(root, handoff_id, ticket):
    task_id = core.selected_task(root)
    if task_id is None:
        raise ValueError("XHOST_TASK_SELECTION_REQUIRED")
    session_id = str(uuid.uuid4())
    events = queue.Queue(maxsize=32)
    stop = threading.Event()
    with _cancel_listener(events, stop) as endpoint:
        prompt, options, role = _consume_and_prebind(root, handoff_id, ticket, session_id, endpoint)
        output = _ClaudeOutput(session_id)
        status = "launch failed"
        try:
            executable = _claude_executable(root)
            if executable is not None:
                with tempfile.TemporaryDirectory(prefix="thaliris-xhost-") as temporary:
                    config = Path(temporary) / "mcp.json"
                    config.write_text('{"mcpServers":{}}', encoding="utf-8")
                    environment = {key: value for key, value in os.environ.items()
                                   if key not in {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}}
                    environment.update({foreign_session.MARKER_ENV: "1", xhost.TASK_ENV: task_id, xhost.HANDOFF_ENV: handoff_id})
                    output.subscription = _subscription(executable, root, environment)
                    argv = _claude_command(executable, session_id, config, options)
                    with ExitStack() as child:
                        process = _start_if_live(child, root, handoff_id, argv, environment, prompt)
                        try:
                            status = (_collect(process, events, stop, output, TIMEOUTS[role])
                                      if process is not None else "cancelled")
                        finally:
                            stop.set()
        except (OSError, subprocess.SubprocessError):
            pass
        except KeyboardInterrupt:
            status = "interrupted"
        result_text = (output.result or {}).get("result", output.partial)
        if not isinstance(result_text, str) or len(result_text.encode("utf-8")) > core.FOREIGN_BODY_MAX_BYTES:
            status, result_text = "invalid result", ""
        result = _settle(root, handoff_id, status, result_text, output.usage(options["effort"]))
    summary = {"ok": True, "foreign": {key: result[key] for key in ("handoff_id", "run_state", "result_sha256") if key in result}}
    if "claims" in result:
        claims = result["claims"]
        summary["claims"] = {"status": claims["status"], "adverse_count": len(claims.get("observations", [])),
                             "support_count": sum(claims.get("supports", {}).values()),
                             "unassigned_count": len(claims.get("unassigned", []))}
    return summary
