"""Exact dedicated-venv identity for a Host-installed Thaliris runtime.

The base CPython standard library and operating system are outside this
installed-runtime boundary and remain platform trust dependencies.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import zipfile

MANIFEST_NAME = "thaliris-install.json"
MANIFEST_FORMAT = "thaliris-installed-runtime-v1"
LOCATION_NAME = "thaliris-runtime-location.json"
LOCATION_FORMAT = "thaliris-runtime-location-v1"

# One ABI definition for Python admission and the generated independent
# PowerShell preflight/replay verifier. CR/LF never belongs to the binding.
WINDOWS_LAUNCHER_BINDING = r'#!(?:"([^"\r\n]+)"|([^"\r\n]+))\r?\n(?:\r?\n)?'


def physical_directory(path: Path) -> Path:
    """Observe the final OS directory, including packaged Windows redirection."""
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("runtime directory must be an existing absolute directory")
    for parent in (path, *path.parents):
        if _is_link(parent):
            raise ValueError("runtime directory contains a link")
    if os.name != "nt":
        return path.resolve(strict=True)
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    final = kernel.GetFinalPathNameByHandleW
    final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final.restype = wintypes.DWORD
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # The setup creator keeps an exclusive directory handle until its final
    # runtime smoke completes. Read/write sharing lets identity probes inspect
    # that same directory while withholding delete sharing keeps its path fixed.
    handle = create(str(path), 0, 3, None, 3, 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        length = final(handle, None, 0, 0)
        if not length:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(length + 1)
        written = final(handle, buffer, len(buffer), 0)
        if not written or written >= len(buffer):
            raise OSError("unable to observe final runtime directory")
        value = buffer.value
    finally:
        close(handle)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def location_bytes(venv: Path) -> bytes:
    final = physical_directory(venv)
    scripts = final / ("Scripts" if os.name == "nt" else "bin")
    value = {"format": LOCATION_FORMAT, "venv_dir": str(final),
             "executable": str(scripts / ("thaliris.exe" if os.name == "nt" else "thaliris")),
             "interpreter": str(scripts / ("python.exe" if os.name == "nt" else "python"))}
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _assert_location(launcher: Path, *, required: bool = False) -> None:
    anchor = launcher.parent.parent / LOCATION_NAME
    # Older owned generations have separate historical verification. Candidate
    # launcher binding is checked independently; absence grants no relocation.
    if required and not anchor.exists():
        raise ValueError("candidate runtime lacks final-location setup anchor")
    if anchor.exists():
        expected = location_bytes(launcher.parent.parent)
        if (_safe_file(anchor).read_bytes() != expected
                or os.path.normcase(str(launcher)) != os.path.normcase(json.loads(expected)["executable"])):
            raise ValueError("runtime location changed: installed venv may not be relocated")


def _assert_launcher_binding(launcher: Path) -> None:
    """Read pip/distlib's Windows ABI without executing a candidate launcher."""
    if os.name != "nt" or launcher.suffix.casefold() != ".exe":
        return
    data = launcher.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) != 1 or entries[0].filename != "__main__.py":
                raise ValueError("unsupported Windows console launcher archive")
            offset = entries[0].header_offset
        start = data.rfind(b"#!", 0, offset)
        # distlib writes the shebang as ``#!<interpreter>\n`` on the short-path
        # branch and as ``#!<interpreter>\n\r\n`` (PEP 397's terminator plus the
        # archive separator) once the interpreter path is long. Both encode the
        # same exact absolute binding, so accept either terminator. The path
        # itself still may not contain CR or LF, and the equality checks below
        # remain the actual invariant.
        match = re.fullmatch(WINDOWS_LAUNCHER_BINDING.encode("ascii"), data[start:offset]) if start >= 0 else None
        if match is None:
            raise ValueError("Windows console launcher interpreter binding is unavailable")
        bound = Path((match[1] or match[2]).decode("utf-8"))
        expected = launcher.parent / "python.exe"
        if not bound.is_absolute() or os.path.normcase(str(bound)) != os.path.normcase(str(expected)):
            raise ValueError("runtime launcher location changed: interpreter must be in the same final directory")
        if _safe_file(bound) != _safe_file(expected):
            raise ValueError("runtime launcher interpreter differs from final directory")
    except (zipfile.BadZipFile, UnicodeError) as exc:
        raise ValueError("invalid Windows console launcher interpreter binding") from exc


