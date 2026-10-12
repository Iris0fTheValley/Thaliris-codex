#!/usr/bin/env python3
"""Exercise the installed Codex app-server against a local Responses mock.

This is an opt-in runtime check. It never contacts a model service and keeps
all generated catalog/configuration/state inside a disposable temporary tree.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.request import ProxyHandler, build_opener
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from thaliris_codex import codex_adapter, controller_instructions, model_catalog_config, roles  # noqa: E402


ROOT_PROMPT = "THALIRIS_RUNTIME_ROOT_HISTORY_SENTINEL: dispatch selected child roles"
IMPLEMENTER_PROMPT = "THALIRIS_RUNTIME_IMPLEMENTER_TASK_SENTINEL: inspect the selected implementation slice"
REVIEWER_PROMPT = "THALIRIS_RUNTIME_REVIEWER_TASK_SENTINEL: challenge the selected contract"
SCANNER_PROMPT = "THALIRIS_RUNTIME_SCANNER_TASK_SENTINEL: collect one nested evidence set"
FORK_PRESERVE_PROMPT = "THALIRIS_RUNTIME_FORK_PRESERVE_SENTINEL"
FORK_SOURCE_PROMPT = "THALIRIS_RUNTIME_FORK_SOURCE_SENTINEL"
FORK_OVERRIDE_PROMPT = "THALIRIS_RUNTIME_FORK_OVERRIDE_SENTINEL"
PARENT_RESUME_PROMPT = "THALIRIS_RUNTIME_PARENT_RESUME_SENTINEL"
IMPLEMENTER_FOLLOWUP = "THALIRIS_RUNTIME_IMPLEMENTER_FOLLOWUP_SENTINEL"
DIRECT_CHILD_RESUME_PROMPT = "THALIRIS_RUNTIME_DIRECT_CHILD_RESUME_SENTINEL"
PARENT_ATTACHMENT_PROMPT = "THALIRIS_RUNTIME_PARENT_ATTACHMENT_SENTINEL"
AGENTS_SENTINEL = "THALIRIS_RUNTIME_PROJECT_AGENTS_SENTINEL"
ROOT_DEVELOPER_SENTINEL = "THALIRIS_CONTROLLER_DEVELOPER_SENTINEL"
DEFAULT_CHILD_SENTINEL = "THALIRIS_DEFAULT_SUBAGENT_DEVELOPER_SENTINEL"
FORK_OVERRIDE_SENTINEL = "THALIRIS_FORK_DEVELOPER_OVERRIDE_SENTINEL"
RESUME_OVERRIDE_SENTINEL = "THALIRIS_DIRECT_RESUME_OVERRIDE_SENTINEL"
RESUMED_ROLE_SENTINEL = "THALIRIS_RESUMED_ROLE_PROFILE_SENTINEL"

ROOT_IMPLEMENTER_CALL = "runtime-root-implementer"
ROOT_REVIEWER_CALL = "runtime-root-reviewer"
NESTED_SCANNER_CALL = "runtime-nested-scanner"
PARENT_FOLLOWUP_CALL = "runtime-parent-followup"
PARENT_ATTACHMENT_CALL = "runtime-parent-attachment-followup"


class VerificationError(RuntimeError):
    pass


class RuntimeUnknownError(RuntimeError):
    pass


def _json_text(value: str) -> str:
    """JSON basic strings are valid TOML basic strings for these values."""
    return json.dumps(value, ensure_ascii=False)


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _request_text(body: dict[str, Any]) -> str:
    return "\n".join(_walk_strings(body))


def _developer_texts(body: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in body.get("input", []):
        if not isinstance(item, dict) or item.get("role") != "developer":
            continue
        content = item.get("content", [])
        if isinstance(content, str):
            result.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    result.append(part["text"])
    return result


def _text_input(prompt: str) -> dict[str, Any]:
    return {"type": "text", "text": prompt, "text_elements": []}


def _event(event_type: str, payload: dict[str, Any]) -> bytes:
    payload = {"type": event_type, **payload}
    return b"event: " + event_type.encode() + b"\ndata: " + json.dumps(payload).encode() + b"\n\n"


def _tool_response(response_id: str, calls: list[tuple[str, str, str, dict[str, Any]]]) -> bytes:
    events: list[bytes] = [
        _event("response.created", {"response": {"id": response_id, "status": "in_progress"}})
    ]
    output: list[dict[str, Any]] = []
    for index, (call_id, namespace, name, args) in enumerate(calls):
        item_id = "fc_" + call_id
        encoded_args = json.dumps(args, separators=(",", ":"))
        in_progress = {
            "id": item_id,
            "type": "function_call",
            "status": "in_progress",
            "call_id": call_id,
            "namespace": namespace,
            "name": name,
            "arguments": "",
        }
        events.append(_event("response.output_item.added", {"output_index": index, "item": in_progress}))
        events.append(_event("response.function_call_arguments.delta", {
            "item_id": item_id, "output_index": index, "delta": encoded_args,
        }))
        events.append(_event("response.function_call_arguments.done", {
            "item_id": item_id, "output_index": index, "arguments": encoded_args,
        }))
        final_item = {**in_progress, "status": "completed", "arguments": encoded_args}
        events.append(_event("response.output_item.done", {"output_index": index, "item": final_item}))
        output.append(final_item)
    events.append(_event("response.completed", {
        "response": {"id": response_id, "status": "completed", "output": output},
    }))
    return b"".join(events) + b"data: [DONE]\n\n"


def _message_response(response_id: str, message: str = "synthetic completion") -> bytes:
    item_id = "msg_" + response_id
    item = {
        "id": item_id,
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": message, "annotations": []}],
    }
    events = [
        _event("response.created", {"response": {"id": response_id, "status": "in_progress"}}),
        _event("response.output_item.added", {
            "output_index": 0,
            "item": {"id": item_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []},
        }),
        _event("response.content_part.added", {
            "item_id": item_id, "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        }),
        _event("response.output_text.delta", {"item_id": item_id, "output_index": 0, "content_index": 0, "delta": message}),
        _event("response.output_text.done", {"item_id": item_id, "output_index": 0, "content_index": 0, "text": message}),
        _event("response.content_part.done", {
            "item_id": item_id, "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": message, "annotations": []},
        }),
        _event("response.output_item.done", {"output_index": 0, "item": item}),
        _event("response.completed", {"response": {"id": response_id, "status": "completed", "output": [item]}}),
    ]
    return b"".join(events) + b"data: [DONE]\n\n"


@dataclass
class CapturedRequest:
    body: dict[str, Any]
    path: str
    thread_id: str | None
    authorization_present: bool


class ResponsesMock:
    def __init__(self) -> None:
        self.requests: list[CapturedRequest] = []
        self._lock = threading.Lock()
        self._requests_changed = threading.Condition(self._lock)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802
                if self.path == "/health":
                    payload = b"ok"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_error(404, "unexpected local mock endpoint")

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw)
                except Exception:
                    self.send_error(400, "invalid JSON")
                    return
                captured = CapturedRequest(
                    body=body,
                    path=self.path,
                    thread_id=self.headers.get("thread-id"),
                    authorization_present=bool(self.headers.get("Authorization")),
                )
                with owner._requests_changed:
                    owner.requests.append(captured)
                    owner._requests_changed.notify_all()
                if self.path.rstrip("/") not in {"/v1/responses", "/responses"}:
                    self.send_error(404, "unexpected local mock endpoint")
                    return
                response = owner._response(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                self.wfile.flush()

            def log_message(self, _format, *_args):
                return

        self.server = ThreadingHTTPServer(("localhost", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.server.server_port}/v1"

    def _response(self, body: dict[str, Any]) -> bytes:
        flat = _request_text(body)
        task = next((
            _request_text(item) for item in reversed(body.get("input", []))
            if item.get("role") == "user" or item.get("type") == "agent_message"
        ), "")
        response_id = "mock_" + uuid.uuid4().hex
        if DIRECT_CHILD_RESUME_PROMPT in task:
            return _message_response(response_id)
        if PARENT_RESUME_PROMPT in task and PARENT_FOLLOWUP_CALL not in flat:
            return _tool_response(response_id, [(
                PARENT_FOLLOWUP_CALL,
                "collaboration",
                "followup_task",
                {"target": "implementer", "message": IMPLEMENTER_FOLLOWUP},
            )])
        if PARENT_ATTACHMENT_PROMPT in task and PARENT_ATTACHMENT_CALL not in flat:
            return _tool_response(response_id, [(
                PARENT_ATTACHMENT_CALL,
                "collaboration",
                "followup_task",
                {"target": "implementer", "message": DIRECT_CHILD_RESUME_PROMPT},
            )])
        if ROOT_PROMPT in task and ROOT_IMPLEMENTER_CALL not in flat and ROOT_REVIEWER_CALL not in flat:
            return _tool_response(response_id, [
                (ROOT_IMPLEMENTER_CALL, "collaboration", "spawn_agent", {
                    "message": IMPLEMENTER_PROMPT,
                    "task_name": "implementer",
                    "fork_turns": "none",
                    "agent_type": "thaliris-implementer",
                    "model": roles.ROLE_MODEL_ROUTING_DEFAULTS["implementer"][0],
                    "reasoning_effort": roles.ROLE_MODEL_ROUTING_DEFAULTS["implementer"][1],
                }),
                (ROOT_REVIEWER_CALL, "collaboration", "spawn_agent", {
                    "message": REVIEWER_PROMPT,
                    "task_name": "reviewer",
                    "fork_turns": "none",
                    "agent_type": "thaliris-reviewer",
                    "model": roles.ROLE_MODEL_ROUTING_DEFAULTS["reviewer"][0],
                    "reasoning_effort": roles.ROLE_MODEL_ROUTING_DEFAULTS["reviewer"][1],
                }),
            ])
        if IMPLEMENTER_PROMPT in task and NESTED_SCANNER_CALL not in flat:
            return _tool_response(response_id, [(
                NESTED_SCANNER_CALL,
                "collaboration",
                "spawn_agent",
                {
                    "message": SCANNER_PROMPT,
                    "task_name": "scanner",
                    "fork_turns": "none",
                    "agent_type": "thaliris-investigator",
                    "model": roles.ROLE_MODEL_ROUTING_DEFAULTS["investigator"][0],
                    "reasoning_effort": roles.ROLE_MODEL_ROUTING_DEFAULTS["investigator"][1],
                },
            )])
        return _message_response(response_id)

    def snapshot(self) -> list[CapturedRequest]:
        with self._lock:
            return list(self.requests)

    def wait_for_markers(self, markers: tuple[str, ...], timeout: float = 45) -> list[CapturedRequest]:
        # Parent tool arguments contain the child's task marker too. Only an
        # actual child request without the spawning call establishes capture.
        excluded_calls = {
            IMPLEMENTER_PROMPT: ROOT_IMPLEMENTER_CALL,
            REVIEWER_PROMPT: ROOT_REVIEWER_CALL,
            SCANNER_PROMPT: NESTED_SCANNER_CALL,
            IMPLEMENTER_FOLLOWUP: PARENT_FOLLOWUP_CALL,
            DIRECT_CHILD_RESUME_PROMPT: PARENT_ATTACHMENT_CALL,
        }

        def captured(marker: str) -> bool:
            excluded = excluded_calls.get(marker)
            return any(
                marker in (text := _request_text(request.body))
                and (excluded is None or excluded not in text)
                for request in self.requests
            )

        def has_all_markers() -> bool:
            return all(captured(marker) for marker in markers)

        with self._requests_changed:
            if not self._requests_changed.wait_for(has_all_markers, timeout=timeout):
                missing = [marker for marker in markers if not captured(marker)]
                raise VerificationError(f"timed out waiting for native Responses requests containing: {missing}")
            return list(self.requests)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class OutboundDenyProxy:
    """Keep app-server background HTTP(S) traffic inside this process."""

    def __init__(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _deny(self) -> None:
                owner.destinations.append(self.path[:240])
                self.send_response(403, "external network disabled by runtime check")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

            do_CONNECT = _deny
            do_DELETE = _deny
            do_GET = _deny
            do_HEAD = _deny
            do_OPTIONS = _deny
            do_PATCH = _deny
            do_POST = _deny
            do_PUT = _deny

            def log_message(self, _format, *_args):
                return

        self.destinations: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def install_in(self, env: dict[str, str]) -> None:
        # App-server also reads Windows' system proxy configuration. Point all
        # proxy variables at this local deny endpoint so startup/plugin traffic
        # cannot escape through the workstation proxy. Loopback model traffic
        # remains direct through NO_PROXY.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            env[name] = self.url
            env[name.lower()] = self.url
        env["NO_PROXY"] = "localhost,127.0.0.1"
        env["no_proxy"] = env["NO_PROXY"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class AppServer:
    def __init__(self, executable: Path, home: Path, cwd: Path, env: dict[str, str]) -> None:
        self.process = subprocess.Popen(
            [str(executable), "app-server", "--listen", "stdio://"],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.stderr_lines: deque[str] = deque(maxlen=200)
        self.seen_messages: deque[str] = deque(maxlen=40)
        self._next_id = 1
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()
        self.initialize()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for raw in iter(self.process.stdout.readline, b""):
            try:
                self.messages.put(json.loads(raw.decode("utf-8")))
            except Exception:
                self.messages.put({"_invalid_line": raw.decode("utf-8", "replace")[:400]})
        self.messages.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for raw in iter(self.process.stderr.readline, b""):
            self.stderr_lines.append(raw.decode("utf-8", "replace").rstrip())

    def _send(self, message: dict[str, Any]) -> None:
        if self.process.poll() is not None:
            raise VerificationError(self._process_error("app-server exited before request"))
        assert self.process.stdin is not None
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        with self._write_lock:
            self.process.stdin.write(data)
            self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any], timeout: float = 25) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VerificationError(self._process_error(f"timed out waiting for {method}"))
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise VerificationError(self._process_error(f"timed out waiting for {method}")) from exc
            if message is None:
                raise VerificationError(self._process_error(f"app-server closed while waiting for {method}"))
            observed = str(message.get("method") or ("response:" + str(message.get("id"))))
            if message.get("method") == "error":
                observed += ":" + json.dumps(message.get("params", {}), ensure_ascii=False)[:600]
            self.seen_messages.append(observed)
            if message.get("id") == request_id:
                if "error" in message:
                    raise VerificationError(f"{method} failed: {message['error'].get('message', 'unknown JSON-RPC error')}")
                return message.get("result", {})

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def initialize(self) -> None:
        self.request("initialize", {"clientInfo": {"name": "thaliris-host-evidence", "version": "1.0.0"}})
        self.notify("initialized")

    def start_turn(self, thread_id: str, prompt: str, *, model: str | None = None, effort: str | None = None) -> str:
        params: dict[str, Any] = {"threadId": thread_id, "input": [_text_input(prompt)]}
        if model is not None:
            params["model"] = model
        if effort is not None:
            params["effort"] = effort
        result = self.request("turn/start", params)
        turn = result.get("turn") or {}
        turn_id = turn.get("id") or result.get("turnId")
        if not isinstance(turn_id, str):
            raise VerificationError("turn/start response did not include a turn id")
        self.wait_turn(turn_id)
        return turn_id

    def wait_turn(self, turn_id: str, timeout: float = 25) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VerificationError(self._process_error(f"timed out waiting for native turn {turn_id}; native_messages={list(self.seen_messages)}"))
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise VerificationError(self._process_error(f"timed out waiting for native turn {turn_id}; native_messages={list(self.seen_messages)}")) from exc
            if message is None:
                raise VerificationError(self._process_error(f"app-server closed before native turn {turn_id} completed"))
            observed = str(message.get("method") or ("response:" + str(message.get("id"))))
            if message.get("method") == "error":
                observed += ":" + json.dumps(message.get("params", {}), ensure_ascii=False)[:600]
            self.seen_messages.append(observed)
            if message.get("method") == "turn/completed":
                params = message.get("params") or {}
                turn = params.get("turn") or {}
                if params.get("turnId") == turn_id or turn.get("id") == turn_id:
                    if turn.get("status") != "completed":
                        raise VerificationError(f"native turn did not complete successfully: {turn}")
                    return message
            if message.get("method") == "error":
                params = message.get("params") or {}
                error = params.get("error") or {}
                details = error.get("additionalDetails") or error.get("message") or "native request transport error"
                if params.get("willRetry") is True and "Connection failed" in str(details):
                    raise VerificationError(
                        f"native Responses transport reported a connection failure: {details}; "
                        f"native_messages={list(self.seen_messages)}; "
                        f"{self._process_error('app-server transport diagnostic')}"
                    )

    def _process_error(self, label: str) -> str:
        status = self.process.poll()
        stderr = "\n".join(self.stderr_lines)
        return f"{label}; process_exit={status}; stderr_tail={stderr[-9000:]}"

    def close(self) -> None:
        if self.process.poll() is None:
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=4)
        self._reader.join(timeout=1)
        self._stderr_reader.join(timeout=1)


def _find_codex() -> tuple[Path, str]:
    selected = os.environ.get("THALIRIS_CODEX_EXECUTABLE") or shutil.which("codex")
    if not selected:
        raise RuntimeUnknownError("codex CLI is not available on PATH; installed runtime request capture is UNKNOWN")
    executable = Path(selected).resolve()
    version = subprocess.run([str(executable), "--version"], capture_output=True, timeout=15, check=False)
    actual = version.stdout.decode("utf-8", "replace").strip()
    if version.returncode != 0 or model_catalog_config.cache_client_version(actual) is None:
        raise RuntimeUnknownError(f"installed CLI version could not be parsed; runtime acceptance is unknown: {actual!r}")
    return executable, actual


def _isolated_env(home: Path, scratch: Path) -> dict[str, str]:
    # Windows exposes environment names in uppercase through os.environ.
    # Dropping SYSTEMROOT breaks the native Windows CLI's HTTP transport,
    # even when Python's mock health request succeeds in the parent process.
    allow = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allow}
    env.update({"CODEX_HOME": str(home), "TEMP": str(scratch), "TMP": str(scratch), "CODEX_DISABLE_AUTO_UPDATE": "1"})
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "OPENAI_API_KEY", "CODEX_SESSION_ID", "CODEX_INTERNAL_ORCHESTRATOR_SESSION_ID"):
        env.pop(key, None)
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["no_proxy"] = env["NO_PROXY"]
    if os.environ.get("THALIRIS_RUNTIME_DEBUG") == "1":
        env["RUST_LOG"] = "codex_core=debug,codex_models_manager=debug,reqwest=debug,hyper=debug"
    return env


def _prepare_native_profile(home: Path, role: str) -> tuple[Path, str]:
    name = f"thaliris-{role}"
    profile = codex_adapter._agent_profile(name, role, None, None)
    path = home / f"{name}.toml"
    path.write_bytes(profile)
    import tomllib

    parsed = tomllib.loads(profile.decode("utf-8"))
    instructions = parsed.get("developer_instructions")
    if not isinstance(instructions, str) or not instructions:
        raise VerificationError(f"canonical native {name} profile has no developer instructions")
    if "model" in parsed or "model_reasoning_effort" in parsed:
        raise VerificationError(f"canonical native {name} profile unexpectedly owns model routing")
    return path, instructions


def _write_home_config(home: Path, mock: ResponsesMock, catalog_path: Path) -> None:
    rows = [
        f"model = {_json_text('gpt-6-luna')}",
        "model_reasoning_effort = \"max\"",
        f"model_provider = {_json_text('mock_provider')}",
        f"model_catalog_json = {_json_text(str(catalog_path))}",
        "approval_policy = \"never\"",
        "sandbox_mode = \"read-only\"",
        f"[model_providers.mock_provider]\nname = \"Local mock provider\"\nbase_url = {_json_text(mock.base_url)}\nwire_api = \"responses\"\nrequest_max_retries = 0\nstream_max_retries = 0\nsupports_websockets = false\nrequires_openai_auth = false",
        "[features.multi_agent_v2]\nenabled = true\nsubagent_developer_instructions = \"" + DEFAULT_CHILD_SENTINEL + "\"",
    ]
    for role in ("implementer", "reviewer", "investigator"):
        name = f"thaliris-{role}"
        rows.append(f"[agents.{name}]\ndescription = {_json_text('synthetic native profile for runtime evidence')}\nconfig_file = {_json_text('./' + name + '.toml')}")
    (home / "config.toml").write_text("\n\n".join(rows) + "\n", encoding="utf-8")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _select_request(requests: list[CapturedRequest], marker: str, *, exclude: tuple[str, ...] = ()) -> CapturedRequest:
    selected = [
        request for request in requests
        if marker in _request_text(request.body) and not any(excluded in _request_text(request.body) for excluded in exclude)
    ]
    if not selected:
        raise VerificationError(f"no captured Responses request contained expected task marker {marker}")
    return selected[0]


def _verify_catalog_patch(raw: bytes, patched: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    original = json.loads(raw)
    updated = json.loads(patched)
    original_by_slug = {item["slug"]: item for item in original["models"]}
    updated_by_slug = {item["slug"]: item for item in updated["models"]}
    _expect(original_by_slug.keys() == updated_by_slug.keys(), "strict catalog patch changed model identities")
    exact_changed = 0
    for slug, before in original_by_slug.items():
        after = updated_by_slug[slug]
        before_template = (before.get("model_messages") or {}).get("instructions_template")
        after_template = (after.get("model_messages") or {}).get("instructions_template")
        if before_template is not None:
            expected = before_template
            if model_catalog_config.TARGET in expected:
                exact_changed += 1
                lines = before_template.splitlines(keepends=True)
                exact_lines = [line for line in lines if line.rstrip("\r\n") == model_catalog_config.TARGET]
                _expect(len(exact_lines) == 1, f"bundled catalog template contains an embedded or duplicated target for {slug}")
                expected = "".join(line for line in lines if line != exact_lines[0])
            _expect(after_template == expected, f"catalog patch changed non-target template bytes for {slug}")
            _expect(model_catalog_config.TARGET not in (after_template or ""), f"patched model template retained the exact managed sentence for {slug}")
            before_messages = dict(before.get("model_messages") or {})
            after_messages = dict(after.get("model_messages") or {})
            before_messages.pop("instructions_template", None)
            after_messages.pop("instructions_template", None)
            _expect(before_messages == after_messages, f"catalog patch changed non-template message fields for {slug}")
        left = dict(before)
        right = dict(after)
        left.pop("model_messages", None)
        right.pop("model_messages", None)
        _expect(left == right, f"catalog patch changed non-instruction model fields for {slug}")
    _expect(exact_changed > 0, "bundled catalog had no exact managed template line to patch")
    return original, updated


def _turn_params(start_result: dict[str, Any], *, name: str) -> dict[str, Any]:
    thread = start_result.get("thread")
    thread_id = thread.get("id") if isinstance(thread, dict) else None
    if not isinstance(thread_id, str):
        raise VerificationError(f"{name} thread/start did not return a thread id")
    return {"threadId": thread_id, "id": thread_id}


def run_verification(*, patched_catalog_enabled: bool = True) -> dict[str, Any]:
    executable, cli_version = _find_codex()
    with tempfile.TemporaryDirectory(prefix="thaliris-model-catalog-runtime-") as scratch_text:
        scratch = Path(scratch_text).resolve()
        home = scratch / "home"
        project = scratch / "project"
        home.mkdir()
        project.mkdir()
        (project / "AGENTS.md").write_text(AGENTS_SENTINEL + "\n", encoding="utf-8")
        env = _isolated_env(home, scratch)

        export = subprocess.run(
            [str(executable), "debug", "models", "--bundled"],
            cwd=str(project), env=env, capture_output=True, timeout=35, check=False,
        )
        if export.returncode != 0:
            raise VerificationError("installed CLI bundled catalog export failed: " + export.stderr.decode("utf-8", "replace")[-1200:])
        patched, patch_status = model_catalog_config.patch_catalog(
            export.stdout, cli_version=cli_version, source="bundled"
        )
        _expect(patched is not None and patch_status.get("status") == "COMPATIBLE", "strict patch did not accept the installed CLI bundle")
        original_catalog, patched_catalog = _verify_catalog_patch(export.stdout, patched)
        catalog_path = home / model_catalog_config.NAME
        catalog_path.write_bytes(patched if patched_catalog_enabled else export.stdout)
        available = {model.get("slug") for model in patched_catalog["models"]}
        route_models = {
            "implementer": roles.ROLE_MODEL_ROUTING_DEFAULTS["implementer"],
            "reviewer": roles.ROLE_MODEL_ROUTING_DEFAULTS["reviewer"],
            "investigator": roles.ROLE_MODEL_ROUTING_DEFAULTS["investigator"],
        }
        for role, (model, _effort) in route_models.items():
            _expect(model in available, f"selected {role} model is absent from the installed bundled catalog: {model}")

        profiles: dict[str, str] = {}
        for role in ("implementer", "reviewer", "investigator"):
            _path, profile_instructions = _prepare_native_profile(home, role)
            profiles[role] = profile_instructions

        mock = ResponsesMock()
        outbound_deny_proxy = OutboundDenyProxy()
        outbound_deny_proxy.install_in(env)
        server: AppServer | None = None
        try:
            _write_home_config(home, mock, catalog_path)
            health_opener = build_opener(ProxyHandler({}))
            with health_opener.open(mock.base_url.removesuffix("/v1") + "/health", timeout=3) as health:
                _expect(health.read() == b"ok", "local Responses mock failed its loopback health preflight")
            server = AppServer(executable, home, project, env)
            effective_config = server.request("config/read", {"cwd": str(project), "includeLayers": True})
            loaded_config = effective_config.get("config") or {}
            provider_name = loaded_config.get("modelProvider", loaded_config.get("model_provider"))
            providers = loaded_config.get("modelProviders") or loaded_config.get("model_providers") or {}
            loaded_provider = providers.get("mock_provider") if isinstance(providers, dict) else None
            loaded_base_url = (loaded_provider or {}).get("baseUrl", (loaded_provider or {}).get("base_url"))
            loaded_catalog = loaded_config.get("modelCatalogJson", loaded_config.get("model_catalog_json"))
            _expect(provider_name == "mock_provider", "app-server config/read did not load the isolated mock provider selection")
            _expect(loaded_base_url == mock.base_url, "app-server config/read did not load the loopback Responses endpoint")
            _expect(isinstance(loaded_catalog, str) and Path(loaded_catalog).resolve() == catalog_path.resolve(), "app-server config/read did not load the patched model_catalog_json path")
            root_guidance = controller_instructions.delivered_resident("<installed pinned runner>")
            _expect("<!-- THALIRIS CONTROLLER GUIDANCE END sha256=" in root_guidance, "resident Controller guidance lacks its complete digest marker")
            root_developer = root_guidance + "\n" + ROOT_DEVELOPER_SENTINEL
            started = server.request("thread/start", {
                "model": "gpt-6-luna",
                "modelProvider": "mock_provider",
                "cwd": str(project),
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "developerInstructions": root_developer,
            })
            root_thread = _turn_params(started, name="Controller")
            try:
                server.start_turn(root_thread["threadId"], ROOT_PROMPT, model="gpt-6.1-sol", effort="high")
            except VerificationError as exc:
                if not mock.snapshot() and "connection failure" in str(exc).lower():
                    provider = started.get("modelProvider")
                    loaded_summary = {
                        "selected_provider": provider_name,
                        "thread_start_provider": provider,
                        "mock_base_url": loaded_base_url,
                        "wire_api": (loaded_provider or {}).get("wireApi", (loaded_provider or {}).get("wire_api")),
                        "catalog_loaded": isinstance(loaded_catalog, str) and Path(loaded_catalog).resolve() == catalog_path.resolve(),
                        "turn_selection": {"model": "gpt-6.1-sol", "effort": "high"},
                        "expected_responses_path": "/responses",
                        "captured_json_requests": len(mock.snapshot()),
                    }
                    raise RuntimeUnknownError(
                        "native request capture is UNKNOWN: the installed app-server loaded and started "
                        "the isolated mock provider, but its first Responses request failed before the "
                        f"local mock captured JSON; transport={exc}; loaded={loaded_summary}; "
                        f"outbound_proxy_denials={len(outbound_deny_proxy.destinations)}"
                    ) from exc
                request_facts = [
                    {"path": item.path, "model": item.body.get("model"), "text_markers": [marker for marker in (ROOT_PROMPT, IMPLEMENTER_PROMPT, REVIEWER_PROMPT, SCANNER_PROMPT) if marker in _request_text(item.body)]}
                    for item in mock.snapshot()
                ]
                loaded_config = effective_config.get("config") or {}
                provider_map = loaded_config.get("modelProviders") or loaded_config.get("model_providers") or {}
                loaded_provider = provider_map.get("mock_provider") if isinstance(provider_map, dict) else None
                safe_provider = {key: value for key, value in (loaded_provider or {}).items() if key in {"name", "baseUrl", "base_url", "wireApi", "wire_api", "requiresOpenaiAuth", "requires_openai_auth", "supportsWebsockets", "supports_websockets"}}
                loaded_summary = {"keys": list(loaded_config)[:60], "modelProvider": loaded_config.get("modelProvider", loaded_config.get("model_provider")), "model": loaded_config.get("model"), "model_catalog_json": bool(loaded_config.get("modelCatalogJson", loaded_config.get("model_catalog_json"))), "provider_keys": list(provider_map)[:12] if isinstance(provider_map, dict) else [], "provider": safe_provider}
                raise VerificationError(f"{exc}; thread_start_provider={started.get('modelProvider')}; loaded_config={loaded_summary}; mock_base={mock.base_url}; mock_requests={request_facts}") from exc
            first_requests = mock.wait_for_markers((ROOT_PROMPT, IMPLEMENTER_PROMPT, REVIEWER_PROMPT, SCANNER_PROMPT))

            root_request = _select_request(first_requests, ROOT_PROMPT, exclude=(ROOT_IMPLEMENTER_CALL,))
            root_body = root_request.body
            root_developers = _developer_texts(root_body)
            _expect(root_body.get("model") == "gpt-6.1-sol", "Controller model-switch request used the wrong selected model")
            _expect((root_body.get("reasoning") or {}).get("effort") == "high", "Controller model-switch request lost the selected effort")
            _expect(any(ROOT_DEVELOPER_SENTINEL in text for text in root_developers), "Controller developer instructions were not present in the actual Responses request")
            _expect(AGENTS_SENTINEL in _request_text(root_body), "project AGENTS.md was absent from the actual Controller request")
            _expect(any("THALIRIS CONTROLLER GUIDANCE END sha256=" in text and "## Thaliris owning Controller" in text for text in root_developers), "rendered bootstrap guidance was not present in the actual Controller request")
            _expect(any("<model_switch>" in text for text in root_developers), "native model-switch developer message was absent")
            switched = next(text for text in root_developers if "<model_switch>" in text)
            _expect((model_catalog_config.TARGET in switched) is not patched_catalog_enabled, "model-switch template did not reflect the selected baseline or patched catalog")
            target_template = patched_catalog["models"][[m.get("slug") for m in patched_catalog["models"]].index("gpt-6.1-sol")]["model_messages"]["instructions_template"]
            stable_template_lines = [line.strip() for line in target_template.splitlines() if len(line.strip()) >= 44 and "{{" not in line and "}}" not in line]
            _expect(bool(stable_template_lines), "selected model catalog template has no stable rendered-text evidence")
            matched_template_lines = sum(line in switched for line in stable_template_lines)
            _expect(matched_template_lines >= min(3, len(stable_template_lines)), "model-switch developer message did not carry the selected catalog template")

            implementer_request = _select_request(first_requests, IMPLEMENTER_PROMPT, exclude=(ROOT_IMPLEMENTER_CALL,))
            reviewer_request = _select_request(first_requests, REVIEWER_PROMPT, exclude=(ROOT_REVIEWER_CALL,))
            scanner_request = _select_request(first_requests, SCANNER_PROMPT, exclude=(NESTED_SCANNER_CALL,))
            for role, request, prompt_marker, forbidden_markers in (
                ("implementer", implementer_request, IMPLEMENTER_PROMPT, (ROOT_PROMPT, ROOT_DEVELOPER_SENTINEL, DEFAULT_CHILD_SENTINEL)),
                ("reviewer", reviewer_request, REVIEWER_PROMPT, (ROOT_PROMPT, ROOT_DEVELOPER_SENTINEL, DEFAULT_CHILD_SENTINEL)),
                ("investigator", scanner_request, SCANNER_PROMPT, (ROOT_PROMPT, IMPLEMENTER_PROMPT, ROOT_DEVELOPER_SENTINEL, DEFAULT_CHILD_SENTINEL)),
            ):
                expected_model, expected_effort = route_models[role]
                body = request.body
                _expect(body.get("model") == expected_model, f"native {role} child request did not use routed model {expected_model}")
                _expect((body.get("reasoning") or {}).get("effort") == expected_effort, f"native {role} child request did not use routed effort {expected_effort}")
                dev_texts = _developer_texts(body)
                _expect(any(text == profiles[role] for text in dev_texts), f"native {role} profile developer instructions did not reach the actual child request")
                flat = _request_text(body)
                _expect(prompt_marker in flat, f"native {role} child task input was not captured")
                _expect(all(marker not in flat for marker in forbidden_markers), f"fresh {role} child inherited parent or default developer/history content")
                _expect(request.thread_id is not None, f"native {role} request omitted thread-id needed for lifecycle checks")

            _expect(all(request.body.get("model") in available for request in first_requests), "captured local request used a model outside the isolated patched catalog")

            # Fork a completed Controller thread without an override and prove
            # that its developer/bootstrap instructions remain in the request.
            preserve_fork = server.request("thread/fork", {"threadId": root_thread["threadId"]})
            preserve_thread = _turn_params(preserve_fork, name="instruction-preserving fork")
            server.start_turn(preserve_thread["threadId"], FORK_PRESERVE_PROMPT)
            preserve_request = _select_request(mock.snapshot(), FORK_PRESERVE_PROMPT)
            preserve_developers = _developer_texts(preserve_request.body)
            _expect(any(ROOT_DEVELOPER_SENTINEL in text for text in preserve_developers), "fork without override did not preserve Controller developer instructions")
            _expect(any("THALIRIS CONTROLLER GUIDANCE END sha256=" in text for text in preserve_developers), "fork without override lost bootstrap guidance")

            # Fork a persisted thread with an explicit developer override.
            # The installed runtime cannot fork a thread with no rollout yet.
            override_source = server.request("thread/start", {
                "model": "gpt-6.1-sol",
                "modelProvider": "mock_provider",
                "cwd": str(project),
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "developerInstructions": ROOT_DEVELOPER_SENTINEL,
            })
            override_source_thread = _turn_params(override_source, name="fork override source")
            server.start_turn(override_source_thread["threadId"], FORK_SOURCE_PROMPT)
            override_fork = server.request("thread/fork", {
                "threadId": override_source_thread["threadId"],
                "developerInstructions": FORK_OVERRIDE_SENTINEL,
            })
            override_thread = _turn_params(override_fork, name="instruction-overriding fork")
            server.start_turn(override_thread["threadId"], FORK_OVERRIDE_PROMPT)
            override_request = _select_request(mock.snapshot(), FORK_OVERRIDE_PROMPT)
            override_developers = _developer_texts(override_request.body)
            fork_override_delivered = any(FORK_OVERRIDE_SENTINEL in text for text in override_developers)
            fork_original_preserved = any(ROOT_DEVELOPER_SENTINEL in text for text in override_developers)
            _expect(fork_override_delivered or fork_original_preserved, "fork lost both original and requested developer instructions")

            # Reattaching a loaded native child with a direct instruction
            # value must leave its persisted instruction contract unchanged.
            child_id = implementer_request.thread_id
            attached_child = server.request("thread/resume", {
                "threadId": child_id,
                "excludeTurns": True,
                "modelProvider": "mock_provider",
                "developerInstructions": RESUME_OVERRIDE_SENTINEL,
            })
            _expect(attached_child.get("thread", {}).get("canAcceptDirectInput") is False, "attached child lost its owner-mediated input boundary")
            try:
                server.start_turn(child_id, DIRECT_CHILD_RESUME_PROMPT)
            except VerificationError as exc:
                _expect("direct app-server input is not allowed for multi-agent v2 sub-agents" in str(exc), "direct child input failed for an unexpected reason")
            else:
                raise VerificationError("native owner-mediated child incorrectly accepted direct app-server input")
            server.start_turn(root_thread["threadId"], PARENT_ATTACHMENT_PROMPT)
            mock.wait_for_markers((DIRECT_CHILD_RESUME_PROMPT,))
            direct_resume_request = _select_request(mock.snapshot(), DIRECT_CHILD_RESUME_PROMPT, exclude=(PARENT_ATTACHMENT_CALL,))
            direct_resume_body = direct_resume_request.body
            _expect(direct_resume_body.get("model") == route_models["implementer"][0], "directly resumed child changed its routed model")
            _expect((direct_resume_body.get("reasoning") or {}).get("effort") == route_models["implementer"][1], "directly resumed child changed its routed effort")
            direct_resume_developers = _developer_texts(direct_resume_body)
            _expect(any(text == profiles["implementer"] for text in direct_resume_developers), "direct child resume replaced persisted role developer instructions")
            _expect(all(RESUME_OVERRIDE_SENTINEL not in text for text in direct_resume_developers), "direct child resume override leaked into the actual resumed request")

            # A cold parent resume owns child reentry. Update the scratch role
            # profile and observe whether the native replay path delivers it.
            # Retained original instructions are reported as a native limit,
            # with baseline/managed catalog parity checked by main().
            parent_id = root_thread["threadId"]
            server.close()
            server = None
            import tomllib

            profile_path = home / "thaliris-implementer.toml"
            profile_value = tomllib.loads(profile_path.read_text(encoding="utf-8"))
            profile_value["developer_instructions"] += "\n\n" + RESUMED_ROLE_SENTINEL
            profile_bytes = (
                f"name = {_json_text(profile_value['name'])}\n"
                f"description = {_json_text(profile_value['description'])}\n"
                f"developer_instructions = {_json_text(profile_value['developer_instructions'])}\n"
            ).encode("utf-8")
            profile_path.write_bytes(profile_bytes)

            server = AppServer(executable, home, project, env)
            resumed_parent = server.request("thread/resume", {"threadId": parent_id})
            resumed_id = resumed_parent.get("thread", {}).get("id")
            _expect(resumed_id == parent_id, "cold parent resume returned a different thread identity")
            server.start_turn(parent_id, PARENT_RESUME_PROMPT)
            mock.wait_for_markers((IMPLEMENTER_FOLLOWUP,))
            resumed_child = _select_request(mock.snapshot(), IMPLEMENTER_FOLLOWUP, exclude=(PARENT_FOLLOWUP_CALL,))
            resumed_body = resumed_child.body
            _expect(resumed_body.get("model") == route_models["implementer"][0], "resumed implementer changed routed model")
            _expect((resumed_body.get("reasoning") or {}).get("effort") == route_models["implementer"][1], "resumed implementer changed routed effort")
            resumed_developers = _developer_texts(resumed_body)
            resumed_current_profile_delivered = any(RESUMED_ROLE_SENTINEL in text for text in resumed_developers)
            resumed_original_profile_preserved = any(text == profiles["implementer"] for text in resumed_developers)
            _expect(resumed_current_profile_delivered or resumed_original_profile_preserved, "cold resumed child lost both original and current role developer instructions")
            _expect(all(marker not in _request_text(resumed_body) for marker in (ROOT_DEVELOPER_SENTINEL, RESUME_OVERRIDE_SENTINEL)), "fresh resumed task inherited parent or direct-resume override text")
            _expect(all(request.body.get("model") in available for request in mock.snapshot()), "captured local request used a model outside the isolated patched catalog")

            all_requests = mock.snapshot()
            return {
                "status": "PASS",
                "acceptance_scope": "catalog instruction regression; native delivery limitations are reported separately",
                "cli_version": cli_version,
                "cli_path_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "catalog_source": "installed CLI debug models --bundled",
                "catalog_variant": "managed" if patched_catalog_enabled else "unpatched baseline",
                "catalog_models": len(original_catalog["models"]),
                "catalog_patched_templates": patch_status.get("patched_templates"),
                "model_catalog_json_loaded": True,
                "local_responses_requests": len(all_requests),
                "denied_background_requests": len(outbound_deny_proxy.destinations),
                "external_model_requests": 0,
                "captured_roles": {
                    "Controller": {"model": root_body.get("model"), "effort": (root_body.get("reasoning") or {}).get("effort"), "bootstrap_guidance": True, "developer_sentinel": True, "project_agents": True, "model_switch_template_lines": matched_template_lines},
                    "Implementer": {"model": implementer_request.body.get("model"), "effort": (implementer_request.body.get("reasoning") or {}).get("effort"), "fresh": True, "native_profile_developer": True},
                    "Reviewer": {"model": reviewer_request.body.get("model"), "effort": (reviewer_request.body.get("reasoning") or {}).get("effort"), "fresh": True, "native_profile_developer": True},
                    "nested Investigator Scanner": {"model": scanner_request.body.get("model"), "effort": (scanner_request.body.get("reasoning") or {}).get("effort"), "fresh": True, "native_profile_developer": True},
                    "cold resumed Implementer": {"model": resumed_body.get("model"), "effort": (resumed_body.get("reasoning") or {}).get("effort"), "current_role_profile": resumed_current_profile_delivered, "original_role_profile_preserved": resumed_original_profile_preserved},
                },
                "fork_resume": {"preserved_parent_instructions": True, "explicit_fork_override": fork_override_delivered, "fork_original_instructions_preserved": fork_original_preserved, "direct_child_resume_override_ignored": True, "direct_child_input_rejected": True, "cold_parent_resume_reentered_child": True},
                "request_evidence": [
                    {"phase": phase, "body_sha256": hashlib.sha256(json.dumps(request.body, sort_keys=True).encode()).hexdigest(), "model": request.body.get("model"), "effort": (request.body.get("reasoning") or {}).get("effort"), "developer_markers": {marker: any(marker in text for text in _developer_texts(request.body)) for marker in (ROOT_DEVELOPER_SENTINEL, FORK_OVERRIDE_SENTINEL, RESUME_OVERRIDE_SENTINEL, RESUMED_ROLE_SENTINEL)}}
                    for phase, request in (("Controller", root_request), ("Implementer", implementer_request), ("Reviewer", reviewer_request), ("nested Scanner", scanner_request), ("fork preserve", preserve_request), ("fork override", override_request), ("attached child via parent", direct_resume_request), ("cold resumed child", resumed_child))
                ],
                "authorization_header_seen": any(item.authorization_present for item in all_requests),
            }
        finally:
            if server is not None:
                server.close()
            mock.close()
            outbound_deny_proxy.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print a machine-readable result")
    parser.parse_args(argv)
    try:
        baseline = run_verification(patched_catalog_enabled=False)
        result = run_verification()
        # Native fork/cold-resume injection can retain replayed instructions.
        # Compare actual requests on both catalogs; never label an unsupported
        # injection as successful merely because regression parity passes.
        _expect(result["fork_resume"] == baseline["fork_resume"], "managed catalog changed native fork/resume behavior")
        for role, current in result["captured_roles"].items():
            prior = baseline["captured_roles"][role]
            _expect({k: v for k, v in current.items() if k != "model_switch_template_lines"} == {k: v for k, v in prior.items() if k != "model_switch_template_lines"}, f"managed catalog changed captured {role} routing/instructions")
        baseline_phases = {item["phase"]: item for item in baseline["request_evidence"]}
        for current in result["request_evidence"]:
            prior = baseline_phases[current["phase"]]
            _expect({k: v for k, v in current.items() if k != "body_sha256"} == {k: v for k, v in prior.items() if k != "body_sha256"}, f"managed catalog changed actual request evidence for {current['phase']}")
        result["baseline_request_evidence"] = baseline["request_evidence"]
        result["baseline_local_responses_requests"] = baseline["local_responses_requests"]
        result["native_catalog_parity"] = True
        result["native_delivery_limitations"] = {
            "explicit_fork_override": "PASS" if result["fork_resume"]["explicit_fork_override"] else "NATIVE_LIMITATION",
            "cold_resume_updated_role_profile": "PASS" if result["captured_roles"]["cold resumed Implementer"]["current_role_profile"] else "NATIVE_LIMITATION",
        }
    except RuntimeUnknownError as exc:
        print(json.dumps({"status": "UNKNOWN", "reason": str(exc)}, indent=2), file=sys.stdout)
        return 2
    except Exception as exc:
        error = {"status": "FAIL", "error": str(exc)}
        print(json.dumps(error, indent=2), file=sys.stdout)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
