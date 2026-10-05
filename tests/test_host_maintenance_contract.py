from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from thaliris_codex import codex_adapter as adapter, codex_bootstrap, host_maintenance as maintenance, lifecycle, runtime_identity


def intent(tmp_path, home, exe, operation="codex-install", *, legacy=None):
    metadata = exe.parent.parent / "Lib/site-packages/thaliris_codex-0.4.3.dist-info/direct_url.json"
    if not metadata.exists():
        metadata.parent.mkdir()
        metadata.write_text(json.dumps({"url": "https://example.test/approved-adapter",
            "vcs_info": {"vcs": "git", "commit_id": "1" * 40}}))
    selected = {"executable": str(exe), "runtime_sha256": maintenance.digest(runtime_identity.manifest_bytes(exe)),
                "source_pin": "git+https://example.test/approved-adapter@" + "1" * 40}
    prior = home / runtime_identity.MANIFEST_NAME
    value = {"format": maintenance.FORMAT, "operation": operation, "codex_home": str(home),
             "human_instruction": "The human requests this exact reviewed Host maintenance operation.",
             "executor": selected, "installed_runtime_sha256": maintenance.digest(prior.read_bytes()) if prior.exists() else "ABSENT",
             "legacy_owned_bytes": legacy or {}}
    if operation == "codex-install":
        value.update(candidate=selected, execution_constraint=None)
    path = tmp_path / (operation + ".json")
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def snapshot(home):
    return {p.relative_to(home).as_posix(): p.read_bytes() for p in home.rglob("*") if p.is_file()} if home.exists() else {}