def child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        environment.pop(name, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    return environment


def console_smoke(executable: Path, contents: bytes) -> dict[str, object]:
    """Exercise the ordinary public launcher before selecting maintenance intent."""
    record = validate_manifest(contents, executable, manifest_identity(contents))
    try:
        probe = subprocess.run([str(executable), "runtime-check"], env=child_environment(),
                               capture_output=True, check=False, timeout=15)
        if probe.returncode or probe.stderr:
            raise ValueError("final-path public runtime console smoke failed")
        observed = json.loads(probe.stdout)
        expected = {"ok": True, "executable": record["executable"],
                    "interpreter": str(executable.parent / ("python.exe" if os.name == "nt" else "python")),
                    "venv_dir": record["venv_dir"], "package_dir": record["package_dir"],
                    "bytecode_disabled": True}
        if observed != expected:
            raise ValueError("final-path public runtime console origin mismatch")
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("final-path public runtime console smoke failed") from exc
    if manifest_bytes(executable) != contents:
        raise ValueError("runtime changed during final-path public console smoke")
    return observed


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _safe_file(path: Path) -> Path:
    if not path.is_absolute() or not path.is_file() or _is_link(path):
        raise ValueError(f"unsafe runtime file: {path}")
    resolved = path.resolve(strict=True)
    for parent in (path, *path.parents):
        if _is_link(parent):
            raise ValueError(f"runtime path contains a symlink: {path}")
    return resolved


def _package_dir(executable: Path) -> Path:
    executable = _safe_file(executable)
    parent = executable.parent
    if parent.name.casefold() not in {"scripts", "bin"}:
        raise ValueError("Thaliris launcher is not in a virtual environment Scripts/bin directory")
    venv = parent.parent
    if not (venv / "pyvenv.cfg").is_file() or _is_link(venv / "pyvenv.cfg"):
        raise ValueError("Thaliris launcher is not in a virtual environment")
    if parent.name.casefold() == "scripts":
        candidates = [venv / "Lib" / "site-packages" / "thaliris_codex"]
    else:
        candidates = list((venv / "lib").glob("python*/site-packages/thaliris_codex"))
    candidates = [candidate for candidate in candidates if candidate.is_dir()]
    if len(candidates) != 1:
        raise ValueError("installed Thaliris package directory is missing or ambiguous")
    package = candidates[0]
    for ancestor in (package, *package.parents):
        if _is_link(ancestor):
            raise ValueError("installed Thaliris package path contains a symlink")
    if not (package / "__init__.py").is_file() or not (package / "cli.py").is_file():
        raise ValueError("installed Thaliris package is incomplete")
    return package.resolve(strict=True)


def _assert_isolated_venv(venv: Path) -> None:
    """Reject Python startup paths that can import code outside the pinned tree."""
    config = (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    settings = {}
    for line in config.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip().casefold()] = value.strip().casefold()
    if settings.get("include-system-site-packages") != "false":
        raise ValueError("installed runtime must disable system site packages")
    for pth in venv.rglob("*.pth"):
        if _is_link(pth) or not pth.is_file():
            raise ValueError("unsafe installed runtime .pth file")
        try:
            lines = pth.read_text(encoding="utf-8").splitlines()
        except UnicodeError as exc:
            raise ValueError("unsafe installed runtime .pth encoding") from exc
        if any(line.strip() and not line.lstrip().startswith("#") for line in lines):
            raise ValueError("installed runtime .pth may not execute or extend import paths")


def _files(venv: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for root, dirs, files in os.walk(venv, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(dirs)
        for name in dirs:
            path = root_path / name
            if _is_link(path):
                # CPython creates this relative, internal alias on 64-bit
                # POSIX even with symlinks=False. Pin the link itself, while
                # walking and hashing its real target exactly once via lib.
                # No absolute target, alternate spelling or nested link gains
                # admission from this platform-layout exception.
                if (os.name != "nt" and root_path == venv and name == "lib64"
                        and path.is_symlink() and os.readlink(path) == "lib"
                        and (venv / "lib").is_dir() and not _is_link(venv / "lib")):
                    result["lib64"] = hashlib.sha256(b"symlink:lib").hexdigest()
                else:
                    raise ValueError("installed runtime contains a symlink")
        for name in sorted(files):
            relative = (root_path / name).relative_to(venv).as_posix()
            path = _safe_file(root_path / name)
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result or "pyvenv.cfg" not in result:
        raise ValueError("installed runtime is incomplete")
    return dict(sorted(result.items()))


def _manifest_bytes(executable: Path, *, candidate: bool) -> bytes:
    launcher = _safe_file(executable)
    package = _package_dir(launcher)
    venv = launcher.parent.parent.resolve(strict=True)
    _assert_isolated_venv(venv)
    if candidate or (venv / LOCATION_NAME).exists():
        _assert_location(launcher)
        _assert_launcher_binding(launcher)
    record = {
        "format": MANIFEST_FORMAT,
        "executable": str(launcher),
        "executable_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "venv_dir": str(venv),
        "package_dir": str(package),
        "files": _files(venv),
    }
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def manifest_bytes(executable: Path) -> bytes:
    """Capture a selectable candidate; location and launcher checks are mandatory."""
    return _manifest_bytes(executable, candidate=True)


def manifest_identity(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def validate_manifest(contents: bytes, executable: Path, identity: str) -> dict[str, object]:
    return _validate_manifest(contents, executable, identity, candidate=True)


def validate_existing_manifest(contents: bytes, executable: Path, identity: str) -> dict[str, object]:
    """Check an installed prior generation without minting candidate admission.

    Pre-location generations retain every original topology, isolation and file
    pin. Their ownership is established separately by the authorized receipt or
    exact legacy approval. No new runnable/location assurance is attributed to
    them. Candidate selection always uses the strict public validator.
    """
    return _validate_manifest(contents, executable, identity, candidate=False)


def _validate_manifest(contents: bytes, executable: Path, identity: str, *, candidate: bool) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{64}", identity) or manifest_identity(contents) != identity:
        raise ValueError("installed runtime manifest identity mismatch")
    record = validate_manifest_record(contents)
    # Removing a newer generation's anchor is still exact pinned-file drift.
    current_bytes = _manifest_bytes(executable, candidate=candidate or LOCATION_NAME in record["files"])
    if contents != current_bytes:
        raise ValueError("installed Thaliris runtime changed: " + json.dumps(
            manifest_diff(record, json.loads(current_bytes)), sort_keys=True, separators=(",", ":")))
    return record


def manifest_diff(expected: dict[str, object], actual: dict[str, object]) -> list[dict[str, object]]:
    """Describe evidence without accepting it or executing either runtime.

    Bytecode is executable input even when its name looks like a Python cache.
    A new cache therefore has a precise diagnosis, but does not gain trust from
    its filename. Ordinary workspace files are outside this installed boundary.
    """
    differences: list[dict[str, object]] = []
    for field in ("format", "executable", "executable_sha256", "venv_dir", "package_dir"):
        if expected.get(field) != actual.get(field):
            differences.append({"surface": "manifest" if field == "format" else "executable" if field.startswith("executable") else "topology",
                                "path": field, "expected": expected.get(field), "actual": actual.get(field)})
    old, new = expected.get("files", {}), actual.get("files", {})
    for name in sorted(set(old) | set(new)):
        if old.get(name) == new.get(name):
            continue
        surface = "python_bytecode" if name.endswith(".pyc") else "package" if "site-packages/" in name else "runtime"
        differences.append({"surface": surface, "path": name, "expected": old.get(name, "ABSENT"),
                            "actual": new.get(name, "ABSENT")})
    return differences


def diagnose_manifest(contents: bytes, executable: Path | None = None) -> dict[str, object]:
    """Validation-only diagnostics; never launch or import the installed code."""
    try:
        expected = validate_manifest_record(contents)
        actual = json.loads(manifest_bytes(executable or Path(expected["executable"])))
        differences = manifest_diff(expected, actual)
        return {"status": "CHANGED" if differences else "MATCH", "differences": differences,
                "execution_assurance": "UNKNOWN" if differences else "PINNED_BYTES",
                "decision_required": bool(differences)}
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        return {"status": "UNKNOWN", "error": str(exc), "differences": [],
                "execution_assurance": "UNKNOWN", "decision_required": True}


def validate_manifest_record(contents: bytes) -> dict[str, object]:
    """Validate owned manifest bytes without requiring the old runtime to survive."""
    try:
        record = json.loads(contents)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid installed runtime manifest") from exc
    required = {"format", "executable", "executable_sha256", "venv_dir", "package_dir", "files"}
    legacy = required - {"venv_dir"}
    if not isinstance(record, dict) or set(record) not in (required, legacy) or record.get("format") != MANIFEST_FORMAT:
        raise ValueError("invalid installed runtime manifest format")
    is_legacy = set(record) == legacy
    executable = Path(record["executable"]) if isinstance(record["executable"], str) else Path()
    venv = (Path(record["venv_dir"]) if isinstance(record.get("venv_dir"), str) else Path()) if not is_legacy else executable.parent.parent
    package = Path(record["package_dir"]) if isinstance(record["package_dir"], str) else Path()
    if (not executable.is_absolute() or not venv.is_absolute() or not package.is_absolute()
            or executable.parent.parent != venv or not package.is_relative_to(venv)
            or not re.fullmatch(r"[0-9a-f]{64}", str(record["executable_sha256"]))):
        raise ValueError("invalid installed runtime manifest paths")
    files = record["files"]
    essential = ({"__init__.py", "cli.py"} if is_legacy else {
        "pyvenv.cfg", executable.relative_to(venv).as_posix(),
        (package / "__init__.py").relative_to(venv).as_posix(),
        (package / "cli.py").relative_to(venv).as_posix(),
    })
    if not isinstance(files, dict) or not files or not essential <= set(files):
        raise ValueError("invalid installed runtime manifest files")
    for name, digest in files.items():
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name or name.startswith("/")
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("invalid installed runtime manifest file entry")
    if not is_legacy and files[executable.relative_to(venv).as_posix()] != record["executable_sha256"]:
        raise ValueError("invalid installed runtime launcher hash")
    if contents != (json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"):
        raise ValueError("invalid installed runtime manifest serialization")
    return record
