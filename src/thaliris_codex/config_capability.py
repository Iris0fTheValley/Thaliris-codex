"""Isolated, no-model-service checks for the two optional prompt config leaves.

Support is never decided by a version string. The resolved Codex binary must
demonstrate string typing and prompt effect using a disposable CLI and a
loopback Responses sink. The install and live-write path always probes again
(``capability``); a recorded result only feeds reporting and doctor
(``cached_capabilities``), so a forged cache entry cannot skip a probe before
a live config write. A definitive result is recorded for exactly that binary
(SHA-256), config leaf and probe contract, and only when the hashed bytes
themselves embed the Host's generated hook schemas (never a launcher shim). An
UNKNOWN result, and a SUPPORTED result whose typed rejection the Host did not
corroborate, is never recorded. This proves CLI configuration behavior of one
binary, never live Desktop activation or other Host binaries reading the same
config.
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


def _shim_sibling(path: Path) -> bool:
    """Scoop-style ``<name>.shim`` beside the executable: its bytes only start the Host."""
    try:
        return any(candidate.exists() for candidate in (path.with_suffix(".shim"),
                                                       path.with_name(path.name + ".shim")))
    except (OSError, ValueError):
        return True


def cache_identity(executable: str | None) -> str | None:
    """SHA-256 under which a result may be recorded or reported, or None.

    The digest and the embedded hook schemas come from one mapping of the
    same bytes (``hook_shape.embedded_identity``); a launcher shim or packed
    binary without observable schemas, or any executable with a ``.shim``
    sibling, is not an identity of the Host.
    """
    from . import hook_shape
    if not executable:
        return None
    path = Path(executable)
    if path.suffix.lower() in LAUNCHER_SUFFIXES or _shim_sibling(path):
        return None
    return hook_shape.embedded_identity(executable)[1]


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
    from . import hook_shape
    try:
        source = "".join(inspect.getsource(item) for item in (
            probe, _probe, _run, _Sink, _developer_text, _misattributed, _corroborated,
            _system_config_is_absent, _system_config_paths, _recordable, cache_identity, _shim_sibling,
            hook_shape.embedded_identity, hook_shape._scan))
    except (OSError, TypeError):
        return None
    keys = json.dumps(_KEY_PATHS, sort_keys=True)
    return hashlib.sha256((CACHE_FORMAT + "\n" + keys + "\n" + source).encode("utf-8")).hexdigest()


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
    """Report recorded evidence for the resolved binary without running a probe.

    Reporting and doctor only: no install or live config write consults this.
    """
    executable = resolve_executable()
    binary = cache_identity(executable) if executable else None
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


# The binary the last install-path probe in this process ran against, for the
# install report only; it never stands in for a probe.
_LAST_PROBED: dict[str, str] = {}


def _recordable(identity: str | None, contract: str | None, result: str, corroborated: bool,
                after: str | None) -> bool:
    """Store gate: definitive, Host-identified, unchanged bytes, and corroborated if SUPPORTED."""
    return (identity is not None and contract is not None and result in _CACHEABLE
            and (result != "SUPPORTED" or corroborated) and after == identity)


def capability(field: str) -> str:
    """Probe the resolved binary now; a recorded result never replaces this probe.

    This is the install and live-write path: the result decides whether a live
    config leaf may be written, so it is always a fresh probe of the current
    bytes. A definitive result is then recorded for reporting.
    """
    if field not in FIELDS:
        raise ValueError("unknown optional config capability")
    executable = resolve_executable()
    if executable is None:
        return "UNKNOWN"
    identity = cache_identity(executable)
    contract = _probe_contract()
    version = _version_line(executable)
    result, corroborated = _probe(executable, field)
    _LAST_PROBED.update({"path": executable, "sha256": binary_sha256(executable) or "UNKNOWN",
                         "host_identity_sha256": identity or "UNKNOWN"})
    # Never attribute a result to bytes that changed while the probe ran.
    if _recordable(identity, contract, result, corroborated, cache_identity(executable)):
        _store(identity, field, contract, result, version)
    return result


def install_probe_report() -> dict[str, object]:
    """Name the one binary whose probe authorized config writes, and what stays unknown."""
    probed = dict(_LAST_PROBED)
    return {
        "probed_binary": probed.get("path", "NOT_PROBED"),
        "probed_binary_sha256": probed.get("sha256", "UNKNOWN"),
        "host_identity_sha256": probed.get("host_identity_sha256", "UNKNOWN"),
        "other_host_binaries": "UNKNOWN",
        "note": ("Only the probed binary demonstrated config support. Other Host binaries that read the same"
                 " config.toml (for example Desktop app bundles) were not probed; their support is UNKNOWN."),
    }


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
    """Serve synthetic completion only; deny every other HTTP/proxy request.

    ``contacts`` counts every accepted connection and every request line of any
    method, parsed or not; ``requests`` keeps only parsed Responses bodies.
    """

    def __init__(self):
        self.requests: list[dict] = []
        self.contacts = 0
        lock = threading.Lock()
        owner = self

        def contact():
            with lock:
                owner.contacts += 1

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                contact()
                super().setup()

            def parse_request(self):
                contact()
                return super().parse_request()

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
         task: str, developer: str) -> tuple[subprocess.CompletedProcess, list[dict], int]:
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
    contacts = sink.contacts
    # exec appends piped stdin to the prompt and waits for EOF; an inherited
    # open pipe would otherwise hold the probe until its timeout.
    result = subprocess.run(
        [executable, "exec", "--disable", "hooks", "--disable", "plugins",
         "--skip-git-repo-check", "--json", task],
        cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=15, check=False,
    )
    return result, sink.requests[start:], sink.contacts - contacts


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


def _corroborated(diagnostic: str, field: str) -> bool:
    """True when the Host's own diagnostic names the leaf or its config location."""
    path = _KEY_PATHS[field]
    if path in diagnostic or path.rsplit(".", 1)[-1] in diagnostic:
        return True
    locations = re.findall(r"\bin `([^`\s]+)`", diagnostic)
    return any(location == path or path.startswith(location + ".") for location in locations)


