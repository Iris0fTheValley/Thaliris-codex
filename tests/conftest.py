from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def pinned_test_thaliris(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Supply a fake exact executable identity for Host installer unit tests."""
    from thaliris_codex import codex_adapter, codex_app_server, lifecycle

    venv = tmp_path / "test-runtime"
    executable = venv / "Scripts" / "test-host-executable.exe"
    executable.parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = test\ninclude-system-site-packages = false\n", encoding="utf-8")
    package = venv / "Lib" / "site-packages" / "thaliris_codex"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text("def main(): pass\n", encoding="utf-8")
    (package / "lifecycle.py").write_text("HOOK_ABI = 10\n", encoding="utf-8")
    commit = "1" * 40
    dist_info = venv / "Lib" / "site-packages" / "thaliris_codex-0.4.3.dist-info"
    dist_info.mkdir()
    (dist_info / "direct_url.json").write_text(json.dumps({
        "url": "https://example.test/approved-adapter",
        "vcs_info": {"vcs": "git", "commit_id": commit},
    }), encoding="utf-8")
    executable.write_bytes(b"test-only direct Thaliris executable identity")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    monkeypatch.setattr(
        codex_adapter,
        "_host_install_executable",
        lambda _home, _path, _sha: (executable, digest, None),
    )

    trusted_homes: set[Path] = set()

    def trust_host_hooks(home: Path, _exe: Path, _sha: str, _runtime_sha: str):
        resolved_home = home.resolve()
        changed = resolved_home not in trusted_homes
        trusted_homes.add(resolved_home)
        expected = len(lifecycle.HOOK_EVENTS)
        return {
            "status": "TRUSTED",
            "trusted_count": expected,
            "enabled_count": expected,
            "expected_count": expected,
            "changed": changed,
            "config_path": str(home / "config.toml") if changed else None,
            "keys": [f"host-key:{event}" for event in lifecycle.HOOK_EVENTS],
        }

    monkeypatch.setattr(codex_adapter, "_install_host_hook_trust", trust_host_hooks)
    monkeypatch.setattr(
        codex_app_server,
        "owned_hook_keys_from_host",
        lambda _home, commands: [
            f"host-key:{event}:{index}"
            for event, handlers in commands.items()
            for index, _command in enumerate(sorted(handlers))
        ],
    )
    monkeypatch.setattr(codex_app_server, "remove_owned_hook_trust", lambda _home, keys: len(keys))
    from thaliris_codex import host_maintenance, runtime_identity
    selection = {
        "executable": str(executable),
        "runtime_sha256": host_maintenance.digest(runtime_identity.manifest_bytes(executable)),
        "source_pin": "git+https://example.test/approved-adapter@" + commit,
    }
    (tmp_path / ".test-host-runtime-selection.json").write_text(
        json.dumps(selection, sort_keys=True), encoding="utf-8"
    )
    return executable, digest
