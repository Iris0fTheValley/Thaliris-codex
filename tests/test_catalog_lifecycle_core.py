from __future__ import annotations

import json
import io
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

from thaliris_codex import catalog_recovery as recovery, codex_adapter as adapter
from thaliris_codex import host_maintenance as maintenance, model_catalog_config as catalog, runtime_identity
from tests.test_host_maintenance_contract import intent, snapshot
from tests.test_model_catalog_config import supply


def install(tmp_path, monkeypatch, executable, *, policy=True, source=None):
    home = tmp_path / "home"
    root = tmp_path / "project"
    marker = root / ".codex" / "thaliris.json"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(adapter._PROJECT_ACTIVATION_BYTES)
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    contract = intent(tmp_path, home, executable)
    value = json.loads(contract.read_bytes())
    if policy:
        value["catalog_recovery_project_root"] = str(root)
        if source is not None:
            value["catalog_recovery_source_root"] = str(source)
    contract.write_text(json.dumps(value))
    result = adapter.codex_install(maintenance_contract=contract)
    assert result["ok"], result
    return home, root


def test_historical_reader_executes_refusal_before_mutation(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, _ = install(tmp_path, monkeypatch, executable)
    receipt = json.loads((home / maintenance.RECEIPT_NAME).read_bytes())
    assert receipt["format"] == maintenance.CATALOG_RECEIPT_FORMAT
    assert receipt["required_capabilities"] == [maintenance.CATALOG_CAPABILITY]
    # Execute the actual pre-catalog implementation, not a copied assertion.
    original = subprocess.check_output(["git", "show", "324b9db^:src/thaliris_codex/host_maintenance.py"])
    historical = types.ModuleType("thaliris_codex.historical_maintenance")
    historical.__package__ = "thaliris_codex"
    exec(compile(original, "historical-host-maintenance.py", "exec"), historical.__dict__)
    before = snapshot(home)
    result = historical.install(home, None, None, None, intent(tmp_path, home, executable))
    assert result["ok"] is False and result["changed"] is False
    assert "ownership record" in " ".join(result["manual_action_required"])
    assert snapshot(home) == before
    result = historical.uninstall(home, intent(tmp_path, home, executable, "codex-uninstall"))
    assert result["ok"] is False and result["changed"] is False
    assert snapshot(home) == before


def test_v1_catalog_receipt_migrates_without_config_loss(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, _ = install(tmp_path, monkeypatch, executable, policy=False)
    path = home / maintenance.RECEIPT_NAME
    receipt = json.loads(path.read_bytes())
    receipt["format"] = maintenance.RECEIPT_FORMAT
    receipt.pop("required_capabilities")
    path.write_text(json.dumps(receipt))
    config_before = (home / "config.toml").read_bytes()
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, executable))
    assert result["ok"], result
    assert json.loads(path.read_bytes())["format"] == maintenance.CATALOG_RECEIPT_FORMAT
    assert (home / "config.toml").read_bytes() == config_before


@pytest.mark.parametrize("loss", ["marker", "move", "source"])
def test_independent_recovery_after_project_loss_is_idempotent(tmp_path, monkeypatch, pinned_test_thaliris, loss):
    executable, _ = pinned_test_thaliris
    source = tmp_path / "source"
    source.mkdir()
    home, root = install(tmp_path, monkeypatch, executable, source=source)
    config = home / "config.toml"
    with config.open("ab") as stream:
        stream.write(b"\n# user tail remains\n")
    backing = (home / catalog.NAME).read_bytes()
    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    if loss == "marker":
        (root / ".codex" / "thaliris.json").unlink()
    elif loss == "move":
        root.rename(tmp_path / "moved-project")
    else:
        source.rmdir()
    result = recovery.recover(home, identity)
    assert result["ok"] and result["status"] == "RESTORED_ABSENT", result
    assert catalog.KEY.encode() not in config.read_bytes()
    assert b"# user tail remains" in config.read_bytes()
    assert (home / catalog.NAME).read_bytes() == backing
    assert result["backing_artifact_status"] == "RETAINED_REFERENCE_SAFE"
    after = snapshot(home)
    result = recovery.recover(home, identity)
    assert result["ok"] and result["status"] == "ALREADY_ABSENT", result
    assert snapshot(home) == after
    assert recovery.retained_record(home)["catalog_sha256"] == maintenance.digest(backing)
    if loss == "move":
        assert not root.exists()


