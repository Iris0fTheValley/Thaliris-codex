"""Exercise generated PowerShell and CMD hooks against isolated native fixtures."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import venv

import pytest
import thaliris
from thaliris import core

from thaliris_codex import codex_adapter as adapter, host_maintenance as maintenance, host_transition, lifecycle, runtime_identity
from tests.test_host_maintenance_contract import intent, snapshot

pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows native preflight")


@pytest.fixture(scope="module")
def replay_runtime(tmp_path_factory):
    target = tmp_path_factory.mktemp("native-replay-runtime") / "venv"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(target)
    packages = target / "Lib/site-packages"
    shutil.copytree(Path(lifecycle.__file__).parent, packages / "thaliris_codex", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(Path(thaliris.__file__).parent, packages / "thaliris", ignore=shutil.ignore_patterns("__pycache__"))
    metadata = packages / "thaliris_codex-0.4.3.dist-info"
    metadata.mkdir()
    (metadata / "direct_url.json").write_text(json.dumps({"url": "https://example.test/approved-adapter",
        "vcs_info": {"vcs": "git", "commit_id": "1" * 40}}))
    exe = target / "Scripts/replay.cmd"
    exe.write_bytes(b'@echo off\r\n"%~dp0python.exe" -I -B -m thaliris_codex.cli %*\r\n')
    return exe


@pytest.fixture
def pending_native(tmp_path, monkeypatch, pinned_test_thaliris, replay_runtime):
    home = tmp_path / "home"
    project = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".codex").mkdir()
    (project / ".codex/thaliris.json").write_text("{}")
    core.init(project)
    core.task_start(project, "Isolated native maintenance replay fixture", None, None)
    monkeypatch.setenv("CODEX_HOME", str(home))

    def prepare(*, distinct=False, operation="codex-install", prepared=False):
        old_exe = pinned_test_thaliris[0] if distinct else replay_runtime
        monkeypatch.setattr(adapter, "_host_install_executable", lambda *_a: (old_exe, maintenance.digest(old_exe.read_bytes()), None))
        assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, old_exe))["ok"]
        old_manifest = (home / runtime_identity.MANIFEST_NAME).read_bytes()
        path = intent(tmp_path, home, replay_runtime, operation)
        monkeypatch.setattr(adapter, "_host_install_executable", lambda *_a: (replay_runtime, maintenance.digest(replay_runtime.read_bytes()), None))
        if operation == "codex-install":
            monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *_a: {"status": "FAILED"})
            assert not adapter.codex_install(maintenance_contract=path)["ok"]
        else:
            from thaliris_codex import codex_app_server
            monkeypatch.setattr(codex_app_server, "remove_owned_hook_trust", lambda *_a: (_ for _ in ()).throw(RuntimeError("interrupted trust")))
            assert not adapter.codex_uninstall(maintenance_contract=path)["ok"]
        if prepared:
            journal = home / host_transition.NAME
            record = json.loads(journal.read_bytes());record["phase"] = "PREPARED"
            journal.write_text(json.dumps(record))
        command = lifecycle._pinned_host_command(home / lifecycle.HOST_HOOK_SCRIPT_NAME, old_exe,
            maintenance.digest(old_exe.read_bytes()), maintenance.digest(old_manifest), "PreToolUse")
        payload = {"hook_event_name": "PreToolUse", "session_id": "native-controller-session", "cwd": str(project),
            "tool_name": "functions.exec_command", "tool_input": {"cmd": f"& '{replay_runtime}' {operation} --maintenance-contract '{path}'"}}
        return home, project, path, command, payload

    return prepare


def native(command, project, payload):
    prefix = 'powershell.exe -NoProfile -NonInteractive -Command "'
    assert command.startswith(prefix) and command.endswith('"')
    source = command[len(prefix):-1]
    before = snapshot(project)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", source],
        input=json.dumps(payload).encode(), cwd=project, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert snapshot(project) == before
    return json.loads(result.stdout)["hookSpecificOutput"]


@pytest.mark.parametrize("distinct", [False, True])
@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("operation", ["codex-install", "codex-uninstall"])
def test_exact_original_native_replay_admitted(pending_native, distinct, prepared, operation):
    home, project, path, command, payload = pending_native(distinct=distinct, prepared=prepared, operation=operation)
    before = snapshot(home)
    result = native(command, project, payload)
    assert result["permissionDecision"] == "allow", result
    assert "UNKNOWN" in result["additionalContext"]
    assert snapshot(home) == before


@pytest.mark.parametrize("distinct", [False, True])
@pytest.mark.parametrize("actor", [{"agent_id": "native-child", "agent_type": "thaliris-focused-implementer"},
    {"agent_type": "thaliris-reviewer"}, {"readonly": True}, {"fenced": True}])
def test_native_pending_never_grants_denied_actor(pending_native, distinct, actor):
    home, project, path, command, payload = pending_native(distinct=distinct)
    before = snapshot(home)
    assert native(command, project, {**payload, **actor})["permissionDecision"] == "deny"
    assert snapshot(home) == before


@pytest.mark.parametrize("defect", ["contract", "other_executor", "missing_contract", "executable", "journal", "receipt",
    "unknown_managed_bytes", "state_directory", "session_fence", "abandoned_owner", "broken_fence", "broken_child_fence", "compound", "option_drift", "executor_snapshot"])
def test_native_replay_input_drift_fails_closed(pending_native, defect):
    home, project, path, command, payload = pending_native(distinct=True)
    restore = None
    if defect == "contract":
        value = json.loads(path.read_bytes()); value["human_instruction"] += " changed"
        path.write_text(json.dumps(value))
    elif defect == "other_executor":
        payload["tool_input"]["cmd"] = payload["tool_input"]["cmd"].replace("replay.cmd", "unapproved.cmd")
    elif defect == "missing_contract":
        path.unlink()
    elif defect == "executable":
        exe = Path(json.loads(path.read_bytes())["executor"]["executable"])
        original = exe.read_bytes();exe.write_bytes(original + b"drift")
        restore = lambda: exe.write_bytes(original)
    elif defect in {"journal", "receipt", "executor_snapshot"}:
        journal = home / host_transition.NAME
        value = json.loads(journal.read_bytes())
        if defect == "journal":
            value["phase"] = "UNKNOWN"
        elif defect == "executor_snapshot":
            value["executor_runtime"] = "invalid bytes"
        else:
            import base64
            value["before"][maintenance.RECEIPT_NAME] = base64.b64encode(b"unverifiable historical receipt").decode()
        journal.write_text(json.dumps(value))
    elif defect in {"unknown_managed_bytes", "state_directory"}:
        state = project / ".context" / "state.json"
        if defect == "state_directory":
            state.unlink();state.mkdir()
        else:
            state.write_text("unknown managed state")
    elif defect in {"session_fence", "abandoned_owner", "broken_fence", "broken_child_fence"}:
        hashes = [hashlib.sha256(payload["session_id"].encode()).hexdigest()]
        fence = lifecycle._abandoned_child_fence_path(project) if defect in {"abandoned_owner", "broken_child_fence"} else lifecycle._session_fence_path(project)
        fence.parent.mkdir(parents=True, exist_ok=True)
        fence.write_text("invalid fence" if defect in {"broken_fence", "broken_child_fence"} else json.dumps({"version": 1, "children": [],
            "owner_session_id_hashes" if defect == "abandoned_owner" else "session_id_hashes": hashes}))
    elif defect == "compound":
        payload["tool_input"]["cmd"] += "; Write-Output arbitrary"
    else:
        payload["tool_input"]["cmd"] += " --execution-constraint luna-only"
    before = snapshot(home)
    try:
        assert native(command, project, payload)["permissionDecision"] == "deny"
        assert snapshot(home) == before
    finally:
        if restore:
            restore()


def test_degraded_native_denies_child_other_executor_even_with_invalid_journal(pending_native):
    home, project, path, command, payload = pending_native(distinct=True)
    (home / host_transition.NAME).write_text("unverifiable journal")
    assert native(command, project, {**payload, "agent_id": "child"})["permissionDecision"] == "deny"


@pytest.mark.parametrize("operation", ["codex-install", "codex-uninstall"])
def test_native_admission_then_original_recovery_completes(pending_native, monkeypatch, operation):
    home, project, path, command, payload = pending_native(distinct=True, operation=operation)
    assert native(command, project, payload)["permissionDecision"] == "allow"
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *_a: {"status": "TRUSTED",
        "trusted_count": len(lifecycle.HOOK_EVENTS), "enabled_count": len(lifecycle.HOOK_EVENTS)})
    from thaliris_codex import codex_app_server
    monkeypatch.setattr(codex_app_server, "remove_owned_hook_trust", lambda *_a: 7)
    invoke = adapter.codex_install if operation == "codex-install" else adapter.codex_uninstall
    result = invoke(maintenance_contract=path)
    assert result["ok"], result
    assert not host_transition.pending(home)
