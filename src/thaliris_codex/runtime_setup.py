"""Create a dedicated Host runtime without pip/setuptools startup machinery.

Run this module from a disposable bootstrap Python with pip installed. pip's
--python route installs into a venv created without ensurepip. Build tools stay
in the bootstrap/build environment, never in the pinned runtime. Nothing in an
existing runtime or Codex home is removed or modified.
Create directly at the final physical directory; installed venvs are never
relocated. The public final-path console must pass before setup returns success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import venv

from . import runtime_identity

_HOST_PACKAGE_FAMILY_ENV = "CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY"
_HOST_PACKAGE_FAMILY = re.compile(r"OpenAI\.Codex_[A-Za-z0-9]{13}")


def _host_package_family() -> str:
    """Use the current Host's package context, or its exact registered identity."""
    family = os.environ.get(_HOST_PACKAGE_FAMILY_ENV)
    if family:
        if not _HOST_PACKAGE_FAMILY.fullmatch(family):
            raise ValueError("current Codex Host package context is invalid")
        return family
    if os.name != "nt":
        raise ValueError("current Codex Host package context is unavailable; pass --runtime explicitly")

    # A bootstrap started from an external terminal has no Host-injected
    # environment. Resolve only the exact stable Codex package identity for the
    # current user and reject missing or ambiguous registrations.
    command = (
        "$ErrorActionPreference='Stop'; "
        "$packages=@(Get-AppxPackage -Name 'OpenAI.Codex'); "
        "if ($packages.Count -ne 1 -or $packages[0].Name -cne 'OpenAI.Codex') { exit 2 }; "
        "[Console]::Out.Write($packages[0].PackageFamilyName)"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            env=runtime_identity.child_environment(), capture_output=True, text=True,
            timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("unable to discover the current Codex Host package; pass --runtime explicitly") from exc
    family = result.stdout.strip() if result.returncode == 0 else ""
    if not _HOST_PACKAGE_FAMILY.fullmatch(family):
        raise ValueError("a unique current Codex Host package was not found; pass --runtime explicitly")
    return family


def default_runtime_directory(adapter_source: str) -> Path:
    """Choose a new final runtime under the current Host's physical LocalCache."""
    if os.name != "nt":
        raise ValueError("automatic runtime discovery is supported for the Windows Codex Host; pass --runtime explicitly")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise ValueError("Windows LocalAppData is unavailable; pass --runtime explicitly")
    family = _host_package_family()
    logical_base = Path(local_app_data) / "Packages" / family / "LocalCache" / "Local"
    try:
        physical_base = runtime_identity.physical_directory(logical_base)
    except (OSError, ValueError) as exc:
        raise ValueError("current Codex Host LocalCache is unavailable; pass --runtime explicitly") from exc
    source_identity = hashlib.sha256(_source(adapter_source).encode("utf-8")).hexdigest()[:12]
    leaf = f"codex-{source_identity}-{uuid.uuid4().hex[:12]}"
    return physical_base / "Thaliris" / "runtimes" / leaf


def _source(value: str) -> str:
    if re.fullmatch(r"git\+https://[^\s]+@[0-9a-f]{40}", value):
        return value
    # A local/downloaded wheel is accepted only with its independently selected
    # artifact digest. pip also records this archive hash as direct provenance.
    match = re.fullmatch(r"(.+\.whl)#sha256=([0-9a-f]{64})", value)
    if match:
        path = Path(match[1]).resolve(strict=True)
        runtime_identity._safe_file(path)
        import hashlib
        if hashlib.sha256(path.read_bytes()).hexdigest() != match[2]:
            raise ValueError("reviewed wheel artifact identity mismatch")
        return path.as_uri() + "#sha256=" + match[2]
    raise ValueError("select a full immutable HTTPS Git commit or wheel#sha256=DIGEST")


class _OwnedDirectory:
    """Keep the directory object returned by exclusive creation for safe cleanup."""

    def __init__(self, path: Path, *, handle=None):
        self.path = path
        self.handle = handle

    def physical_path(self) -> Path:
        if self.handle is None:
            return runtime_identity.physical_directory(self.path)
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        final = kernel.GetFinalPathNameByHandleW
        final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        final.restype = wintypes.DWORD
        length = final(self.handle, None, 0, 0)
        if not length:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(length + 1)
        written = final(self.handle, buffer, len(buffer), 0)
        if not written or written >= len(buffer):
            raise OSError("unable to observe final runtime directory")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)

    def remove_if_empty(self) -> bool:
        """Mark this exact created directory for deletion; never unlink by name."""
        if self.handle is None:
            # Portable mkdir has no create-and-return-handle operation. Preserve
            # the leaf rather than using a racy identity-check/path-unlink pair.
            return False
        import ctypes
        from ctypes import wintypes

        class FileDispositionInfo(ctypes.Structure):
            _fields_ = [("DeleteFile", ctypes.c_ubyte)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        set_info = kernel.SetFileInformationByHandle
        set_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        set_info.restype = wintypes.BOOL
        disposition = FileDispositionInfo(1)
        if not set_info(self.handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            # A nonempty directory or a concurrent handle can prevent deletion.
            # Preserve it rather than falling back to a path-based removal.
            return False
        return True

    def close(self) -> None:
        if self.handle is not None:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            close(self.handle)
            self.handle = None


def _create_owned_directory(path: Path) -> _OwnedDirectory:
    """Exclusively create a directory and retain its Windows file handle."""
    if os.name != "nt":
        path.mkdir()
        return _OwnedDirectory(path)

    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", ctypes.c_void_p)]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(UnicodeString)), ("Attributes", wintypes.ULONG),
                    ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("StatusOrPointer", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_parent = kernel.CreateFileW
    open_parent.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_parent.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    parent = open_parent(str(path.parent), 0x0004 | 0x0020 | 0x0080 | 0x00100000,
                         0x00000007, None, 3, 0x02000000, None)
    if parent == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        leaf_buffer = ctypes.create_unicode_buffer(path.name)
        leaf_bytes = len(path.name.encode("utf-16-le"))
        leaf = UnicodeString(leaf_bytes, leaf_bytes + 2, ctypes.cast(leaf_buffer, ctypes.c_void_p))
        attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), parent, ctypes.pointer(leaf), 0x40,
                                      None, None)
        io_status = IoStatusBlock()
        created = wintypes.HANDLE()
        ntdll = ctypes.WinDLL("ntdll")
        nt_create = ntdll.NtCreateFile
        nt_create.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                              ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatusBlock),
                              ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
                              wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
        nt_create.restype = wintypes.LONG
        status = nt_create(ctypes.byref(created), 0x00010000 | 0x00000080 | 0x00100000,
                           ctypes.byref(attributes), ctypes.byref(io_status), None,
                           0x00000010, 0x00000003, 2, 0x00000001 | 0x00000020, None, 0)
        status_value = ctypes.c_uint32(status).value
        if status < 0:
            if status_value == 0xC0000035:
                raise ValueError("runtime destination already exists; select a new directory")
            to_error = ntdll.RtlNtStatusToDosError
            to_error.argtypes = [wintypes.LONG]
            to_error.restype = wintypes.ULONG
            raise ctypes.WinError(to_error(status))
        return _OwnedDirectory(path, handle=created)
    finally:
        close(parent)


