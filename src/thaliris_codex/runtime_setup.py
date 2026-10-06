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


def _directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return None
    if not info.st_ino:
        return None
    return info.st_dev, info.st_ino


def _remove_created_empty_directory(path: Path, identity: tuple[int, int] | None) -> None:
    """Remove only the same leaf this attempt created, and only while empty."""
    if identity is None:
        return
    try:
        if _directory_identity(path) == identity:
            path.rmdir()
    except OSError:
        # A changed or nonempty directory is preserved for inspection.
        pass


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
    # Observe the directory through an OS handle before installing anything.
    # Store-app redirection is not resolved by spelling an absolute path. If
    # this attempt created the redirected leaf, remove it only while it remains
    # empty so the reported physical destination can be selected immediately.
    target.mkdir(parents=True)
    created_identity = _directory_identity(target)
    final = runtime_identity.physical_directory(target)
    if os.path.normcase(str(final)) != os.path.normcase(str(target)):
        _remove_created_empty_directory(target, created_identity)
        raise ValueError(f"runtime destination is redirected; select final physical directory: {final}")
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