def test_recovery_crash_between_field_and_receipt_repeats_safely(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, root = install(tmp_path, monkeypatch, executable)
    (root / ".codex" / "thaliris.json").unlink()
    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    original = adapter._atomic_host_write
    def fail_receipt(path, contents):
        if path.name == maintenance.RECEIPT_NAME:
            raise OSError("crash after field restoration")
        return original(path, contents)
    with monkeypatch.context() as scoped:
        scoped.setattr(adapter, "_atomic_host_write", fail_receipt)
        assert recovery.recover(home, identity)["ok"] is False
    config = (home / "config.toml").read_bytes()
    assert catalog.KEY.encode() not in config
    result = recovery.recover(home, identity)
    assert result["ok"] and result["status"] == "RECOVERY_PROVENANCE_UNKNOWN", result
    assert (home / "config.toml").read_bytes() == config
    receipt = json.loads((home / maintenance.RECEIPT_NAME).read_bytes())
    assert "restored" not in receipt[recovery.POLICY_KEY]


def test_user_deleted_field_before_project_loss_does_not_authorize_reclaim(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, root = install(tmp_path, monkeypatch, executable)
    config_path = home / "config.toml"
    config_before = config_path.read_bytes()
    receipt_path = home / maintenance.RECEIPT_NAME
    receipt_raw_before = receipt_path.read_bytes()
    receipt_before = json.loads(receipt_raw_before)
    record = receipt_before[catalog.RECORD_KEY]
    owned_fragment = record["fragment"].encode()
    assert config_before.count(owned_fragment) == 1
    config_path.write_bytes(config_before.replace(owned_fragment, b"", 1))
    after_user_delete = config_path.read_bytes()
    assert catalog.KEY.encode() not in after_user_delete
    (root / ".codex" / "thaliris.json").unlink()

    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    recovered = recovery.recover(home, identity)
    assert recovered["ok"] and recovered["status"] == "RECOVERY_PROVENANCE_UNKNOWN", recovered
    assert config_path.read_bytes() == after_user_delete
    assert receipt_path.read_bytes() == receipt_raw_before
    receipt_after_recovery = json.loads(receipt_path.read_bytes())
    assert "restored" not in receipt_after_recovery[recovery.POLICY_KEY]

    (root / ".codex" / "thaliris.json").write_bytes(adapter._PROJECT_ACTIVATION_BYTES)
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, executable))
    assert result["ok"] and result["catalog_goal_met"] is False, result
    assert result["native_model_catalog_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert config_path.read_bytes() == after_user_delete


@pytest.mark.parametrize("payload", [
    {},
    {"session_id": ""},
    {"session_id": []},
    {"session_id": "test", "readonly": "true"},
    {"session_id": "test", "fenced": 1},
    {"session_id": "test", "agent_id": []},
    {"session_id": "test", "agent_type": 7},
    {"session_id": "test", "turn_id": None},
])
def test_session_start_rejects_malformed_native_identity_before_recovery(tmp_path, monkeypatch, payload):
    from thaliris_codex import lifecycle
    fake_executable = tmp_path / "runtime" / "python.exe"
    fake_executable.parent.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (home / runtime_identity.MANIFEST_NAME).write_bytes(b"fixture manifest")
    fake_manifest = {"executable": str(fake_executable), "package_dir": str(Path(recovery.__file__).parent)}
    monkeypatch.setattr(runtime_identity, "validate_manifest_record", lambda raw: fake_manifest)
    monkeypatch.setattr(runtime_identity, "validate_manifest", lambda *args: None)
    monkeypatch.setattr(sys, "executable", str(fake_executable))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["catalog_recovery", "--home", str(home),
        "--runtime-sha256", "f" * 64, "--session-start", "--managed-hook-abi", lifecycle.MANAGED_HOOK_ABI])
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode())))
    recovered = []
    monkeypatch.setattr(recovery, "recover", lambda *args: recovered.append(args) or {"ok": True, "status": "RECOVERED"})

    assert recovery.main() != 0
    assert recovered == []


