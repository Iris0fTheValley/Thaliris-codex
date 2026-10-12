"""Isolated, no-model-service checks for the two optional prompt config leaves.

Version evidence is a fast path only. Unknown builds must demonstrate the same
string typing and prompt effect using a disposable CLI and loopback Responses
sink. This proves CLI configuration behavior, never live Desktop activation.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid


def capability(field: str, verified_versions: frozenset[str]) -> str:
    executable = shutil.which("codex")
    if executable is None:
        return "UNKNOWN"
    try:
        result = subprocess.run([executable, "--version"], capture_output=True,
                                text=True, timeout=10, check=False)
        if result.returncode != 0:
            return "UNKNOWN"
        if result.stdout.strip() in verified_versions:
            return "SUPPORTED"
        return probe(executable, field)
    except (OSError, subprocess.SubprocessError, ValueError):
        return "UNKNOWN"


def _developer_text(body: dict) -> str:
    texts = []
    for item in body.get("input", []):
        if not isinstance(item, dict) or item.get("role") != "developer":
            continue
        content = item.get("content", [])
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(part["text"] for part in content if isinstance(part, dict)
                         and isinstance(part.get("text"), str))
    return "\n".join(texts)


def _windows_program_data_dir() -> Path:
    """Resolve the real ProgramData known folder, never the environment value."""
    if sys.platform != "win32":
        raise OSError("ProgramData known-folder lookup is only available on Windows")
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    folder_id = GUID(0x62AB5D82, 0xFDC1, 0x4DC3,
                     (ctypes.c_ubyte * 8)(0xA9, 0xDD, 0x07, 0x0D,
                                          0x1D, 0x49, 0x5D, 0x97))
    path = ctypes.POINTER(ctypes.c_wchar)()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                                             wintypes.HANDLE,
                                             ctypes.POINTER(ctypes.POINTER(ctypes.c_wchar))]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None,
                                          ctypes.byref(path))
    free = ctypes.WinDLL("ole32").CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    if result != 0 or not path:
        if path:
            free(ctypes.cast(path, ctypes.c_void_p))
        raise OSError(f"SHGetKnownFolderPath(FOLDERID_ProgramData) failed: {result:#x}")
    try:
        return Path(ctypes.wstring_at(path))
    finally:
        free(ctypes.cast(path, ctypes.c_void_p))


def _system_config_paths() -> tuple[Path, ...] | None:
    """Return every locally documented system layer, or None if unknown."""
    if sys.platform == "win32":
        root = _windows_program_data_dir() / "OpenAI" / "Codex"
        return (root / "config.toml", root / "requirements.toml")
    if sys.platform.startswith("linux"):
        root = Path("/etc/codex")
        return (root / "config.toml", root / "requirements.toml",
                root / "managed_config.toml")
    # Codex also supports macOS managed preferences. Their absence is not
    # observable here, so no CLI process may start the capability probe.
    return None


def _system_config_is_absent() -> bool:
    """Prove local system config layers are absent without reading their bytes."""
    try:
        paths = _system_config_paths()
        if paths is None:
            return False
        for path in paths:
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                return False
            else:
                return False
        return True
    except (OSError, ValueError, TypeError):
        return False


class _Sink:
    """Serve synthetic completion only; deny every other HTTP/proxy request."""

    def __init__(self):
        self.requests: list[dict] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/v1/responses":
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4 * 1024 * 1024:
                        raise ValueError("unexpected body length")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("unexpected request")
                except (ValueError, OSError):
                    self.send_error(400)
                    return
                owner.requests.append(body)
                # A synthetic text completion cannot dispatch tools.
                item = {"id": "probe_message", "type": "message", "status": "completed",
                        "role": "assistant", "content": [{"type": "output_text",
                        "text": "config probe complete", "annotations": []}]}
                events = [
                    ("response.created", {"response": {"id": "config_probe", "status": "in_progress"}}),
                    ("response.output_item.added", {"output_index": 0, "item": {
                        "id": "probe_message", "type": "message", "role": "assistant", "content": []}}),
                    ("response.output_text.delta", {"item_id": "probe_message", "output_index": 0,
                        "content_index": 0, "delta": "config probe complete"}),
                    ("response.output_item.done", {"output_index": 0, "item": item}),
                    ("response.completed", {"response": {"id": "config_probe",
                        "status": "completed", "output": [item]}}),
                ]
                payload = ("".join("event: " + kind + "\ndata: " + json.dumps({"type": kind, **data})
                                   + "\n\n" for kind, data in events) + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def deny(self):
                self.send_error(403, "non-loopback traffic disabled")

            do_CONNECT = deny
            do_GET = deny
            do_PUT = deny
            do_DELETE = deny

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def _run(executable: str, root: Path, sink: _Sink, field: str, value: object,
         task: str, developer: str) -> tuple[subprocess.CompletedProcess, list[dict]]:
    home = root / uuid.uuid4().hex
    home.mkdir()
    cwd = home / "workspace"
    cwd.mkdir()
    (cwd / ".thaliris-config-probe").touch()
    encoded = json.dumps(value)
    lines = [
        'model = "gpt-5.1-codex"',
        'model_provider = "config_probe"',
        'approval_policy = "never"',
        'sandbox_mode = "read-only"',
        'project_doc_max_bytes = 0',
        'project_root_markers = [".thaliris-config-probe"]',
        f'developer_instructions = {encoded if field == "developer_instructions" else json.dumps(developer)}',
        '[model_providers.config_probe]',
        'name = "Local config capability probe"',
        f'base_url = "{sink.url}/v1"',
        'wire_api = "responses"',
        'requires_openai_auth = false',
        'request_max_retries = 0',
        'stream_max_retries = 0',
        'supports_websockets = false',
    ]
    if field == "multi_agent_mode_hint_text":
        lines += ['[features.multi_agent_v2]', 'enabled = true',
                  f'multi_agent_mode_hint_text = {encoded}']
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Never copy authentication or user/project configuration into the probe.
    runtime_keys = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                    "SYSTEMDRIVE", "PROCESSOR_ARCHITECTURE"}
    env = {key: val for key, val in os.environ.items() if key.upper() in runtime_keys}
    env["CODEX_HOME"] = str(home)
    env["HOME"] = env["USERPROFILE"] = str(home)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[name] = env[name.lower()] = sink.url
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1"
    start = len(sink.requests)
    result = subprocess.run(
        [executable, "exec", "--disable", "hooks", "--disable", "plugins",
         "--skip-git-repo-check", "--json", task],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    return result, sink.requests[start:]


def probe(executable: str, field: str) -> str:
    """Check accepted string, empty-string effect, and rejection of a wrong type.

    Completed captured requests with a contradictory effect are INCOMPATIBLE.
    Missing transport/effect evidence or ambiguous failures remain UNKNOWN.
    """
    if field not in {"multi_agent_mode_hint_text", "developer_instructions"}:
        raise ValueError("unknown optional config capability")
    # A fresh CODEX_HOME does not override system requirements/config layers.
    # Refuse the probe when their absence cannot be proven; hooks from managed
    # policy remain effective even when ordinary hooks are disabled below.
    if not _system_config_is_absent():
        return "UNKNOWN"
    sink = _Sink()
    sentinel = "CONFIG_CAPABILITY_" + uuid.uuid4().hex
    developer = "CONFIG_DEVELOPER_" + uuid.uuid4().hex
    task = "Return config probe complete and call no tools. CONFIG_TASK_" + uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix="thaliris-config-capability-") as directory:
            root = Path(directory)
            for value in (sentinel, "", 123):
                result, requests = _run(executable, root, sink, field, value, task, developer)
                if type(value) is int:
                    if requests:
                        return "INCOMPATIBLE"
                    diagnostic = result.stderr + result.stdout
                    type_error = re.search(
                        r"invalid type:\s*integer\b.*?expected\s+(?:a\s+)?string\b",
                        diagnostic, re.IGNORECASE | re.DOTALL,
                    )
                    if result.returncode != 0 and field in diagnostic and type_error is not None:
                        return "SUPPORTED"
                    return "UNKNOWN"
                if result.returncode != 0 or len(requests) != 1:
                    return "UNKNOWN"
                body = requests[0]
                # A tool/model response or another request cannot stand in for
                # the one finite task we asked this disposable CLI to execute.
                if task not in json.dumps(body.get("input", [])):
                    return "UNKNOWN"
                text = _developer_text(body)
                if field == "multi_agent_mode_hint_text":
                    expected = rf"<multi_agent_mode>\s*{sentinel}\s*</multi_agent_mode>"
                    if developer not in text:
                        return "UNKNOWN"
                    if value and re.search(expected, text) is None:
                        return "INCOMPATIBLE"
                    if not value and ("<multi_agent_mode>" in text or sentinel in text):
                        return "INCOMPATIBLE"
                elif (bool(value) and sentinel not in text) or (not value and sentinel in text):
                    return "INCOMPATIBLE"
        return "UNKNOWN"
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return "UNKNOWN"
    finally:
        sink.close()
