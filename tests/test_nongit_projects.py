from pathlib import Path
import subprocess

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, codex_bootstrap, lifecycle, task_authority
from tests.test_task_authority import start, payload


@pytest.fixture
def nongit_project(tmp_path, monkeypatch, managed_role_profile_home):
    root = tmp_path / "explicit-project"
    root.mkdir()
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "authority")
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_bootstrap, "_trusted_executable", lambda: ["synthetic-installed-runtime"])
    # Exercise real project probe/init and admission. The installed executable
    # boundary is synthetic; no production Host installation is changed.
    monkeypatch.setattr(codex_bootstrap, "_invoke", lambda _exe, root, command:
        codex_adapter.bootstrap_check(root) if command == "bootstrap-check" else codex_adapter.init(root))
    return root


def test_nongit_bootstrap_admission_authority_and_continuation(nongit_project):
    root = nongit_project
    note = root / "notes.txt"
    note.write_bytes(b"preserve user bytes\r\n")
    result = codex_bootstrap.bootstrap(root)
    assert result["ok"] and result["status"] == "READY" and result["init_invoked"]
    second = codex_bootstrap.bootstrap(root)
    assert second["status"] == "READY" and not second["init_invoked"]
    # Before a session has navigation, an explicit project command from its
    # parent cwd may reach normal contract admission. It does not initialize
    # or adopt the parent as a managed project.
    assert lifecycle.handle_hook(root.parent, "PreToolUse", payload(root.parent,
        f'thaliris --root "{root}" task-start goal --authority-contract "{root / "authority.json"}"')) == ""
    admitted = start(root)
    assert admitted["status"] == "ACTIVE"
    anchor = task_authority.check(root)
    assert anchor["task_id"] == admitted["task_id"]
    assert anchor["project"] == str(root.resolve())
    assert anchor["host_actor_assurance"] == "UNKNOWN"
    assert codex_bootstrap.bootstrap(root)["status"] == "CURRENT_CONTINUATION"
    assert core.task_show(root)["state"]["task_surface_baseline"] == "UNAVAILABLE"
    assert core.task_show(root)["state"]["task_base_head"] is None
    assert core.task_candidate_observation(root)["paths"] is None
    child = {"agent_id": "known-child", "agent_type": "thaliris-reviewer"}
    assert "deny" in lifecycle.handle_hook(root.parent, "PreToolUse", payload(root.parent,
        "Set-Content example.py changed", **child))
    assert "deny" in lifecycle.handle_hook(root.parent, "PreToolUse", payload(root.parent,
        f'thaliris --root "{root}" task-start changed --authority-contract authority.json', **child))
    assert not (root / ".git").exists()
    assert not (root.parent / ".git").exists()
    assert not (root.parent / ".context").exists()
    assert note.read_bytes() == b"preserve user bytes\r\n"


def test_git_bootstrap_keeps_worktree_selection(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    nested = tmp_path / "nested"
    nested.mkdir()
    assert codex_bootstrap._repo_root(nested) == tmp_path.resolve()
    assert codex_bootstrap._repo_root(tmp_path) == core._repo_root(tmp_path)


def test_missing_git_executable_keeps_explicit_root(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")
    monkeypatch.setattr(codex_bootstrap.subprocess, "run", unavailable)
    assert codex_bootstrap._repo_root(tmp_path) == tmp_path.resolve()


@pytest.mark.parametrize("metadata_kind", ["broken_worktree", "corrupt_config", "bare_repository"])
def test_git_metadata_with_failed_discovery_stays_unknown(tmp_path, monkeypatch, metadata_kind):
    root = tmp_path / "project"
    root.mkdir()
    if metadata_kind == "broken_worktree":
        (root / ".git").write_text("gitdir: missing-worktree-metadata\n", encoding="utf-8")
    elif metadata_kind == "corrupt_config":
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[broken\n", encoding="utf-8")
    else:
        (root / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (root / "config").write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
        (root / "objects").mkdir()

    def discovery_failure(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, "", "fatal: metadata could not be read")

    monkeypatch.setattr(codex_bootstrap.subprocess, "run", discovery_failure)
    with pytest.raises(ValueError, match="UNKNOWN"):
        codex_bootstrap._repo_root(root)


def test_unexpected_git_discovery_error_without_metadata_stays_unknown(tmp_path, monkeypatch):
    def transient_failure(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, "", "fatal: transient discovery error")
    monkeypatch.setattr(codex_bootstrap.subprocess, "run", transient_failure)
    with pytest.raises(ValueError, match="UNKNOWN"):
        codex_bootstrap._repo_root(tmp_path)


def test_missing_git_executable_with_repository_metadata_stays_unknown(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(codex_bootstrap.subprocess, "run", unavailable)
    with pytest.raises(ValueError, match="UNKNOWN"):
        codex_bootstrap._repo_root(tmp_path)