@pytest.mark.parametrize("failure", ["receipt", "actor-check"])
@pytest.mark.parametrize("native_exit", [0, 7])
def test_auxiliary_failure_forwards_exact_native_result_once(tmp_path, monkeypatch, failure, native_exit):
    from thaliris_codex import lifecycle, task_authority
    executable = tmp_path / "runtime" / "thaliris.exe"
    home = tmp_path / "home"
    home.mkdir()
    (home / runtime_identity.MANIFEST_NAME).write_bytes(b"fixture manifest")
    manifest = {"executable": str(executable), "package_dir": str(Path(recovery.__file__).parent)}
    monkeypatch.setattr(runtime_identity, "validate_manifest_record", lambda raw: manifest)
    monkeypatch.setattr(runtime_identity, "validate_manifest", lambda *args: None)
    monkeypatch.setattr(sys, "executable", str(executable.parent / "python.exe"))
    marker = tmp_path / ".codex" / "thaliris.json"
    marker.parent.mkdir()
    marker.write_bytes(adapter._PROJECT_ACTIVATION_BYTES)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["catalog_recovery", "--home", str(home),
        "--runtime-sha256", "f" * 64, "--session-start", "--managed-hook-abi", lifecycle.MANAGED_HOOK_ABI])
    raw = b'\xef\xbb\xbf  {"session_id":"native-session","source":"startup"}\r\n'
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(raw)))
    stdout, stderr = io.BytesIO(), io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(stdout, encoding="utf-8", write_through=True))
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(stderr, encoding="utf-8", write_through=True))
    if failure == "actor-check":
        def unavailable(*args):
            raise ValueError("authority unavailable")
        monkeypatch.setattr(task_authority, "read", unavailable)
        monkeypatch.setattr(recovery, "recover", lambda *args: pytest.fail("uncertain actor must not restore"))
    else:
        monkeypatch.setattr(recovery, "recover", lambda *args: {"ok": False, "changed": False,
            "status": "CATALOG_RECOVERY_FAILED", "diagnostic": "invalid receipt"})
    callbacks = []
    def callback(command, **kwargs):
        callbacks.append((command, kwargs))
        return types.SimpleNamespace(returncode=native_exit, stdout=b"native\x00stdout", stderr=b"native\x00stderr\n")
    monkeypatch.setattr(subprocess, "run", callback)
    monkeypatch.setattr(lifecycle, "_hook_repository_root", lambda root, payload: root)
    assert recovery.main() == native_exit
    assert len(callbacks) == 1
    assert callbacks[0][0] == [str(executable), "audit-hook", "SessionStart", "--managed-hook-abi", lifecycle.MANAGED_HOOK_ABI]
    assert callbacks[0][1]["input"] == raw
    assert stdout.getvalue() == b"native\x00stdout"
    assert stderr.getvalue().startswith(b"native\x00stderr\n")
    assert b"CATALOG_RECOVERY_FAILED" in stderr.getvalue()


@pytest.mark.parametrize("edit", ["field", "backing", "receipt", "runtime", "legacy"])
def test_recovery_preserves_unowned_or_unknown_input(tmp_path, monkeypatch, pinned_test_thaliris, edit):
    executable, _ = pinned_test_thaliris
    home, root = install(tmp_path, monkeypatch, executable, policy=edit != "legacy")
    (root / ".codex" / "thaliris.json").unlink()
    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    if edit == "field":
        path = home / "config.toml"
        path.write_bytes(path.read_bytes().replace(catalog.MARKER.encode(), b"# user adoption\n"))
    elif edit == "backing":
        (home / catalog.NAME).write_bytes(b"user backing bytes")
    elif edit == "receipt":
        (home / maintenance.RECEIPT_NAME).write_bytes(b"invalid receipt")
    elif edit == "runtime":
        (home / runtime_identity.MANIFEST_NAME).write_bytes(b"invalid runtime")
    before = snapshot(home)
    result = recovery.recover(home, identity)
    assert snapshot(home) == before
    assert result["status"] in {"USER_CHANGED_PRESERVED", "CATALOG_CHANGED_PRESERVED", "CATALOG_RECOVERY_FAILED", "RECOVERY_POLICY_UNKNOWN"}, result


