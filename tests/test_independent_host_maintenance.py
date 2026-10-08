"""Emergency entry imports reviewed source even if ordinary entrypoints fail."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import thaliris


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
