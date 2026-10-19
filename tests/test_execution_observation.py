"""Public retrieval and action routing preserve native/authority boundaries."""
import json
from pathlib import Path

from thaliris_codex import cli, controller_instructions, execution_observation, roles


def test_packaged_source_retrieval_is_readonly_without_task_or_home(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "absent-home"))
    assert cli.main(["--root", str(tmp_path), "execution-wait", "--tool-source"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source"] == execution_observation.TOOL_SOURCE
    assert Path("tools/owned_tool_wait.js").read_text(encoding="utf-8") == result["source"]
    assert "async function observeOwnedCommand" in result["source"]
    assert not list(tmp_path.iterdir())


def test_foreground_action_routes_unchanged_and_source_cannot_execute(tmp_path, monkeypatch, capsys):
    from thaliris_codex import execution_wait
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    captured = []
    monkeypatch.setattr(execution_wait, "main", lambda args: captured.append(args) or 7)
    assert cli.main(["--root", str(tmp_path), "execution-wait", "github", "--identity", "exact.json", "--receipt", "new"]) == 7
    assert captured == [["github", "--identity", "exact.json", "--receipt", "new"]]
    assert cli.main(["--root", str(tmp_path), "execution-wait", "--tool-source", "run"]) == 2
    assert "retrieval only" in capsys.readouterr().out
    assert len(captured) == 1


def test_one_canonical_selection_per_role_and_controller():
    text = execution_observation.INSTRUCTIONS.strip()
    for role in roles.role_choices():
        if role != "controller":
            assert roles.get_role(role).instructions.count(text) == 1
    assert controller_instructions.render().count(text) == 1


def test_pending_host_transition_allows_retrieval_but_refuses_execution(tmp_path, monkeypatch, capsys):
    from thaliris_codex import execution_wait, host_transition
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(host_transition, "pending", lambda home: True)
    monkeypatch.setattr(execution_wait, "main", lambda args: (_ for _ in ()).throw(AssertionError("must not execute")))
    assert cli.main(["--root", str(tmp_path), "execution-wait"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert cli.main(["--root", str(tmp_path), "execution-wait", "run"]) == 2
    assert "HOST_TRANSITION_PENDING" in capsys.readouterr().out
