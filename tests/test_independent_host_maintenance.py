"""Emergency entry imports reviewed source even if ordinary entrypoints fail."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import thaliris
from thaliris_codex import host_maintenance, runtime_identity, runtime_setup
from tests.test_runtime_setup import source_wheel


@pytest.mark.parametrize("defect", ["operation", "unknown-runtime"])
def test_independent_entry_fails_closed_without_importing_installed_runtime(tmp_path, defect):
    import shutil
    core = tmp_path / "reviewed-core"
    shutil.copytree(Path(thaliris.__file__).parent, core / "src" / "thaliris")
    home = tmp_path / "broken-host"
    home.mkdir()
    (home / "thaliris-run.cmd").write_text("damaged launcher")
    (home / "thaliris-preflight.ps1").write_text("damaged preflight")
    contract = tmp_path / "contract.json"
    value = {"format": "thaliris-host-maintenance-v1", "operation": "task-start" if defect == "operation" else "codex-install",
             "human_instruction": "Recover this isolated test Host.", "codex_home": str(home),
             "executor": {"executable": str(tmp_path / "unknown.exe"), "runtime_sha256": "0" * 64,
                          "source_pin": "sha256:" + "0" * 64}}
    contract.write_text(json.dumps(value))
    before = {p.name: p.read_bytes() for p in home.iterdir()}
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(home), THALIRIS_EXECUTABLE=str(home / "missing.exe"),
                       THALIRIS_INSTALL_MANIFEST=str(home / "missing.json"))
    tool = Path(__file__).resolve().parents[1] / "tools" / "thaliris_host_maintenance.py"
    result = subprocess.run([sys.executable, "-I", "-B", str(tool), "--core-source-root", str(core),
                             "--maintenance-contract", str(contract)], env=environment,
                            capture_output=True, timeout=30)
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["ok"] is False and output["changed"] is False
    assert {p.name: p.read_bytes() for p in home.iterdir()} == before


@pytest.mark.skipif(os.name != "nt", reason="real Windows independent preflight and console dispatch")
def test_independent_entry_installs_into_isolated_home(tmp_path):
    """Exercise the standalone emergency install route in a disposable Host home.

    The synthetic contract is test-operator intent for this temporary home. The
    real Windows preflight, immutable runtime selection, console dispatch, and
    app-server hook trust path still run; no installed Host runner is invoked.
    """
    import shutil
    import thaliris_codex

    if shutil.which("codex") is None:
        pytest.skip("Codex app-server CLI is required for an end-to-end isolated install")

    reviewed_core = tmp_path / "reviewed-core"
    shutil.copytree(Path(thaliris.__file__).parent, reviewed_core / "src/thaliris")
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    runtime = runtime_setup.create(tmp_path / "approved-runtime", core, adapter)
    executable = Path(runtime["executable"])
    selection = {"executable": str(executable), "runtime_sha256": runtime["runtime_sha256"],
                 "source_pin": "sha256:" + adapter.rsplit("=", 1)[1]}

    home = tmp_path / "isolated-codex-home"
    home.mkdir()
    contract = tmp_path / "isolated-install.json"
    contract.write_text(json.dumps({
        "format": host_maintenance.FORMAT,
        "operation": "codex-install",
        "human_instruction": "Install this exact fixture into its disposable test Host home.",
        "codex_home": str(home),
        "executor": selection,
        "candidate": selection,
        "installed_runtime_sha256": "ABSENT",
        "execution_constraint": None,
    }), encoding="utf-8")

    tool = Path(__file__).resolve().parents[1] / "tools/thaliris_host_maintenance.py"
    environment = runtime_identity.child_environment()
    environment["CODEX_HOME"] = str(home)
    environment["PYTHONPATH"] = str(home)
    environment["THALIRIS_EXECUTABLE"] = str(home / "missing.exe")
    environment["THALIRIS_INSTALL_MANIFEST"] = str(home / "missing-manifest.json")
    environment.pop("THALIRIS_RUN_SCRIPT", None)
    command = [sys.executable, "-I", "-B", str(tool), "--core-source-root", str(reviewed_core),
               "--maintenance-contract", str(contract)]

    installed = subprocess.run(command, env=environment, capture_output=True, timeout=120)

    assert installed.returncode == 0, installed.stdout or installed.stderr
    result = json.loads(installed.stdout)
    assert result["ok"] and result["host_integration_ready"] == "YES", result
    assert result["host_actor_assurance"] == "UNKNOWN"
    assert result["project_files_touched"] == []
    assert result["installed_runtime_identity"] == runtime["runtime_sha256"]
    assert (home / runtime_identity.MANIFEST_NAME).is_file()
    assert (home / host_maintenance.RECEIPT_NAME).is_file()
    assert (home / "hooks.json").is_file()
    assert (home / "AGENTS.md").is_file()


@pytest.mark.skipif(os.name != "nt", reason="real Windows independent preflight and console dispatch")
def test_independent_entry_removes_explicitly_approved_broken_legacy_controls(tmp_path):
    """Real subprocess and PowerShell, no installed runner or trust-test seam.

    Narrow exact approval is test-operator intent, not permission to approve
    drift in a production installation or proof of live Codex activation.
    """
    import shutil
    import thaliris_codex
    reviewed_core = tmp_path / "reviewed-core"
    shutil.copytree(Path(thaliris.__file__).parent, reviewed_core / "src/thaliris")
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    runtime = runtime_setup.create(tmp_path / "approved-runtime", core, adapter)
    exe = Path(runtime["executable"])
    contents = runtime_identity.manifest_bytes(exe)
    home = tmp_path / "broken-disposable-host"
    home.mkdir()
    controls = {"thaliris-run.cmd": b"broken runner", "thaliris-hook.cmd": b"broken hook",
                "thaliris-preflight.ps1": b"broken preflight"}
    for name, data in controls.items():
        (home / name).write_bytes(data)
    (home / runtime_identity.MANIFEST_NAME).write_bytes(contents)
    selection = {"executable": str(exe), "runtime_sha256": runtime["runtime_sha256"],
                 "source_pin": "sha256:" + adapter.rsplit("=", 1)[1]}
    contract = tmp_path / "explicit-recovery.json"
    value = {"format": host_maintenance.FORMAT, "operation": "codex-uninstall",
             "human_instruction": "Remove these exact reviewed broken controls in the disposable test Host.",
             "codex_home": str(home), "executor": selection,
             "installed_runtime_sha256": runtime["runtime_sha256"], "legacy_owned_bytes": {}}
    tool = Path(__file__).resolve().parents[1] / "tools/thaliris_host_maintenance.py"
    environment = runtime_identity.child_environment()
    # Pollution and broken installed entrypoints cannot route the import.
    environment.update(PYTHONPATH=str(home), THALIRIS_RUN_SCRIPT=str(home / "thaliris-run.cmd"))
    command = [sys.executable, "-I", "-B", str(tool), "--core-source-root", str(reviewed_core),
               "--maintenance-contract", str(contract)]
    contract.write_text(json.dumps(value), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in home.iterdir()}
    rejected = subprocess.run(command, env=environment, capture_output=True, timeout=60)
    assert rejected.returncode != 0
    assert {p.name: p.read_bytes() for p in home.iterdir()} == before
    value["legacy_owned_bytes"] = {name: host_maintenance.digest(data) for name, data in controls.items()}
    contract.write_text(json.dumps(value), encoding="utf-8")
    environment.pop("THALIRIS_RUN_SCRIPT")
    recovered = subprocess.run(command, env=environment, capture_output=True, timeout=60)
    assert recovered.returncode == 0, recovered.stdout or recovered.stderr
    result = json.loads(recovered.stdout)
    assert result["ok"] and result["status"] == "UNINSTALLED"
    assert not result["project_files_touched"] and result["host_actor_assurance"] == "UNKNOWN"
    assert all(not (home / name).exists() for name in controls)
    assert not (home / runtime_identity.MANIFEST_NAME).exists()
    assert result["runtime_audit_records"]
    assert runtime_identity.manifest_bytes(exe) == contents
