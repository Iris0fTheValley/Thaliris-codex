"""Real Python/pip source-fixture evidence for the dedicated runtime boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from thaliris_codex import runtime_setup, runtime_identity, host_maintenance, codex_adapter


def source_wheel(tmp_path, name, package, *, entry=False):
    """Pack current test source as a disposable fixture, not a release artifact."""
    path = tmp_path / f"{name}-0.4.3-py3-none-any.whl"
    info = f"{name}-0.4.3.dist-info"
    with zipfile.ZipFile(path, "w") as wheel:
        for source in package.rglob("*.py"):
            wheel.write(source, name + "/" + source.relative_to(package).as_posix())
        wheel.writestr(info + "/METADATA", f"Metadata-Version: 2.1\nName: {name.replace('_', '-')}\nVersion: 0.4.3\n")
        wheel.writestr(info + "/WHEEL", "Wheel-Version: 1.0\nGenerator: source-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr(info + "/RECORD", "")
        if entry:
            wheel.writestr(info + "/entry_points.txt", "[console_scripts]\nthaliris = thaliris_codex.cli:main\n")
    return str(path) + "#sha256=" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_python311_pip_bootstrap_creates_runtime_without_pth_repair(tmp_path, monkeypatch):
    import thaliris
    import thaliris_codex
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    # The caller may contain executable .pth/setuptools; no bytes from that
    # startup machinery are copied into the target's importable environment.
    target = tmp_path / "dedicated-runtime"
    result = runtime_setup.create(target, core, adapter)
    assert result["ok"]
    assert not list(target.rglob("*.pth"))
    assert not list(target.rglob("setuptools*"))
    assert not list(target.rglob("pip-*.dist-info"))
    executable = Path(result["executable"])
    before = runtime_identity.manifest_bytes(executable)
    selection = {"executable": str(executable), "runtime_sha256": result["runtime_sha256"],
                 "source_pin": "sha256:" + adapter.rsplit("=", 1)[1]}
    assert host_maintenance.selected_runtime(selection)[0] == executable
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    # Exercise the real interpreter origin and native console-launcher ABI
    # probe; actual Codex trust/catalog loading stays outside this fixture.
    probe = codex_adapter._host_install_executable(home, executable, json.loads(before)["executable_sha256"])
    assert probe[2] is None, probe
    assert runtime_identity.manifest_bytes(executable) == before
    from thaliris_codex import codex_bootstrap, lifecycle
    expected = len(lifecycle.HOOK_EVENTS)
    monkeypatch.setattr(codex_adapter, "_install_host_hook_trust", lambda *a: {
        "status": "TRUSTED", "trusted_count": expected, "enabled_count": expected, "changed": False})
    contract = tmp_path / "approved-fixture-install.json"
    contract.write_text(json.dumps({"format": host_maintenance.FORMAT, "operation": "codex-install",
        "codex_home": str(home), "human_instruction": "Install source fixture into disposable test home.",
        "executor": selection, "candidate": selection, "installed_runtime_sha256": "ABSENT",
        "execution_constraint": None}), encoding="utf-8")
    installed = codex_adapter.codex_install(maintenance_contract=contract)
    assert installed["ok"], installed
    project = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "docs").mkdir()
    (project / "docs/thaliris-role-packs.md").write_bytes(b"user-owned role description")
    # Bootstrap executes the installed console launcher and installed Core,
    # rather than a development _invoke or executable substitute.
    ready = codex_bootstrap.bootstrap(project)
    assert ready["status"] == "DEFINITION_READY_ACTOR_UNKNOWN", ready
    assert (project / "docs/thaliris-role-packs.md").read_bytes() == b"user-owned role description"
    assert runtime_identity.manifest_bytes(executable) == before
    with pytest.raises(ValueError, match="already exists"):
        runtime_setup.create(target, core, adapter)
    assert runtime_identity.manifest_bytes(executable) == before


def test_runtime_setup_rejects_unpinned_or_changed_artifacts_before_create(tmp_path):
    target = tmp_path / "runtime"
    with pytest.raises(ValueError, match="immutable"):
        runtime_setup.create(target, "git+https://example.test/core@main", "unreviewed")
    assert not target.exists()
    artifact = tmp_path / "test.whl"
    artifact.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="artifact identity mismatch"):
        runtime_setup.create(target, str(artifact) + "#sha256=" + "0" * 64, "unreviewed")
    assert not target.exists()
