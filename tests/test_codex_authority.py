"""Authority contracts through Core, without a Codex Host or CLI."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from thaliris import authority, core


def intent(mode="delegated"):
    return {"human_instruction": "Repair the example", "boundary": "Example module",
            "invariants": "Keep public behavior", "acceptance": "Focused checks pass", "execution_mode": mode}


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    core.init(root)
    return authority.AuthorityStore(root, tmp_path / "external", protected_paths=(".context/config.json", "host/security.json"))


def start(store, mode="delegated"):
    core.task_start(store.root, "Repair the example", None, None, actor="controller")
    return store.establish(core.task_show(store.root)["state"], intent(mode))


























def test_codex_recovery_checks_anchor_and_resolves_native_paths_under_core_lock(store, monkeypatch):
    from thaliris_codex import task_authority

    monkeypatch.setattr(task_authority, "directory", lambda: store.directory)
    core.task_start(store.root, "Repair the example", None, None)
    task_authority.establish(store.root, core.task_show(store.root)["state"], intent(), "session-fact")
    expected = authority.digest(task_authority.path(store.root))
    original_lock, original_digest = core._lock, authority.digest
    locked = False

    @contextmanager
    def observed_lock(root):
        nonlocal locked
        with original_lock(root):
            locked = True
            try:
                yield
            finally:
                locked = False

    def checked_digest(path):
        assert locked, "recovery must wait for the ledger lock before inspecting authority/evidence"
        return original_digest(path)

    monkeypatch.setattr(core, "_lock", observed_lock)
    monkeypatch.setattr(authority, "digest", checked_digest)
    monkeypatch.setattr(task_authority, "digest", checked_digest)
    assert task_authority.recover(store.root, expected, "Preserve serialized Codex recovery")["ok"]
    with pytest.raises(ValueError, match="TASK_AUTHORITY_CHANGED"):
        task_authority.recover(store.root, "0" * 64, "Keep legacy conflict error")




def test_codex_facade_keeps_legacy_record_shape_and_bytes(store, monkeypatch):
    from thaliris_codex import task_authority

    monkeypatch.setattr(task_authority, "directory", lambda: store.directory)
    core.task_start(store.root, "Repair the example", None, None)
    state = core.task_show(store.root)["state"]
    paths = (*task_authority.SECURITY_PATHS, ".context/state.json")
    expected = {
        "version": 1, "project": str(store.root.resolve()), "task_id": state["task_id"], "goal": state["goal"],
        "contract": intent(), "status": "ACTIVE", "provenance": "CONTROLLER_ASSERTED_HUMAN_INSTRUCTION",
        "host_actor_assurance": "UNKNOWN", "origin_session_hash": "explicit-session-fact",
        "state_sha256": authority.digest(store.root / ".context/state.json"), "lifecycle_sha256": "ABSENT",
        "security": {name: authority.digest(store.root / name) for name in task_authority.SECURITY_PATHS},
        "fenced_sessions": [], "fenced_agents": [], "history": [],
        "snapshots": {name: base64.b64encode((store.root / name).read_bytes()).decode()
                      if (store.root / name).is_file() else None for name in paths},
    }
    assert task_authority.establish(store.root, state, intent(), "explicit-session-fact") == expected
    assert task_authority.path(store.root).read_bytes() == (json.dumps(expected, sort_keys=True, indent=2) + "\n").encode()
    assert task_authority.read(store.root) == expected
