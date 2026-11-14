"""Isolated, no-model-service checks for the two optional prompt config leaves.

Support is never decided by a version string. The resolved Codex binary must
demonstrate string typing and prompt effect using a disposable CLI and a
loopback Responses sink. A definitive result is cached for exactly that binary
(SHA-256), config leaf and probe contract; a changed binary is probed again and
an UNKNOWN result is never cached. This proves CLI configuration behavior,
never live Desktop activation.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

CACHE_FORMAT = "thaliris-config-capability-v1"
FIELDS = frozenset({"multi_agent_mode_hint_text", "developer_instructions"})
_KEY_PATHS = {
    "multi_agent_mode_hint_text": "features.multi_agent_v2.multi_agent_mode_hint_text",
    "developer_instructions": "developer_instructions",
}
# A launcher script's bytes do not identify the Host binary it starts.
LAUNCHER_SUFFIXES = frozenset({".cmd", ".bat", ".ps1", ".sh", ".py", ".js"})
_CACHEABLE = frozenset({"SUPPORTED", "INCOMPATIBLE"})


def resolve_executable() -> str | None:
    """Select the Codex CLI exactly as the adapter's provenance path does."""
    configured = os.environ.get("THALIRIS_CODEX_EXECUTABLE")
    if configured:
        return shutil.which(configured) or configured
    return shutil.which("codex")


def binary_sha256(executable: str) -> str | None:
    """Hash a direct binary; launcher scripts and unreadable paths stay unknown."""
    path = Path(executable)
    if path.suffix.lower() in LAUNCHER_SUFFIXES:
        return None
    try:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            head = stream.read(2)
            if head == b"#!":
                return None
            digest.update(head)
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def cache_directory() -> Path:
    """Host-scoped adapter state, never a user project or the Codex home."""
    return Path.home() / ".thaliris" / "host-capability"


def _probe_contract() -> str | None:
    """Bind cached results to the evidence rules that produced them."""
    try:
        source = "".join(inspect.getsource(item) for item in (
            probe, _run, _Sink, _developer_text, _misattributed))
    except (OSError, TypeError):
        return None
    return hashlib.sha256((CACHE_FORMAT + "\n" + source).encode("utf-8")).hexdigest()


def _cache_path(binary: str, field: str, contract: str) -> Path:
    key = hashlib.sha256(json.dumps([CACHE_FORMAT, binary, field, contract]).encode()).hexdigest()
    return cache_directory().absolute() / f"{key}.json"


def _cached(binary: str, field: str, contract: str) -> str | None:
    from .host_maintenance import safe
    try:
        path = _cache_path(binary, field, contract)
        safe(path)
        if not path.is_file():
            return None
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, TypeError):
        return None
    if (not isinstance(value, dict)
            or set(value) != {"format", "cli_sha256", "field", "probe_contract", "result", "cli_version"}
            or value["format"] != CACHE_FORMAT or value["cli_sha256"] != binary
            or value["field"] != field or value["probe_contract"] != contract
            or value["result"] not in _CACHEABLE or not isinstance(value["cli_version"], str)):
        return None
    return value["result"]


