"""The release gate consumes the already-built bytes, never builds replacements."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from thaliris_codex import codex_adapter, host_maintenance, lifecycle, release_identity as identity
from thaliris_codex import release_manager as manager, runtime_identity


@pytest.fixture(scope="module")
def bundle():
    directory = os.environ.get("THALIRIS_RELEASE_BUNDLE")
    if not directory:
        pytest.skip("set THALIRIS_RELEASE_BUNDLE to an already-built final bundle")
    directory = Path(directory).absolute()
    raw = (directory / "release.json").read_bytes()
    binding = identity.binding(raw, identity.sha256(raw))
    wheels = {name: directory / artifact["filename"] for name, artifact in binding["manifest"]["artifacts"].items()}
    for name, path in wheels.items():
        assert identity.sha256(path.read_bytes()) == binding["manifest"]["artifacts"][name]["sha256"]
    return directory, binding, wheels


def test_gate_executor_is_the_built_adapter_and_core(bundle):
    _directory, binding, _wheels = bundle
    import thaliris_codex
    # A gate accidentally importing an editable checkout cannot establish
    # artifact acceptance, even if its source happens to resemble the wheel.
    identity.validate_selected({"release_binding": binding,
        "source_pin": "sha256:" + binding["manifest"]["artifacts"]["adapter"]["sha256"]},
        {"package_dir": str(Path(thaliris_codex.__file__).parent)})


def test_exact_bundle_runtime_reuse_core_binding_and_disposable_host(tmp_path, monkeypatch, bundle):
    directory, binding, wheels = bundle
    cache = tmp_path / "final physical runtime cache"
    selected = manager.prepare(cache, binding, wheels)
    executable = Path(selected["executable"])
    original = runtime_identity.manifest_bytes(executable)
    assert manager.prepare(cache, binding, wheels) == selected
    assert runtime_identity.manifest_bytes(executable) == original
    assert len(list(cache.glob("runtime-*"))) == 1
    # Candidate and manifest together must not relabel an unchanged Core.
    wrong = copy.deepcopy(binding["manifest"])
    wrong["artifacts"]["core"]["sha256"] = "0" * 64
    wrong_binding = identity.binding(identity.canonical(wrong), identity.sha256(identity.canonical(wrong)))
    wrong_selected = {**selected, "release_binding": wrong_binding}
    with pytest.raises(ValueError, match="core archive"):
        host_maintenance.selected_runtime(wrong_selected)
    home = tmp_path / "disposable-host"
    home.mkdir()
    (home / "config.toml").write_text('model_catalog_json = "user-owned-catalog.json"\n')
    (home / "user-data.txt").write_text("preserve")
    monkeypatch.setenv("CODEX_HOME", str(home))
    # Real candidate console renders the plan. Native Codex hook trust is a
    # separately controlled Host boundary, modeled only for this temporary home.
    planned = manager._run(str(executable), ["codex-maintenance-plan", "codex-install", "--executable", str(executable),
        "--source-pin", selected["source_pin"], "--human-instruction", "Install these exact release artifacts in the disposable test Host."],
        home=home, project=tmp_path)
    assert planned["ok"], planned
    contract = planned["maintenance_contract"]
    contract.update(candidate=selected, executor=selected)
    path = tmp_path / "approved-plan.json"
    path.write_bytes(identity.canonical(contract))
    monkeypatch.setattr(codex_adapter, "_install_host_hook_trust", lambda *args: {
        "status": "TRUSTED", "trusted_count": len(lifecycle.HOOK_EVENTS), "enabled_count": len(lifecycle.HOOK_EVENTS), "changed": False})
    installed = codex_adapter.codex_install(maintenance_contract=path)
    assert installed["ok"], installed
    receipt = json.loads((home / host_maintenance.RECEIPT_NAME).read_bytes())
    assert receipt["release_binding"] == binding
    assert (home / runtime_identity.MANIFEST_NAME).read_bytes() == original
    assert (home / "user-data.txt").read_text() == "preserve"
    # Same release update uses independently validated bytes and a new plan,
    # preserving normal ownership/transition semantics for repair/no-op.
    updated = manager._run(str(executable), ["codex-maintenance-plan", "codex-install", "--executable", str(executable),
        "--source-pin", selected["source_pin"], "--human-instruction", "Repair this exact release in the disposable test Host."],
        home=home, project=tmp_path)
    updated["maintenance_contract"].update(candidate=selected, executor=selected)
    retry = tmp_path / "repair-plan.json"
    retry.write_bytes(identity.canonical(updated["maintenance_contract"]))
    repaired = codex_adapter.codex_install(maintenance_contract=retry)
    assert repaired["ok"], repaired
    assert runtime_identity.manifest_bytes(executable) == original
    diagnostic = manager.status(home, cache, binding, tmp_path)
    assert diagnostic["loaded_host"] == "UNKNOWN"
    assert diagnostic["installed_disk"]["release_binding"] == binding
    current_project = tmp_path / "current-release-project"
    current_project.mkdir()
    codex_adapter.init(current_project)
    monkeypatch.setattr(manager, "_run", lambda *_args, **_kwargs: {
        "ok": True, "expected_managed_instruction_sha256": "f" * 64,
        "session_restart_required": False,
    })
    skewed = manager.status(home, cache, binding, current_project)
    assert skewed["project_host_relation"] == "HOST_UPDATE_REQUIRED"
    assert skewed["project_host_relation_reason"] == "project_matches_current_reader_but_not_installed_reader"
    assert skewed["loaded_host"] == skewed["restart_required"] == "UNKNOWN"
    # Runtime drift is a cache miss: never repair/overwrite the original tree.
    package_file = Path(json.loads(original)["package_dir"]) / "__init__.py"
    package_file.write_bytes(package_file.read_bytes() + b"\n# simulated runtime drift\n")
    damaged = package_file.read_bytes()
    replacement = manager.prepare(cache, binding, wheels)
    assert replacement["executable"] != selected["executable"]
    assert package_file.read_bytes() == damaged
    assert len(list(cache.glob("runtime-*"))) == 2


def test_system_python_bootstrap_uses_staged_bundle_without_checkout(tmp_path, bundle):
    directory, binding, _wheels = bundle
    blank = tmp_path / "no-checkout"
    blank.mkdir()
    result = subprocess.run([sys.executable, "-I", "-B", str(directory / "thaliris-bootstrap.py"), "prepare",
        "--manifest", str(directory / "release.json"), "--manifest-sha256", binding["manifest_sha256"],
        "--artifacts", str(directory), "--cache", str(tmp_path / "final-runtime-cache"), "--project", str(blank),
        "--home", str(tmp_path / "home")], cwd=blank, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr + result.stdout
    out = json.loads(result.stdout)
    assert out["selected"]["release_binding"] == binding
    assert out["host_installed"] is False
    assert not (tmp_path / "home").exists()
    assert list(blank.iterdir()) == []