def probe(executable: str, field: str) -> str:
    """Probe result only; see ``_probe``."""
    return _probe(executable, field)[0]


def _probe(executable: str, field: str) -> tuple[str, bool]:
    """Check accepted string, empty-string effect, and rejection of a wrong type.

    Returns the result and whether a SUPPORTED result is corroborated (and so
    may be recorded). The sentinel and empty-string prompt effects are the
    positive evidence that the leaf is recognised. A wrong-typed integer must
    then be rejected by behaviour: a non-zero exit with no sink contact at all
    (no connection, no request of any kind). The integer run differs from the
    accepted runs only in that leaf, and a final repeat of the accepted
    sentinel run proves the environment still works. When the Host's
    diagnostic does not name the leaf or its location, a second, independent
    integer rejection run is required, and the SUPPORTED result is returned
    uncorroborated (never recorded). Completed captured requests with a
    contradictory effect are INCOMPATIBLE. Missing transport/effect evidence
    or ambiguous failures remain UNKNOWN.
    """
    if field not in FIELDS:
        raise ValueError("unknown optional config capability")
    # A fresh CODEX_HOME does not override system requirements/config layers.
    # Refuse the probe when their absence cannot be proven; hooks from managed
    # policy remain effective even when ordinary hooks are disabled below.
    if not _system_config_is_absent():
        return "UNKNOWN", False
    sink = _Sink()
    sentinel = "CONFIG_CAPABILITY_" + uuid.uuid4().hex
    developer = "CONFIG_DEVELOPER_" + uuid.uuid4().hex
    task = "Return config probe complete and call no tools. CONFIG_TASK_" + uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix="thaliris-config-capability-") as directory:
            root = Path(directory)
            rejected = False
            corroborated = False
            # The trailing sentinel is the control run for the integer case.
            values: list[object] = [sentinel, "", 123, sentinel]
            index = 0
            while index < len(values):
                value = values[index]
                index += 1
                result, requests, contacts = _run(executable, root, sink, field, value, task, developer)
                if type(value) is int:
                    if requests:
                        return "INCOMPATIBLE", False
                    # Any other contact, or exit 0, shows neither acceptance
                    # nor typed rejection; a failure the Host attributes to an
                    # unrelated location cannot be credited to this leaf.
                    diagnostic = result.stderr + result.stdout
                    if contacts or result.returncode == 0 or _misattributed(diagnostic, field):
                        return "UNKNOWN", False
                    if _corroborated(diagnostic, field):
                        corroborated = True
                    elif not rejected:
                        # Uncorroborated: one more independent rejection run
                        # (fresh home, another integer) before the control run.
                        values.insert(index, 456)
                    rejected = True
                    continue
                if result.returncode != 0 or len(requests) != 1:
                    return "UNKNOWN", False
                body = requests[0]
                # A tool/model response or another request cannot stand in for
                # the one finite task we asked this disposable CLI to execute.
                if task not in json.dumps(body.get("input", [])):
                    return "UNKNOWN", False
                text = _developer_text(body)
                if field == "multi_agent_mode_hint_text":
                    expected = rf"<multi_agent_mode>\s*{sentinel}\s*</multi_agent_mode>"
                    if developer not in text:
                        return "UNKNOWN", False
                    if value and re.search(expected, text) is None:
                        return "INCOMPATIBLE", True
                    if not value and ("<multi_agent_mode>" in text or sentinel in text):
                        return "INCOMPATIBLE", True
                elif (bool(value) and sentinel not in text) or (not value and sentinel in text):
                    return "INCOMPATIBLE", True
        return ("SUPPORTED", corroborated) if rejected else ("UNKNOWN", False)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return "UNKNOWN", False
    finally:
        sink.close()