def test_uninstall_late_user_reference_retains_backing_and_archive(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, _ = install(tmp_path, monkeypatch, executable)
    backing = (home / catalog.NAME).read_bytes()
    original = catalog.apply
    def late_adoption(path, record, **kwargs):
        result = original(path, record, **kwargs)
        if kwargs.get("remove"):
            with (home / "config.toml").open("ab") as stream:
                stream.write(('\nmodel_catalog_json = ' + json.dumps(str(home / catalog.NAME)) + '\n').encode())
        return result
    with monkeypatch.context() as scoped:
        scoped.setattr(catalog, "apply", late_adoption)
        result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, executable, "codex-uninstall"))
    assert result["ok"], result
    assert (home / catalog.NAME).read_bytes() == backing
    assert result["native_model_catalog_compatibility"]["backing_artifact_status"] == "RETAINED_REFERENCE_SAFE"
    assert recovery.retained_record(home)["catalog_sha256"] == maintenance.digest(backing)


def test_reinstall_retained_backing_only_when_config_absent(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, _ = install(tmp_path, monkeypatch, executable)
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, executable, "codex-uninstall"))
    assert result["ok"], result
    assert catalog.KEY not in catalog.read(home)[1]
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, executable))
    assert result["ok"] and result["native_model_catalog_compatibility"]["status"] == "MANAGED", result


def test_old_reader_install_after_new_uninstall_then_reupgrade(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, _ = install(tmp_path, monkeypatch, executable)
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, executable, "codex-uninstall"))
    assert result["ok"], result
    original = subprocess.check_output(["git", "show", "324b9db^:src/thaliris_codex/host_maintenance.py"])
    historical = types.ModuleType("thaliris_codex.historical_maintenance")
    historical.__package__ = "thaliris_codex"
    exec(compile(original, "historical-host-maintenance.py", "exec"), historical.__dict__)
    result = historical.install(home, None, None, None, intent(tmp_path, home, executable))
    assert result["ok"], result
    assert json.loads((home / maintenance.RECEIPT_NAME).read_bytes())["format"] == maintenance.RECEIPT_FORMAT
    assert catalog.KEY not in catalog.read(home)[1]
    assert (home / catalog.NAME).is_file()
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, executable))
    assert result["ok"] and result["catalog_goal_met"] is True, result
    assert json.loads((home / maintenance.RECEIPT_NAME).read_bytes())["format"] == maintenance.CATALOG_RECEIPT_FORMAT


