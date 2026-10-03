from pathlib import Path

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, runtime_identity


def test_adapter_uses_external_shared_core():
    adapter_root = Path(codex_adapter.__file__).parent
    assert adapter_root.name == "thaliris_codex"
    assert Path(core.__file__).parent.name == "thaliris"
    assert not (adapter_root / "core.py").exists()
    assert codex_adapter.core is core


def test_runtime_manifest_pins_shared_core_bytes(pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    shared_core = executable.parent.parent / "Lib/site-packages/thaliris/core.py"
    shared_core.parent.mkdir()
    shared_core.write_bytes(b"reviewed shared Core bytes")
    raw = runtime_identity.manifest_bytes(executable)
    identity = runtime_identity.manifest_identity(raw)
    record = runtime_identity.validate_manifest(raw, executable, identity)
    assert "Lib/site-packages/thaliris/core.py" in record["files"]
    assert Path(record["package_dir"]).name == "thaliris_codex"
    shared_core.write_bytes(b"changed shared Core")
    with pytest.raises(ValueError, match="installed Thaliris runtime changed"):
        runtime_identity.validate_manifest(raw, executable, identity)
