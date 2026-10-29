"""Platform preflight across a legitimate upgrade, an unrestarted Host, a Host
restart and genuine drift. The decision never changes; only diagnosis does."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from thaliris_codex import host_preflight, lifecycle, runtime_identity
from tests.test_drift_recovery import _windows_hook

windows = pytest.mark.skipif(os.name != "nt", reason="Windows platform preflight")
RESTRICTED = {"PSExecutionPolicyPreference": "Restricted"}
WRITE_STATE = {"tool_name": "Bash", "tool_input": {"command": "Set-Content .context/state.json '{}'"}}
ORDINARY = {"tool_name": "Bash", "tool_input": {"command": "pytest tests/test_roles.py"}}


def _run(command, cwd, home, payload, **env):
    result = subprocess.run(command, shell=True, cwd=cwd, input=json.dumps(payload).encode(), capture_output=True,
                            timeout=60, env={**os.environ, "CODEX_HOME": str(home), **env})
    assert result.returncode == 0, result.stderr
    return result


def _context(result):
    assert b"SHOULD_NOT_EXECUTE" not in result.stdout
    return json.loads(result.stdout)["hookSpecificOutput"]


def test_frozen_054_renderings_keep_installed_bytes_recognizable():
    # Hosts upgraded from 0.5.4 still hold these exact bytes; ownership must
    # recognize them so codex-install replaces rather than refuses them.
    # Pin the source text: packed bytes also depend on the platform's zlib.
    digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
    assert host_preflight._PREVIOUS_PREFLIGHT_SHA256 == "e8974be7983125d9c3d592df9e1121b07608623f87926302984f7c24b436c542"
    assert digest(host_preflight.entry_source(previous=True)) == (
        "853d0492f52ed932146c0bf821115d0ff9b00d8fa4c04b85ddb125dc3cf97756")
    assert digest(host_preflight.recovery_source(previous=True)) == (
        "8c8ad23b7e18afec8418cf361553d44d30ce52b0fb649290030b72c8fe4011e9")
    entry = 'powershell.exe -NoProfile -NonInteractive -Command "' + host_preflight.command_entry(previous=True) + '"'
    assert entry.encode() in lifecycle.host_hook_script_bytes(previous=True)
    assert entry.encode() in lifecycle.host_run_script_bytes(Path(r"C:\x\Scripts\thaliris.exe"), "a" * 64, previous=True)
    assert lifecycle.host_hook_script_bytes() != lifecycle.host_hook_script_bytes(previous=True)
    home, exe = Path(r"C:\h"), Path(r"C:\x\Scripts\thaliris.exe")
    source = lifecycle._pinned_host_source(home / lifecycle.HOST_HOOK_SCRIPT_NAME, exe, "b" * 64, "a" * 64, "PreToolUse",
                                           v054=True)
    assert digest(source) == "29d70ad7afeb89929c1d788148b9be3b79173e7567157878e77e9d55663563d8"
    old = 'powershell.exe -NoProfile -NonInteractive -Command "' + host_preflight.packed_literal_without_variables(source) + '"'
    assert lifecycle._pinned_host_payload(old)["runtime"] == "a" * 64
    assert "& $p;" not in host_preflight.entry_source()  # never a policy-gated script file


@pytest.mark.parametrize("path", [r"C:\Users\O'Brien\.codex", r"C:\h"])
def test_plain_payload_round_trips_exactly(path):
    home = Path(path)
    command = lifecycle._pinned_host_command(home / lifecycle.HOST_HOOK_SCRIPT_NAME, home / "thaliris.exe",
                                             "b" * 64, "a" * 64, "Stop")
    assert lifecycle._pinned_host_payload(command)["script"] == str(home / lifecycle.HOST_HOOK_SCRIPT_NAME)
    prefix = 'powershell.exe -NoProfile -NonInteractive -Command "'
    source = host_preflight.unpack_literal(command[len(prefix):-1])
    assert '"event":"Stop"' in source
    altered = prefix + host_preflight.packed_literal_without_variables(
        source.replace("throw 'script drift'", "Write-Output 'script drift'")) + '"'
    assert lifecycle._pinned_host_payload(altered) is None


@windows
def test_restricted_execution_policy_still_runs_the_pinned_preflight(tmp_path, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    command, home = _windows_hook(tmp_path, exe, drift=False)
    result = _run(command, tmp_path, home, ORDINARY, **RESTRICTED)
    assert b"SHOULD_NOT_EXECUTE" in result.stdout  # verified preflight passed; dispatch reached
    assert b"THALIRIS_RUNTIME_DRIFT" not in result.stdout


@windows
def test_genuine_drift_reports_its_cause_under_restricted_policy(tmp_path, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    command, home = _windows_hook(tmp_path, exe, drift=True)
    output = _context(_run(command, tmp_path, home, WRITE_STATE, **RESTRICTED))
    assert output["permissionDecision"] == "deny"
    context = output["additionalContext"]
    assert context.startswith("THALIRIS_RUNTIME_DRIFT: ") and context.endswith("assurance UNKNOWN.")
    assert "platform preflight unavailable" not in context and "thaliris_codex/cli.py" in context


def _upgrade(tmp_path, exe, monkeypatch, generation):
    """Host loaded hooks for generation G0; disk now holds committed G1."""
    real = lifecycle.host_hook_script_bytes
    earlier = real() + b"rem earlier committed generation\r\n"
    monkeypatch.setattr(lifecycle, "host_hook_script_bytes", lambda previous=False: earlier)
    stale_command, home = _windows_hook(tmp_path, exe, drift=False)
    monkeypatch.setattr(lifecycle, "host_hook_script_bytes", real)
    hook = home / lifecycle.HOST_HOOK_SCRIPT_NAME
    hook.write_bytes(real())
    encode = lambda data: base64.b64encode(data).decode("ascii")
    record = {"format": "thaliris-host-transition-v1", "phase": "PREPARED" if generation == "uncommitted" else "COMMITTED",
              "before": {lifecycle.HOST_HOOK_SCRIPT_NAME: encode(b"unrelated" if generation == "unrelated" else earlier)},
              "after": {runtime_identity.MANIFEST_NAME: encode((home / runtime_identity.MANIFEST_NAME).read_bytes()),
                        lifecycle.HOST_HOOK_SCRIPT_NAME: encode(real()),
                        host_preflight.NAME: encode((home / host_preflight.NAME).read_bytes())}}
    if generation != "absent":
        archive = home / "thaliris-host-generations" / (hashlib.sha256(json.dumps(record).encode()).hexdigest() + ".json")
        archive.parent.mkdir()
        archive.write_text(json.dumps(record, sort_keys=True) + "\n")
    if generation == "damaged_current":
        (exe.parent.parent / "Lib/site-packages/thaliris_codex/cli.py").write_text("tampered runtime")
    if generation == "foreign_hook":
        hook.write_bytes(real() + b"rem not the committed generation\r\n")
    if generation == "damaged_preflight":
        (home / host_preflight.NAME).write_bytes(host_preflight.script_bytes() + b"\n# damaged after upgrade\n")
    if generation == "missing_preflight":
        (home / host_preflight.NAME).unlink()
    return stale_command, home


@windows
@pytest.mark.parametrize("generation", ["committed", "absent", "uncommitted", "unrelated", "damaged_current",
                                        "foreign_hook", "damaged_preflight", "missing_preflight"])
def test_unrestarted_host_after_upgrade_is_distinguished_from_drift(tmp_path, pinned_test_thaliris, monkeypatch,
                                                                     generation):
    exe, _ = pinned_test_thaliris
    command, home = _upgrade(tmp_path, exe, monkeypatch, generation)
    for payload, denied in ((ORDINARY, False), (WRITE_STATE, True)):
        output = _context(_run(command, tmp_path, home, payload, **RESTRICTED))
        assert (output.get("permissionDecision") == "deny") == denied
        context = output["additionalContext"]
        assert context.endswith("assurance UNKNOWN.")
        if generation == "committed":
            assert context.startswith("THALIRIS_RUNTIME_STALE_HOST_LOAD: ")
            assert "Restart Codex once" in context and "delegated mode are kept" in context
        else:
            assert context.startswith("THALIRIS_RUNTIME_DRIFT: ") and "(script drift)" in context
            assert "STALE_HOST_LOAD" not in context


@windows
def test_restarted_host_dispatches_the_upgraded_generation(tmp_path, pinned_test_thaliris, monkeypatch):
    exe, _ = pinned_test_thaliris
    _stale, home = _upgrade(tmp_path, exe, monkeypatch, "committed")
    launcher = exe.parent / "dispatch.cmd"
    manifest = (home / runtime_identity.MANIFEST_NAME).read_bytes()
    # A restarted Host loads the registration for the files now on disk.
    command = lifecycle.host_hook_spec(home, launcher, hashlib.sha256(launcher.read_bytes()).hexdigest(),
                                       runtime_identity.manifest_identity(manifest))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    for payload in (ORDINARY, WRITE_STATE):
        assert b"SHOULD_NOT_EXECUTE" in _run(command, tmp_path, home, payload, **RESTRICTED).stdout