@pytest.fixture
def installed(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    exe, _ = pinned_test_thaliris
    path = intent(tmp_path, home, exe)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"] is True, result
    return home, exe


def test_unknown_with_intent_clean_install_and_project_admission(tmp_path, monkeypatch, installed):
    home, exe = installed
    assert lifecycle._controller_actor_assurance({}) == "UNKNOWN"
    subprocess.run(["git", "init", "-q", str(tmp_path / "project")], check=True)
    project = tmp_path / "project"
    (project / "docs").mkdir()
    documentation = b"User-owned role descriptions and changed docs.\r\n"
    (project / "docs/thaliris-role-packs.md").write_bytes(documentation)
    result = adapter.init(project)
    assert result["project_definition_present"] == "YES"
    assert result["manual_action_required"] == []
    assert "docs/thaliris-role-packs.md" in result["preserved_manual_followup"]
    assert (project / "docs/thaliris-role-packs.md").read_bytes() == documentation
    monkeypatch.setattr(codex_bootstrap, "_trusted_executable", lambda: [str(exe)])
    monkeypatch.setattr(codex_bootstrap, "_invoke", lambda _e, r, command: adapter.bootstrap_check(r) if command == "bootstrap-check" else adapter.init(r))
    ready = codex_bootstrap.bootstrap(project)
    assert ready["status"] == "DEFINITION_READY_ACTOR_UNKNOWN"
    assert ready["host_role_catalog_status"] == "UNKNOWN" if "host_role_catalog_status" in ready else True


def test_n_plus_one_new_outputs_need_no_historical_hashes(tmp_path, monkeypatch, installed):
    home, exe = installed
    old_receipt = json.loads((home / maintenance.RECEIPT_NAME).read_bytes())
    old_global = adapter._global_agents_block
    old_profile = adapter._agent_profile
    monkeypatch.setattr(adapter, "_global_agents_block", lambda *a, **kw: old_global(*a, **kw).replace(b"## Thaliris project startup", b"## Future completely changed startup contract"))
    monkeypatch.setattr(adapter, "_agent_profile", lambda *a, **kw: old_profile(*a, **kw) + b"# Future arbitrary profile output\n")
    changed = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert changed["ok"] is True, changed
    assert changed["changed"] is True
    assert "Future completely changed" in (home / "AGENTS.md").read_text()
    assert old_receipt["owned_bytes"] != json.loads((home / maintenance.RECEIPT_NAME).read_bytes())["owned_bytes"]
    assert lifecycle._controller_actor_assurance({}) == "UNKNOWN"


@pytest.mark.parametrize("surface", ["AGENTS.md", "agents/thaliris-implementer.toml", lifecycle.HOST_HOOK_SCRIPT_NAME])
def test_true_host_control_conflicts_fail_before_any_write(tmp_path, installed, surface):
    home, exe = installed
    contents = (home / surface).read_bytes()
    if surface == "AGENTS.md":
        contents = contents.replace(b"## Thaliris project startup", b"## user control edit")
    else:
        contents += b"user control edit"
    (home / surface).write_bytes(contents)
    before = snapshot(home)
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"] is False
    assert result["changed"] is False
    assert snapshot(home) == before


def test_candidate_renderer_equality_is_not_ownership_or_intent(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    home.mkdir()
    (home / "AGENTS.md").write_bytes(adapter._global_agents_block())
    exe, _ = pinned_test_thaliris
    before = snapshot(home)
    assert adapter.codex_install()["ok"] is False
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"] is False
    assert snapshot(home) == before


@pytest.mark.parametrize("defect", ["executable", "package", "manifest", "pth", "probe", "source_pin"])
def test_candidate_identity_failure_never_writes_profiles(tmp_path, monkeypatch, pinned_test_thaliris, defect):
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    exe, _ = pinned_test_thaliris
    path = intent(tmp_path, home, exe)
    if defect == "executable":
        exe.write_bytes(b"changed executable")
    elif defect == "package":
        (exe.parent.parent / "Lib/site-packages/thaliris_codex/cli.py").write_bytes(b"changed package")
    elif defect == "manifest":
        value = json.loads(path.read_bytes()); value["candidate"]["runtime_sha256"] = "a" * 64
        path.write_text(json.dumps(value))
    elif defect == "pth":
        (exe.parent.parent / "Lib/site-packages/evil.pth").write_text("import external\n")
    elif defect == "probe":
        monkeypatch.setattr(adapter, "_host_install_executable", lambda *a: (None, None, "host_executable_current_hook_abi_probe_failed"))
    else:
        value = json.loads(path.read_bytes()); value["candidate"]["source_pin"] = "sha256:" + "f" * 64
        path.write_text(json.dumps(value))
    assert adapter.codex_install(maintenance_contract=path)["ok"] is False
    assert snapshot(home) == {}


def test_arbitrary_workspace_guard_real_unknown_and_child_denial(tmp_path, monkeypatch, installed):
    home, exe = installed
    workspace = tmp_path / "unrelated"
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    (workspace / "AGENTS.md").write_bytes(b"unknown CONTROLPLANE project instruction")
    path = intent(tmp_path, home, exe)
    payload = {"tool_name": "exec_command", "session_id": "ambiguous-actor", "cwd": str(workspace),
               "tool_input": {"cmd": f"& '{exe}' codex-install --maintenance-contract '{path}'"}}
    assert lifecycle._controller_actor_assurance(payload) == "UNKNOWN"
    assert lifecycle._trusted_host_maintenance_route(payload)
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload, lifecycle.MANAGED_HOOK_ABI) == ""
    # An ACTIVE project's source/control compatibility is not Host authority.
    # This task ledger is test data, never evidence of native Controller identity.
    from thaliris import core
    core.init(workspace)
    core.task_start(workspace, "independent active sandbox task", None, None)
    assert lifecycle.managed_task_state(workspace)[0] == "ACTIVE"
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload, lifecycle.MANAGED_HOOK_ABI) == ""
    child = {**payload, "agent_id": "known-child", "agent_type": "thaliris-implementer"}
    assert not lifecycle._trusted_host_maintenance_route(child)
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", child, lifecycle.MANAGED_HOOK_ABI)
    assert (workspace / "AGENTS.md").read_bytes() == b"unknown CONTROLPLANE project instruction"
    readonly = {**payload, "readonly": True}
    assert not lifecycle._trusted_host_maintenance_route(readonly)
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", readonly, lifecycle.MANAGED_HOOK_ABI)
    direct_write = {**child, "tool_input": {"cmd": f"Set-Content -LiteralPath '{home / maintenance.RECEIPT_NAME}' -Value 'forged'"}}
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", direct_write, lifecycle.MANAGED_HOOK_ABI)
    lifecycle._session_fence_path(workspace).parent.mkdir(parents=True, exist_ok=True)
    lifecycle._session_fence_path(workspace).write_text(json.dumps({"version": 1,
        "session_id_hashes": [maintenance.digest(b"ambiguous-actor")]}))
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload, lifecycle.MANAGED_HOOK_ABI)
    payload["tool_input"]["cmd"] = "thaliris codex-install"
    assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload, lifecycle.MANAGED_HOOK_ABI)


def test_uninstall_reinstall_preserves_config_user_profiles_and_recovery_evidence(tmp_path, monkeypatch, installed):
    home, exe = installed
    (home / "config.toml").write_bytes(b"user_setting = true\n")
    (home / "agents/user.toml").write_bytes(b"user role\n")
    (home / "recovery-authority.json").write_bytes(b"retained task recovery evidence")
    monkeypatch.setenv("THALIRIS_RUN_SCRIPT", str(home / lifecycle.HOST_RUN_SCRIPT_NAME))
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall"))
    assert result["ok"] is True, result
    assert result["retained_inert_runner"] is True
    assert result["runtime_audit_records"]
    monkeypatch.delenv("THALIRIS_RUN_SCRIPT")
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"] is True, result
    assert (home / "config.toml").read_bytes() == b"user_setting = true\n"
    assert (home / "agents/user.toml").read_bytes() == b"user role\n"
    assert (home / "recovery-authority.json").read_bytes() == b"retained task recovery evidence"
    assert result["host_session_load_status"] == "UNKNOWN"
    assert result["host_role_catalog_status"] == lifecycle.HOST_ROLE_CATALOG_UNKNOWN