def _remove_owned_directory_if_empty(directory: _OwnedDirectory) -> bool:
    return directory.remove_if_empty()


def _owned_directory_physical_path(directory: _OwnedDirectory) -> Path:
    return directory.physical_path()


def create(directory: Path, core_source: str, adapter_source: str) -> dict:
    if sys.version_info < (3, 11):
        raise ValueError("Host runtime setup requires Python 3.11+")
    sources = [_source(core_source), _source(adapter_source)]
    target = Path(os.path.abspath(directory))
    if target.exists():
        raise ValueError("runtime destination already exists; select a new directory")
    for parent in target.parents:
        if runtime_identity._is_link(parent):
            raise ValueError("runtime destination contains a link")
    target.parent.mkdir(parents=True, exist_ok=True)
    owned = _create_owned_directory(target)
    try:
        # On Windows this is queried through the handle returned by the atomic
        # create, so a replaced pathname cannot become the object we trust.
        final = _owned_directory_physical_path(owned)
        if os.path.normcase(str(final)) != os.path.normcase(str(target)):
            removed = _remove_owned_directory_if_empty(owned)
            diagnostic = f"runtime destination is redirected; select final physical directory: {final}"
            if not removed:
                diagnostic += f"; created directory was preserved because safe empty cleanup was unavailable: {target}"
            raise ValueError(diagnostic)
        target = final
        (target / runtime_identity.LOCATION_NAME).write_bytes(runtime_identity.location_bytes(target))
        # Copies are intentional: a system Python symlink is outside the venv's
        # independently pinned file topology.
        venv.EnvBuilder(with_pip=False, symlinks=False).create(target)
        interpreter = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        environment = runtime_identity.child_environment()
        subprocess.run([sys.executable, "-I", "-B", "-m", "pip", "--isolated", "--python", str(interpreter),
                        "install", "--no-deps", "--no-compile", *sources],
                       env=environment, check=True, stdout=sys.stderr)
        executable = interpreter.parent / ("thaliris.exe" if os.name == "nt" else "thaliris")
        contents = runtime_identity.manifest_bytes(executable)
        # Check runtime dependency versions without installing package-manager
        # machinery into the runtime or importing code from the caller's checkout.
        subprocess.run([str(interpreter), "-I", "-B", "-c",
                        "from importlib.metadata import version; "
                        "v=tuple(map(int,version('thaliris').split('.')[:3])); "
                        "assert (0,4,3)<=v<(0,5,0); import thaliris_codex.cli"],
                       env=environment, check=True, stdout=sys.stderr)
        if runtime_identity.manifest_bytes(executable) != contents:
            raise ValueError("new runtime changed during verification")
        smoke = runtime_identity.console_smoke(executable, contents)
        return {"ok": True, "executable": str(executable),
                "runtime_sha256": runtime_identity.manifest_identity(contents),
                "runtime_dir": str(target), "console_smoke": smoke,
                "host_installed": False, "project_files_touched": []}
    finally:
        owned.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, help="explicit runtime directory; defaults to the current Codex Host")
    parser.add_argument("--core-source", required=True)
    parser.add_argument("--adapter-source", required=True)
    args = parser.parse_args()
    try:
        directory = args.runtime or default_runtime_directory(args.adapter_source)
        result = create(directory, args.core_source, args.adapter_source)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "host_installed": False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