def test_restored_field_reinstall_replay_clears_one_generation_reclaim(tmp_path, monkeypatch, pinned_test_thaliris):
    from thaliris_codex import codex_app_server
    executable, _ = pinned_test_thaliris
    home, root = install(tmp_path, monkeypatch, executable)
    marker = root / ".codex" / "thaliris.json"
    marker.unlink()
    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    assert recovery.recover(home, identity)["status"] == "RESTORED_ABSENT"
    marker.write_bytes(adapter._PROJECT_ACTIVATION_BYTES)
    contract = intent(tmp_path, home, executable)
    def interrupted(*args):
        raise codex_app_server.CodexAppServerError("trust interrupted")
    with monkeypatch.context() as scoped:
        scoped.setattr(adapter, "_install_host_hook_trust", interrupted)
        pending = adapter.codex_install(maintenance_contract=contract)
    assert not pending["ok"] and pending["transition_pending"] is True, pending
    result = adapter.codex_install(maintenance_contract=contract)
    assert result["ok"] and result["catalog_goal_met"] is True, result
    receipt = json.loads((home / maintenance.RECEIPT_NAME).read_bytes())
    assert "restored" not in receipt[recovery.POLICY_KEY]
    # A later user deletion belongs to the user; a past restoration receipt
    # cannot silently insert the field again.
    assert catalog.apply(home, receipt[catalog.RECORD_KEY], remove=True)["status"] == "RESTORED_ABSENT"
    before = (home / "config.toml").read_bytes()
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, executable))
    assert result["ok"] and result["catalog_goal_met"] is False, result
    assert result["native_model_catalog_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert (home / "config.toml").read_bytes() == before


def test_pending_transition_defers_independent_recovery(tmp_path, monkeypatch, pinned_test_thaliris):
    from thaliris_codex import host_transition
    executable, _ = pinned_test_thaliris
    home, root = install(tmp_path, monkeypatch, executable)
    (root / ".codex" / "thaliris.json").unlink()
    (home / host_transition.NAME).write_bytes(b"pending transition requires its original contract")
    before = snapshot(home)
    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    result = recovery.recover(home, identity)
    assert not result["ok"] and result["status"] == "HOST_TRANSITION_PENDING"
    assert snapshot(home) == before


@pytest.mark.xfail(strict=True, reason="An external config writer can race the final comparison and atomic replacement; portable file compare-and-swap is unavailable")
def test_noncooperating_config_writer_in_replace_window_remains_preserved(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home, root = install(tmp_path, monkeypatch, executable)
    (root / ".codex" / "thaliris.json").unlink()
    original = adapter._atomic_host_write
    user_edit = b"\nuser_edit_after_final_compare = true\n"
    def concurrent_edit(path, contents):
        if path == home / "config.toml":
            with path.open("ab") as stream:
                stream.write(user_edit)
        return original(path, contents)
    monkeypatch.setattr(adapter, "_atomic_host_write", concurrent_edit)
    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    result = recovery.recover(home, identity)
    assert result["ok"], result
    assert user_edit in (home / "config.toml").read_bytes()


def real_session_start_install(tmp_path, monkeypatch, *, native_probe=False):
    import thaliris
    import thaliris_codex
    from thaliris_codex import runtime_setup, lifecycle, mode_hint_config, wait_guidance_config
    from tests.test_runtime_setup import source_wheel
    core_wheel = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter_wheel = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    if native_probe:
        # Instrument only the disposable fixture's actual console receiver.
        # This gives process-level evidence for exact stdin/count/exit routing;
        # production receiver behavior remains the default for every other call.
        import hashlib
        import zipfile
        wheel_path = Path(adapter_wheel.split("#", 1)[0])
        with zipfile.ZipFile(wheel_path) as wheel:
            entries = {name: wheel.read(name) for name in wheel.namelist()}
        entries["thaliris_codex/cli.py"] += b'''
_fixture_main = main
def main(argv=None):
    import os
    if os.environ.get("THALIRIS_TEST_NATIVE_PROBE") and sys.argv[1:3] == ["audit-hook", "SessionStart"]:
        raw = sys.stdin.buffer.read()
        with open(os.environ["THALIRIS_TEST_NATIVE_PROBE"], "ab") as stream:
            stream.write(len(raw).to_bytes(4, "little") + raw)
        sys.stdout.buffer.write(b"native\\x00stdout")
        sys.stderr.buffer.write(b"native\\x00stderr\\n")
        return 7
    return _fixture_main(argv)
'''
        with zipfile.ZipFile(wheel_path, "w") as wheel:
            for name, contents in entries.items():
                wheel.writestr(name, contents)
        adapter_wheel = str(wheel_path) + "#sha256=" + hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    created = runtime_setup.create(tmp_path / "independent pinned runtime", core_wheel, adapter_wheel)
    executable = Path(created["executable"])
    home = tmp_path / "callback home"
    root = tmp_path / "disappearing project"
    marker = root / ".codex" / "thaliris.json"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(adapter._PROJECT_ACTIVATION_BYTES)
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(mode_hint_config, "capability", lambda: "UNKNOWN")
    monkeypatch.setattr(wait_guidance_config, "capability", lambda: "UNKNOWN")
    supply(monkeypatch)
    expected = len(lifecycle.HOOK_EVENTS)
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *a: {
        "status": "TRUSTED", "trusted_count": expected, "enabled_count": expected, "changed": False})
    selection = {"executable": str(executable), "runtime_sha256": created["runtime_sha256"],
                 "source_pin": "sha256:" + adapter_wheel.rsplit("=", 1)[1]}
    contract = tmp_path / "callback-contract.json"
    contract.write_text(json.dumps({"format": maintenance.FORMAT, "operation": "codex-install",
        "codex_home": str(home), "human_instruction": "Install disposable fixture with project-loss restoration.",
        "executor": selection, "candidate": selection, "installed_runtime_sha256": "ABSENT",
        "execution_constraint": None, "catalog_recovery_project_root": str(root)}))
    assert adapter.codex_install(maintenance_contract=contract)["ok"]
    command = subprocess.list2cmdline([str(home / lifecycle.HOST_HOOK_SCRIPT_NAME), str(executable),
        maintenance.digest(executable.read_bytes()), created["runtime_sha256"], "SessionStart", str(lifecycle.MANAGED_HOOK_ABI)])
    return home, root, executable, command


@pytest.mark.skipif(os.name != "nt", reason="real Windows Host callback trampoline")
def test_real_session_start_recovers_without_project_checkout(tmp_path, monkeypatch):
    from thaliris_codex import lifecycle
    home, root, executable, command = real_session_start_install(tmp_path, monkeypatch)
    root.rename(tmp_path / "moved project")
    # No project checkout is importable from this unrelated cwd. The callback
    # must use the immutable installed wheel and keep native stdin untouched.
    for actor in [{"agent_id": "known-child"}, {"readonly": True}, {"fenced": True}]:
        before = snapshot(home)
        raw = b'\xef\xbb\xbf' + json.dumps({"session_id": "test", "cwd": str(tmp_path), **actor}).encode()
        denied = subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=tmp_path,
            env=runtime_identity.child_environment(), input=raw, capture_output=True, timeout=60)
        assert denied.returncode == 0 and b"ACTOR_RECOVERY_DENIED" in denied.stderr, denied.stderr
        assert snapshot(home) == before
    before = snapshot(home)
    malformed = subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=tmp_path,
        env=runtime_identity.child_environment(), input=b"not a native JSON payload", capture_output=True, timeout=60)
    assert malformed.returncode != 0 and b"CATALOG_RECOVERY_FAILED" in malformed.stderr
    assert snapshot(home) == before
    for invalid_payload in ({}, {"session_id": "test", "readonly": "true"},
                            {"session_id": "test", "fenced": 1},
                            {"session_id": "test", "agent_id": []}):
        malformed_actor = subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=tmp_path,
            env=runtime_identity.child_environment(), input=json.dumps(invalid_payload).encode(),
            capture_output=True, timeout=60)
        assert malformed_actor.returncode != 0 and b"CATALOG_RECOVERY_FAILED" in malformed_actor.stderr, malformed_actor.stderr
        assert snapshot(home) == before
    # A marker in another active cwd still gets the unchanged original native
    # audit receiver, with exact payload bytes and identity fields.
    marker_here = tmp_path / ".codex" / "thaliris.json"
    marker_here.parent.mkdir()
    marker_here.write_bytes(adapter._PROJECT_ACTIVATION_BYTES)
    raw = b'\xef\xbb\xbf' + json.dumps({"session_id": "child-session", "cwd": str(tmp_path), "agent_id": "child", "agent_type": "thaliris-verifier", "readonly": True}).encode()
    direct = subprocess.run([str(executable), "audit-hook", "SessionStart", "--managed-hook-abi", lifecycle.MANAGED_HOOK_ABI],
        cwd=tmp_path, env=runtime_identity.child_environment(), input=raw, capture_output=True, timeout=60)
    forwarded = subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=tmp_path,
        env=runtime_identity.child_environment(), input=raw, capture_output=True, timeout=60)
    assert forwarded.returncode == direct.returncode
    assert forwarded.stdout == direct.stdout
    assert b"ACTOR_RECOVERY_DENIED" in forwarded.stderr
    before_malformed_dispatch = snapshot(home)
    malformed_raw = json.dumps({"session_id": "test", "cwd": str(tmp_path), "readonly": "true"}).encode()
    direct_malformed = subprocess.run([str(executable), "audit-hook", "SessionStart", "--managed-hook-abi", lifecycle.MANAGED_HOOK_ABI],
        cwd=tmp_path, env=runtime_identity.child_environment(), input=malformed_raw, capture_output=True, timeout=60)
    forwarded_malformed = subprocess.run('cmd.exe /d /s /c "' + command + '"', cwd=tmp_path,
        env=runtime_identity.child_environment(), input=malformed_raw, capture_output=True, timeout=60)
    assert forwarded_malformed.stdout == direct_malformed.stdout
    assert not direct_malformed.stderr or direct_malformed.stderr in forwarded_malformed.stderr
    assert b"CATALOG_RECOVERY_FAILED" in forwarded_malformed.stderr
    assert snapshot(home) == before_malformed_dispatch
    marker_here.unlink()
    callback = subprocess.run('cmd.exe /d /s /c "' + command + '"',
        cwd=tmp_path, env=runtime_identity.child_environment(), input=b'{"session_id":"test","cwd":"unrelated"}',
        capture_output=True, timeout=60)
    assert callback.returncode == 0, callback.stderr.decode(errors="replace")
    assert b"RESTORED_ABSENT" in callback.stderr
    assert callback.stdout == b""
    assert catalog.KEY not in catalog.read(home)[1]
    assert (home / catalog.NAME).is_file()
    assert not root.exists()


