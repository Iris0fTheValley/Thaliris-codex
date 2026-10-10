"""Focused cross-layer evidence for native execution and selected instructions."""
import json
from pathlib import Path
import tomllib

from thaliris_codex import cli, codex_adapter, controller_instructions, lifecycle, roles, task_authority


def test_controller_retrieval_is_readonly_before_admission_and_during_conflict(tmp_path, monkeypatch, capsys):
    def unavailable(*_args, **_kwargs):
        raise ValueError("damaged authority")
    monkeypatch.setattr(task_authority, "check", unavailable)
    before = list(tmp_path.iterdir())
    assert cli.main(["--root", str(tmp_path), "controller-instructions"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"]
    text = result["content"]
    assert "--section startup" in text and "--section host-maintenance" in text
    assert "task-recover-authority" not in text
    for section in controller_instructions.SECTIONS:
        assert cli.main(["--root", str(tmp_path), "controller-instructions", "--section", section]) == 0
        selected = json.loads(capsys.readouterr().out)["content"]
        assert selected == controller_instructions.render(
            controller_instructions.runner_command(codex_adapter._codex_home() / lifecycle.HOST_RUN_SCRIPT_NAME), section=section)
        assert selected.count("\n## ") == 0
    assert "@RUNNER@" not in text and "@ROLE_ROWS@" not in text
    assert list(tmp_path.iterdir()) == before


def test_hook_retrieval_during_authority_conflict_grants_no_control_or_compound_exemption(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    authority_path = tmp_path / ".context" / "audit" / "task-authority.json"
    monkeypatch.setattr(task_authority, "path", lambda _root: authority_path)
    authority_path.parent.mkdir(parents=True)
    authority_path.write_text("{damaged authority", encoding="utf-8")
    original = authority_path.read_bytes()
    def unavailable(*_args, **_kwargs):
        raise ValueError("damaged authority")
    monkeypatch.setattr(task_authority, "read", unavailable)
    payload = {"session_id": "unknown", "tool_name": "Bash", "tool_input": {
        "command": "thaliris controller-instructions",
    }}
    assert lifecycle.handle_hook(tmp_path, "PreToolUse", payload) == ""
    payload["tool_input"]["command"] = "thaliris controller-instructions --section task-recovery"
    assert lifecycle.handle_hook(tmp_path, "PreToolUse", payload) == ""
    assert lifecycle._controller_actor_assurance(payload) == "UNKNOWN"
    payload["tool_input"]["command"] = "thaliris controller-instructions --unexpected"
    assert lifecycle.handle_hook(tmp_path, "PreToolUse", payload) == ""
    payload["tool_input"]["command"] += "; thaliris task-close --base-revision 1"
    assert "THALIRIS_TASK_AUTHORITY_UNAVAILABLE" in lifecycle.handle_hook(tmp_path, "PreToolUse", payload)
    assert authority_path.read_bytes() == original


def test_inherited_spans_select_entry_without_bulk_controller_procedures():
    project = codex_adapter.render_managed()
    global_span = codex_adapter._global_agents_block().decode()
    for inherited in (project, global_span):
        assert "Controller" in inherited and "controller-instructions" in inherited
        for low_frequency in ("task-recover-authority", "--expected-sha256", "FOREIGN_RECOVERY_DECISION",
                              "OPERATOR_ASSERTED_USER_DELEGATED_ADMINISTRATION"):
            assert low_frequency not in inherited
            assert low_frequency in controller_instructions.render()
    assert "selected spawn handoff without parent conversation history" in project
    assert "readonly" in global_span and "human decision" in global_span


def test_current_role_profiles_preserve_local_iteration_and_selected_context():
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = tomllib.loads(codex_adapter._agent_profile(name.removesuffix(".toml"), role, model, effort).decode())
        text = profile["developer_instructions"]
        assert "selected native spawn handoff is your task-specific input" in text
        assert "task-recover-authority" not in text and "codex-bootstrap" not in text
        if role in {"implementer", "focused-implementer"}:
            assert "repair ordinary local defects" in text
            assert "implementation methods" in text
        if role == "focused-implementer":
            assert "full reasoning, implementation, runtime-feedback and revision loop" in text
            assert "fresh ordinary Implementer" in text
            assert "PASS alone is insufficient" in text


def test_controller_and_native_profile_artifacts_are_generated_from_sources():
    assert Path("docs/thaliris-controller.md").read_text(encoding="utf-8") == controller_instructions.render()
    assert Path("docs/thaliris-role-packs.md").read_text(encoding="utf-8") == codex_adapter.render_role_packs()
    for name, (model, effort, role) in roles.agent_profiles().items():
        assert Path(".codex/agents", name).read_bytes() == codex_adapter._agent_profile(name.removesuffix(".toml"), role, model, effort)


def test_init_preserves_unknown_controller_document(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    target = tmp_path / "docs" / "thaliris-controller.md"
    target.parent.mkdir()
    target.write_text("user-owned controller notes", encoding="utf-8")
    result = codex_adapter.init(tmp_path)
    assert "docs/thaliris-controller.md" in result["preserved_manual_followup"]
    assert target.read_text(encoding="utf-8") == "user-owned controller notes"
