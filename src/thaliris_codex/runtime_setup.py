"""Create a dedicated Host runtime without pip/setuptools startup machinery.

Run this module from a disposable bootstrap Python with pip installed. pip's
--python route installs into a venv created without ensurepip. Build tools stay
in the bootstrap/build environment, never in the pinned runtime. Nothing in an
existing runtime or Codex home is removed or modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import venv

from . import runtime_identity


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


def create(directory: Path, core_source: str, adapter_source: str) -> dict:
    if sys.version_info < (3, 11):
        raise ValueError("Host runtime setup requires Python 3.11+")
    sources = [_source(core_source), _source(adapter_source)]
    target = directory.absolute()
    if target.exists():
        raise ValueError("runtime destination already exists; select a new directory")
    for parent in target.parents:
        if runtime_identity._is_link(parent):
            raise ValueError("runtime destination contains a link")
    # Copies are intentional: a system Python symlink is outside the venv's
    # independently pinned file topology.
    venv.EnvBuilder(with_pip=False, symlinks=False).create(target)
    interpreter = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        environment.pop(name, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
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
    return {"ok": True, "executable": str(executable),
            "runtime_sha256": runtime_identity.manifest_identity(contents),
            "host_installed": False, "project_files_touched": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--core-source", required=True)
    parser.add_argument("--adapter-source", required=True)
    args = parser.parse_args()
    try:
        result = create(args.runtime, args.core_source, args.adapter_source)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "host_installed": False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