def _store(binary: str, field: str, contract: str, result: str, version: str) -> None:
    """Best effort: a cache failure only costs a later probe."""
    from .host_maintenance import safe
    try:
        path = _cache_path(binary, field, contract)
        safe(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        safe(path)
        temporary = path.with_name(path.name + "." + secrets.token_hex(8))
        body = {"format": CACHE_FORMAT, "cli_sha256": binary, "field": field,
                "probe_contract": contract, "result": result, "cli_version": version}
        with temporary.open("xb") as stream:
            stream.write(json.dumps(body, sort_keys=True).encode("utf-8"))
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        return


def _version_line(executable: str) -> str:
    """Provenance only. A missing or unparseable version never decides support."""
    try:
        result = subprocess.run([executable, "--version"], capture_output=True,
                                text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return "UNKNOWN"
    line = (result.stdout or "").strip()
    if result.returncode != 0 or not line or len(line) > 200 or "\n" in line:
        return "UNKNOWN"
    return line


def cached_capabilities() -> dict[str, dict]:
    """Report cached evidence for the resolved binary without running a probe."""
    executable = resolve_executable()
    binary = binary_sha256(executable) if executable else None
    contract = _probe_contract()
    report = {}
    for field in sorted(FIELDS):
        cached = _cached(binary, field, contract) if binary and contract else None
        report[field] = {"key_path": _KEY_PATHS[field], "status": cached or "UNKNOWN",
                         "evidence": "BINARY_SHA256_PROBE_CACHE" if cached else "NOT_PROBED_FOR_THIS_BINARY",
                         "cli_sha256": binary or "UNKNOWN"}
    return report


def cached_capability(field: str) -> dict:
    if field not in FIELDS:
        raise ValueError("unknown optional config capability")
    return cached_capabilities()[field]


def capability(field: str) -> str:
    """Probe the resolved binary, reusing a result only for identical bytes."""
    if field not in FIELDS:
        raise ValueError("unknown optional config capability")
    executable = resolve_executable()
    if executable is None:
        return "UNKNOWN"
    binary = binary_sha256(executable)
    contract = _probe_contract()
    if binary is not None and contract is not None:
        cached = _cached(binary, field, contract)
        if cached is not None:
            return cached
    version = _version_line(executable)
    result = probe(executable, field)
    # Never attribute a result to bytes that changed while the probe ran.
    if (binary is not None and contract is not None and result in _CACHEABLE
            and binary_sha256(executable) == binary):
        _store(binary, field, contract, result, version)
    return result


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
    # exec appends piped stdin to the prompt and waits for EOF; an inherited
    # open pipe would otherwise hold the probe until its timeout.
    result = subprocess.run(
        [executable, "exec", "--disable", "hooks", "--disable", "plugins",
         "--skip-git-repo-check", "--json", task],
        cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=15, check=False,
    )
    return result, sink.requests[start:]


def _misattributed(diagnostic: str, field: str) -> bool:
    """True when the Host names a config location unrelated to this leaf.

    Error wording is corroboration only. Serde reports the failing location as
    ``in `path``` (for the mode hint, its untagged bool-or-table parent
    ``features.multi_agent_v2``). A failure attributed only elsewhere cannot be
    credited to the leaf under test; no location at all is merely uncorroborated.
    """
    locations = re.findall(r"\bin `([^`\s]+)`", diagnostic)
    if not locations:
        return False
    path = _KEY_PATHS[field]
    return not any(location == path or path.startswith(location + ".")
                   or location.startswith(path + ".") for location in locations)


def probe(executable: str, field: str) -> str:
    """Check accepted string, empty-string effect, and rejection of a wrong type.

    The sentinel and empty-string prompt effects are the positive evidence that
    the leaf is recognised. A wrong-typed integer must then be rejected by
    behaviour: a non-zero exit before any Responses request. The integer run
    differs from the accepted runs only in that leaf, and a final repeat of the
    accepted sentinel run proves the environment still works, so the failure is
    attributable to the leaf's string typing without matching error wording.
    Completed captured requests with a contradictory effect are INCOMPATIBLE.
    Missing transport/effect evidence or ambiguous failures remain UNKNOWN.
    """
    if field not in FIELDS:
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
            rejected = False
            # The trailing sentinel is the control run for the integer case.
            for value in (sentinel, "", 123, sentinel):
                result, requests = _run(executable, root, sink, field, value, task, developer)
                if type(value) is int:
                    if requests:
                        return "INCOMPATIBLE"
                    # Exit 0 without a request shows neither acceptance nor
                    # typed rejection; a failure the Host attributes to an
                    # unrelated location cannot be credited to this leaf.
                    if (result.returncode == 0
                            or _misattributed(result.stderr + result.stdout, field)):
                        return "UNKNOWN"
                    rejected = True
                    continue
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
        return "SUPPORTED" if rejected else "UNKNOWN"
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return "UNKNOWN"
    finally:
        sink.close()
