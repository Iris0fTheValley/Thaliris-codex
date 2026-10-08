"""Actual independent Windows preflight, including the recovery verifier."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from thaliris_codex import host_preflight, runtime_identity
from tests.test_runtime_identity import _console_launcher

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows platform preflight")


def runtime(tmp_path):
    scripts = tmp_path / "runtime" / "Scripts"
    scripts.mkdir(parents=True)
    interpreter = scripts / "python.exe"
    interpreter.write_bytes(Path(sys.executable).read_bytes())
    (scripts.parent / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    package = scripts.parent / "Lib" / "site-packages" / "thaliris_codex"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text("")
    return scripts / "thaliris.exe", interpreter


@pytest.mark.parametrize("terminator", [b"\n", b"\r\n", b"\n\r\n", b"\r\n\r\n"])
@pytest.mark.parametrize("quoted", [False, True])
def test_python_and_platform_accept_same_distlib_layout(tmp_path, terminator, quoted):
    exe, interpreter = runtime(tmp_path)
    _console_launcher(exe, interpreter, terminator)
    if quoted:
        data = exe.read_bytes()
        binding = str(interpreter).encode()
        exe.write_bytes(data.replace(b"#!" + binding, b'#!"' + binding + b'"', 1))
    manifest = runtime_identity.manifest_bytes(exe)
    runtime_identity.validate_manifest(manifest, exe, runtime_identity.manifest_identity(manifest))
    host_preflight.verify_runtime(exe, manifest)
    # Both the normal disk guard and pinned recovery replay render this ABI.
    assert runtime_identity.WINDOWS_LAUNCHER_BINDING in host_preflight.script_bytes().decode()
    assert runtime_identity.WINDOWS_LAUNCHER_BINDING in host_preflight.recovery_source()


@pytest.mark.parametrize("invalid", ["relocated", "relative", "missing", "garbage", "three-newlines"])
def test_python_and_platform_reject_invalid_binding_even_when_hash_pinned(tmp_path, invalid):
    exe, interpreter = runtime(tmp_path)
    bound = interpreter
    terminator = b"\n\r\n"
    if invalid == "relocated":
        bound = tmp_path / "other" / "python.exe"
        bound.parent.mkdir()
        bound.write_bytes(interpreter.read_bytes())
    elif invalid == "relative":
        bound = Path("python.exe")
    elif invalid == "missing":
        bound = None
    elif invalid == "garbage":
        terminator = b"\n\r\ngarbage\n"
    elif invalid == "three-newlines":
        terminator = b"\n\n\n"
    _console_launcher(exe, bound, terminator)
    # Historical snapshot capture is not candidate admission. Independently
    # pin the bad bytes to prove rejection does not depend only on hash drift.
    manifest = runtime_identity._manifest_bytes(exe, candidate=False)
    with pytest.raises(ValueError):
        runtime_identity.validate_manifest(manifest, exe, runtime_identity.manifest_identity(manifest))
    with pytest.raises(ValueError, match="platform runtime preflight failed"):
        host_preflight.verify_runtime(exe, manifest)


@pytest.mark.parametrize("drift", ["launcher", "interpreter", "extra-file"])
def test_platform_rejects_runtime_drift_before_dispatch(tmp_path, drift):
    exe, interpreter = runtime(tmp_path)
    _console_launcher(exe, interpreter, b"\n\r\n")
    manifest = runtime_identity.manifest_bytes(exe)
    target = {"launcher": exe, "interpreter": interpreter,
              "extra-file": exe.parent / "unlisted.py"}[drift]
    target.write_bytes(target.read_bytes() + b"changed" if target.exists() else b"changed")
    with pytest.raises(ValueError):
        runtime_identity.validate_manifest(manifest, exe, runtime_identity.manifest_identity(manifest))
    with pytest.raises(ValueError, match="platform runtime preflight failed"):
        host_preflight.verify_runtime(exe, manifest)