@pytest.mark.skipif(os.name != "nt", reason="real Windows Host callback trampoline")
def test_real_session_start_isolates_auxiliary_failure_and_keeps_native_refusal(tmp_path, monkeypatch):
    import hashlib
    from thaliris import core
    from thaliris_codex import lifecycle, host_transition, task_authority
    home, recovery_root, executable, command = real_session_start_install(tmp_path, monkeypatch, native_probe=True)
    (recovery_root / ".codex" / "thaliris.json").unlink()
    project = tmp_path / "normal project"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    marker = project / ".codex" / "thaliris.json"
    marker.parent.mkdir()
    marker.write_bytes(adapter._PROJECT_ACTIVATION_BYTES)
    environment = runtime_identity.child_environment()
    environment["USERPROFILE"] = str(tmp_path / "isolated actor home")

    def invoke(cwd, raw, event="SessionStart", *, direct=False):
        if direct:
            call = [str(executable), "audit-hook", event, "--managed-hook-abi", lifecycle.MANAGED_HOOK_ABI]
        else:
            rendered = command if event == "SessionStart" else command.replace("SessionStart", event)
            call = 'cmd.exe /d /s /c "' + rendered + '"'
        return subprocess.run(call, cwd=cwd, env=environment, input=raw, capture_output=True, timeout=60)

    receipt = home / maintenance.RECEIPT_NAME
    original_receipt = receipt.read_bytes()
    receipt.write_bytes(b"invalid receipt retained for diagnosis")
    before = snapshot(home)
    unrelated_raw = b'\xef\xbb\xbf {"session_id":"unrelated","source":"startup"}\r\n'
    unrelated = invoke(tmp_path, unrelated_raw)
    assert unrelated.returncode == 0 and unrelated.stdout == b"", unrelated.stderr
    assert b"CATALOG_RECOVERY_FAILED" in unrelated.stderr
    assert snapshot(home) == before
    raw = b'\xef\xbb\xbf ' + json.dumps({"session_id": "normal", "source": "startup", "cwd": str(project)}).encode() + b"\r\n"
    direct = invoke(project, raw, direct=True)
    forwarded = invoke(project, raw)
    assert direct.returncode == forwarded.returncode == 0, (direct.stderr, forwarded.stderr)
    assert direct.stdout == forwarded.stdout
    assert json.loads(forwarded.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert b"CATALOG_RECOVERY_FAILED" in forwarded.stderr
    assert not direct.stderr or direct.stderr in forwarded.stderr
    assert snapshot(home) == before
    receipt.write_bytes(original_receipt)

    # Probe the actual installed console process: nonzero is not normalized by
    # Python, PowerShell or cmd; exact native bytes are delivered only once.
    probe_log = tmp_path / "native receiver probe.bin"
    environment["THALIRIS_TEST_NATIVE_PROBE"] = str(probe_log)
    receipt.write_bytes(b"invalid receipt retained for diagnosis")
    before = snapshot(home)
    direct = invoke(project, raw, direct=True)
    probe_log.unlink()
    forwarded = invoke(project, raw)
    assert direct.returncode == forwarded.returncode == 7
    assert direct.stdout == forwarded.stdout == b"native\x00stdout"
    assert forwarded.stderr.startswith(direct.stderr)
    assert b"CATALOG_RECOVERY_FAILED" in forwarded.stderr
    assert probe_log.read_bytes() == len(raw).to_bytes(4, "little") + raw
    assert snapshot(home) == before
    environment.pop("THALIRIS_TEST_NATIVE_PROBE")
    receipt.write_bytes(original_receipt)

    # Broken actor-check evidence cannot restore. SessionStart retains the
    # original receiver's empty result; managed control below still refuses.
    session_hash = hashlib.sha256(b"normal").hexdigest()
    association = project / ".context" / "audit" / "session-tasks" / (session_hash + ".json")
    association.parent.mkdir(parents=True, exist_ok=True)
    association.write_bytes(b"invalid association")
    before = snapshot(home)
    direct = invoke(project, raw, direct=True)
    forwarded = invoke(project, raw)
    assert direct.returncode == forwarded.returncode == 0, (direct.stderr, forwarded.stderr)
    assert direct.stdout == forwarded.stdout
    assert direct.stderr in forwarded.stderr and b"CATALOG_RECOVERY_FAILED" in forwarded.stderr
    assert snapshot(home) == before

    # Read actual damaged Authority only in a disposable user profile.
    task_id = "00000000-0000-0000-0000-000000000001"
    association.write_text(json.dumps({"version": 1, "task_id": task_id}), encoding="utf-8")
    prior_task = core.selected_task(project)
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "home", classmethod(lambda cls: Path(environment["USERPROFILE"])))
        core.select_task(project, task_id)
        authority_path = task_authority.path(project)
        core.select_task(project, prior_task)
    authority_path.parent.mkdir(parents=True)
    authority_path.write_bytes(b"invalid authority")
    before = snapshot(home)
    direct = invoke(project, raw, direct=True)
    forwarded = invoke(project, raw)
    assert forwarded.returncode == direct.returncode
    assert forwarded.stdout == direct.stdout
    assert b"CATALOG_RECOVERY_FAILED" in forwarded.stderr
    assert snapshot(home) == before
    control = {"session_id": "normal", "cwd": str(project), "tool_name": "exec_command",
               "tool_input": {"cmd": "thaliris task-update --role controller --base-revision 1 --input unauthorized.json"}}
    for actor in ({}, {"agent_id": "child", "agent_type": "thaliris-implementer"},
                  {"readonly": True}, {"fenced": True}):
        control_raw = json.dumps(control | actor).encode()
        direct = invoke(project, control_raw, "PreToolUse", direct=True)
        forwarded = invoke(project, control_raw, "PreToolUse")
        assert forwarded.returncode == direct.returncode
        assert forwarded.stdout == direct.stdout
        assert json.loads(forwarded.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert snapshot(home) == before
    association.unlink()

    # User edits remain preserved; a pending Host transaction remains a hard
    # preflight rejection rather than a successful restoration diagnostic.
    config = home / "config.toml"
    config.write_bytes(config.read_bytes().replace(catalog.MARKER.encode(), b"# user adoption\n"))
    before = snapshot(home)
    preserved = invoke(tmp_path, unrelated_raw)
    assert preserved.returncode == 0 and b"USER_CHANGED_PRESERVED" in preserved.stderr
    assert snapshot(home) == before
    journal = home / host_transition.NAME
    journal.write_bytes(b"unfinished maintenance must retain original evidence")
    before = snapshot(home)
    pending = invoke(project, raw)
    assert pending.returncode != 0 and b"HOST_TRANSITION_PENDING" in pending.stderr
    assert pending.stdout == b"" and snapshot(home) == before
    journal.unlink()
    before = snapshot(home)
    wrong_abi_command = command.rsplit(" ", 1)[0] + " invalid-abi"
    wrong_abi = subprocess.run('cmd.exe /d /s /c "' + wrong_abi_command + '"',
        cwd=project, env=environment, input=raw, capture_output=True, timeout=60)
    assert wrong_abi.returncode != 0 and wrong_abi.stdout == b""
    assert b"native SessionStart hook ABI differs" in wrong_abi.stderr
    assert snapshot(home) == before
    manifest = home / runtime_identity.MANIFEST_NAME
    manifest.write_bytes(b"changed startup identity")
    before = snapshot(home)
    rejected = invoke(project, raw)
    assert rejected.returncode != 0 and rejected.stdout == b""
    assert b"runtime manifest identity mismatch" in rejected.stderr
    assert snapshot(home) == before