def test_legacy_migration_requires_exact_specific_human_approval(tmp_path, installed):
    home, exe = installed
    receipt = json.loads((home / maintenance.RECEIPT_NAME).read_bytes())
    (home / maintenance.RECEIPT_NAME).unlink()
    before = snapshot(home)
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"] is False
    assert snapshot(home) == before
    legacy = receipt["owned_bytes"] | {"hooks.json": maintenance.digest((home / "hooks.json").read_bytes())}
    path = intent(tmp_path, home, exe, legacy=legacy)
    migrated = adapter.codex_install(maintenance_contract=path)
    assert migrated["ok"] is True, migrated["manual_action_required"]


def test_unknown_project_control_is_preserved_and_admission_stays_blocked(tmp_path, monkeypatch, installed):
    home, exe = installed
    workspace = tmp_path / "control-conflict"
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    current = adapter.render_managed().replace("## Thaliris Router", "## Unknown authority contract").encode()
    (workspace / "AGENTS.md").write_bytes(current)
    result = adapter.init(workspace)
    assert result["project_definition_present"] == "NO"
    assert result["manual_action_required"] == ["AGENTS.md"]
    assert (workspace / "AGENTS.md").read_bytes() == current
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"] is True
    assert adapter.bootstrap_check(workspace)["project_definition_present"] == "NO"


def test_installed_runtime_drift_does_not_rebaseline_or_write(tmp_path, installed):
    home, exe = installed
    (exe.parent.parent / "Lib/site-packages/thaliris_codex/lifecycle.py").write_bytes(b"installed drift")
    path = intent(tmp_path, home, exe)
    before = snapshot(home)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"] is False
    assert result["changed"] is False
    assert snapshot(home) == before


def test_unsafe_host_trampoline_path_is_rejected_before_writes(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "unsafe%home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    exe, _ = pinned_test_thaliris
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"] is False
    assert result["changed"] is False
    assert not home.exists()


def test_file_in_profile_parent_is_rejected_before_any_host_write(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "home"
    home.mkdir()
    (home / "agents").write_bytes(b"user-owned regular file")
    monkeypatch.setenv("CODEX_HOME", str(home))
    exe, _ = pinned_test_thaliris
    before = snapshot(home)

    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))

    assert result["ok"] is False
    assert result["changed"] is False
    assert result["project_files_touched"] == []
    assert any("Host maintenance path parent is not a directory" in item
               for item in result["manual_action_required"])
    assert snapshot(home) == before


def test_uninstall_rejects_extra_thaliris_hook_even_with_receipt_before_mutation(
    tmp_path, monkeypatch, installed
):
    home, exe = installed
    hooks_path = home / "hooks.json"
    hooks = json.loads(hooks_path.read_bytes())
    extra = lifecycle.host_hook_spec(home, exe, "e" * 64, "f" * 64)["hooks"]["SessionStart"][0]
    hooks["hooks"]["SessionStart"].append(extra)
    hooks_path.write_text(json.dumps(hooks), encoding="utf-8")
    before = snapshot(home)
    calls = []
    from thaliris_codex import codex_app_server
    monkeypatch.setattr(codex_app_server, "remove_owned_hook_trust", lambda *_args: calls.append("trust"))
    monkeypatch.setattr(adapter, "_write_runtime_audit", lambda *_args: calls.append("audit"))

    result = adapter.codex_uninstall(
        maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall")
    )

    assert result["ok"] is False
    assert result["changed"] is False
    assert result["project_files_touched"] == []
    assert any("unowned Host hooks" in item for item in result["manual_action_required"])
    assert calls == []
    assert snapshot(home) == before


def test_unknown_actor_maintenance_does_not_drop_prior_luna_constraint(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "constrained-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    exe, _ = pinned_test_thaliris
    path = intent(tmp_path, home, exe)
    value = json.loads(path.read_bytes()); value["execution_constraint"] = "luna-only"
    path.write_text(json.dumps(value))
    assert adapter.codex_install(execution_constraint="luna-only", maintenance_contract=path)["ok"] is True
    before = snapshot(home)
    assert lifecycle._controller_actor_assurance({}) == "UNKNOWN"
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"] is False
    assert snapshot(home) == before
    payload = {"tool_name": "exec_command", "tool_input": {
        "cmd": f"& '{exe}' codex-install --maintenance-contract '{path}'"}}
    assert not lifecycle._trusted_host_maintenance_route(payload)
