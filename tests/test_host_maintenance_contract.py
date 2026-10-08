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


def test_candidate_platform_failure_preserves_previous_generation(tmp_path, monkeypatch, installed):
    from thaliris_codex import host_preflight
    home, exe = installed
    before = snapshot(home)
    path = intent(tmp_path, home, exe)

    def reject(*_args):
        raise ValueError("independent platform runtime preflight failed: incompatible launcher")

    monkeypatch.setattr(host_preflight, "verify_runtime", reject)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"] is False and result["changed"] is False
    assert "platform runtime preflight failed" in result["manual_action_required"][0]
    assert snapshot(home) == before


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
    monkeypatch.setattr(adapter, "_global_agents_block", lambda *a, **kw: old_global(*a, **kw).replace(b"## Thaliris shared entry", b"## Future completely changed startup contract"))
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
        contents = contents.replace(b"## Thaliris shared entry", b"## user control edit")
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
    current = adapter.render_managed().replace("## Thaliris shared boundaries", "## Unknown authority contract").encode()
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


def test_retired_receipt_owned_profiles_are_deleted_without_candidate_history(tmp_path, monkeypatch, installed):
    from tests.host_maintenance_test_support import attest_prior_authorized_bytes
    home, exe = installed
    retired = "agents/thaliris-retired-generation.toml"
    old_bytes = b"arbitrary authorized generation N profile\n"
    (home / retired).write_bytes(old_bytes)
    attest_prior_authorized_bytes(home, {retired: old_bytes})
    (home / "agents/user.toml").write_bytes(b"user role")
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"], result
    assert retired in result["files"]
    assert not (home / retired).exists()
    assert retired not in json.loads((home / maintenance.RECEIPT_NAME).read_bytes())["owned_bytes"]
    assert (home / "agents/user.toml").read_bytes() == b"user role"


@pytest.mark.parametrize("operation", ["codex-install", "codex-uninstall"])
def test_edited_retired_profile_is_preserved(operation, tmp_path, installed):
    from tests.host_maintenance_test_support import attest_prior_authorized_bytes
    home, exe = installed
    name = "agents/thaliris-retired.toml"
    (home / name).write_bytes(b"old authorized")
    attest_prior_authorized_bytes(home, {name: b"old authorized"})
    (home / name).write_bytes(b"user edits")
    before = snapshot(home)
    path = intent(tmp_path, home, exe, operation)
    result = adapter.codex_install(maintenance_contract=path) if operation == "codex-install" else adapter.codex_uninstall(maintenance_contract=path)
    if operation == "codex-install":
        assert not result["ok"]
        assert snapshot(home) == before
    else:
        assert result["ok"], result
        assert name in result["preserved_files"]
    assert (home / name).read_bytes() == b"user edits"


class SimulatedProcessExit(BaseException):
    pass


@pytest.mark.parametrize("operation", ["fresh", "upgrade", "uninstall"])
@pytest.mark.parametrize("surface", ["AGENTS.md", "agents/thaliris-implementer.toml", "hooks.json",
                                    runtime_identity.MANIFEST_NAME, maintenance.RECEIPT_NAME,
                                    "COMMIT", "ARCHIVE"])
def test_generation_crash_replays_original_contract(operation, surface, tmp_path, monkeypatch, pinned_test_thaliris):
    import shutil
    from thaliris_codex import host_transition
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    exe, _ = pinned_test_thaliris
    if operation != "fresh":
        assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"]
    home.mkdir(exist_ok=True)
    (home / "user.txt").write_bytes(b"user-owned content")
    (home / "config.toml").write_bytes(b"user_setting=true\n")
    (home / "agents").mkdir(exist_ok=True)
    (home / "agents/user.toml").write_bytes(b"user role")
    if operation == "upgrade":
        next_runtime = tmp_path / "generation-n-plus-one"
        shutil.copytree(exe.parent.parent, next_runtime)
        exe = next_runtime / "Scripts" / exe.name
        exe.write_bytes(b"independently selected N+1 launcher")
        (next_runtime / "Lib/site-packages/thaliris_codex/cli.py").write_bytes(b"N+1 package source")
        monkeypatch.setattr(adapter, "_host_install_executable", lambda _home, path, sha: (Path(path), sha, None))
        original_profile = adapter._agent_profile
        monkeypatch.setattr(adapter, "_agent_profile", lambda *a, **kw: original_profile(*a, **kw) + b"# N+1\n")
        original_global = adapter._global_agents_block
        monkeypatch.setattr(adapter, "_global_agents_block", lambda *a, **kw: original_global(*a, **kw).replace(b"## Thaliris shared entry", b"## N+1 startup"))
    op = "codex-uninstall" if operation == "uninstall" else "codex-install"
    path = intent(tmp_path, home, exe, op)
    approved_before = maintenance._files(home)
    original_write = adapter._atomic_host_write
    original_unlink = Path.unlink
    hit = []

    def fault(target, contents=None):
        relative = target.relative_to(home).as_posix() if target.is_relative_to(home) else ""
        selected = relative == surface or (surface == "COMMIT" and relative == host_transition.NAME) or (
            surface == "ARCHIVE" and relative.startswith("thaliris-host-generations/"))
        if selected and not hit:
            hit.append(relative)
            raise SimulatedProcessExit()

    def write(target, contents):
        fault(target, contents)
        return original_write(target, contents)

    def unlink(target, *args, **kwargs):
        fault(target)
        return original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    monkeypatch.setattr(Path, "unlink", unlink)
    invoke = adapter.codex_uninstall if operation == "uninstall" else adapter.codex_install
    with pytest.raises(SimulatedProcessExit):
        invoke(maintenance_contract=path)
    assert hit
    journal, before, after = host_transition.load(home, maintenance.contract(path, op, home))
    assert journal["phase"] == ("COMMITTED" if surface == "ARCHIVE" else "PREPARED")
    assert {n: v for n, v in before.items() if v is not None} == approved_before
    # Read-only native routing accepts the exact original contract across an
    # interrupted manifest/receipt pair. Children still have no maintenance grant.
    payload = {"tool_name": "exec_command", "tool_input": {"cmd": f"& '{exe}' {op} --maintenance-contract '{path}'"}}
    assert lifecycle._trusted_host_maintenance_route(payload)
    assert not lifecycle._trusted_host_maintenance_route({**payload, "agent_id": "child"})
    monkeypatch.setattr(adapter, "_atomic_host_write", original_write)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    result = invoke(maintenance_contract=path)
    assert result["ok"], result
    assert not host_transition.pending(home)
    assert (home / "user.txt").read_bytes() == b"user-owned content"
    assert (home / "agents/user.toml").read_bytes() == b"user role"
    assert (home / "config.toml").read_bytes() == b"user_setting=true\n"
    if operation == "uninstall":
        assert not (home / runtime_identity.MANIFEST_NAME).exists()
        assert not (home / maintenance.RECEIPT_NAME).exists()
    else:
        receipt = maintenance.ownership(home, maintenance._installed(home), maintenance.contract(path, op, home))
        assert all(maintenance.owned(receipt, n, (home / n).read_bytes()) for n in receipt["owned_bytes"] if n != "AGENTS.md#global")


@pytest.mark.parametrize("operation", ["codex-install", "codex-uninstall"])
@pytest.mark.parametrize("surface", ["COMMIT", "ARCHIVE"])
def test_legacy_prior_generation_crash_replays_with_exact_receipt(
    operation, surface, tmp_path, monkeypatch, pinned_test_thaliris
):
    """A pre-location prior stays receipt-authorized through interrupted recovery."""
    import shutil
    from thaliris_codex import host_transition

    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    legacy_exe, _ = pinned_test_thaliris
    initial_contract = intent(tmp_path, home, legacy_exe)
    assert adapter.codex_install(maintenance_contract=initial_contract)["ok"]
    prior = (home / runtime_identity.MANIFEST_NAME).read_bytes()
    prior_record = runtime_identity.validate_manifest_record(prior)
    assert runtime_identity.LOCATION_NAME not in prior_record["files"]
    prior_receipt = (home / maintenance.RECEIPT_NAME).read_bytes()

    candidate_venv = tmp_path / "independently-selected-candidate"
    shutil.copytree(legacy_exe.parent.parent, candidate_venv)
    candidate = candidate_venv / "Scripts" / legacy_exe.name
    candidate.write_bytes(b"independently selected next-generation launcher")
    (candidate_venv / "Lib/site-packages/thaliris_codex/cli.py").write_text(
        "# next-generation candidate\n", encoding="utf-8"
    )

    original_binding = runtime_identity._assert_launcher_binding

    def binding(path):
        if Path(path).resolve() == legacy_exe.resolve():
            raise ValueError("Windows console launcher interpreter binding is unavailable")
        return original_binding(path)

    monkeypatch.setattr(runtime_identity, "_assert_launcher_binding", binding)
    with pytest.raises(ValueError, match="interpreter binding is unavailable"):
        runtime_identity.validate_manifest(prior, legacy_exe, maintenance.digest(prior))
    assert runtime_identity.validate_existing_manifest(
        prior, legacy_exe, maintenance.digest(prior)
    ) == prior_record
    candidate_manifest = runtime_identity.manifest_bytes(candidate)
    runtime_identity.validate_manifest(candidate_manifest, candidate, maintenance.digest(candidate_manifest))

    monkeypatch.setattr(
        adapter,
        "_host_install_executable",
        lambda _home, path, sha: (Path(path).resolve(), sha, None),
    )
    path = intent(tmp_path, home, candidate, operation)
    approved_before = maintenance._files(home)
    assert maintenance.validate_ownership(prior_receipt, prior, {})["runtime_sha256"] == maintenance.digest(prior)

    original_write = adapter._atomic_host_write

    def crash(target, contents):
        relative = target.relative_to(home).as_posix() if target.is_relative_to(home) else ""
        interrupted = relative == host_transition.NAME if surface == "COMMIT" else (
            relative.startswith("thaliris-host-generations/")
        )
        if interrupted:
            raise SimulatedProcessExit()
        original_write(target, contents)

    monkeypatch.setattr(adapter, "_atomic_host_write", crash)
    invoke = adapter.codex_install if operation == "codex-install" else adapter.codex_uninstall
    with pytest.raises(SimulatedProcessExit):
        invoke(maintenance_contract=path)

    monkeypatch.setattr(adapter, "_atomic_host_write", original_write)
    journal, before, _after = host_transition.load(home, maintenance.contract(path, operation, home))
    assert journal["phase"] == ("PREPARED" if surface == "COMMIT" else "COMMITTED")
    assert {name: contents for name, contents in before.items() if contents is not None} == approved_before
    assert before[maintenance.RECEIPT_NAME] == prior_receipt

    result = invoke(maintenance_contract=path)
    assert result["ok"], result
    assert not host_transition.pending(home)
    if operation == "codex-install":
        installed = maintenance._installed(home)
        assert installed == runtime_identity.manifest_bytes(candidate)
    else:
        assert not (home / runtime_identity.MANIFEST_NAME).exists()
        assert not (home / maintenance.RECEIPT_NAME).exists()


def test_partial_transition_drift_is_never_blessed(tmp_path, monkeypatch, pinned_test_thaliris):
    from thaliris_codex import host_transition
    home = tmp_path / "home"
    exe, _ = pinned_test_thaliris
    path = intent(tmp_path, home, exe)
    original = adapter._atomic_host_write
    def crash(target, contents):
        if target.name == maintenance.RECEIPT_NAME:
            raise SimulatedProcessExit()
        original(target, contents)
    monkeypatch.setattr(adapter, "_atomic_host_write", crash)
    with pytest.raises(SimulatedProcessExit):
        adapter.codex_install(codex_home=home, maintenance_contract=path)
    monkeypatch.setattr(adapter, "_atomic_host_write", original)
    (home / "AGENTS.md").write_bytes(b"user change during interrupted transition")
    before = snapshot(home)
    result = adapter.codex_install(codex_home=home, maintenance_contract=path)
    assert not result["ok"]
    assert snapshot(home) == before
    assert host_transition.pending(home)


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_native_trust_interruption_is_coherent_and_replayable(operation, tmp_path, monkeypatch, installed):
    from thaliris_codex import host_transition, codex_app_server
    home, exe = installed
    op = "codex-" + operation
    path = intent(tmp_path, home, exe, op)
    module, name = (adapter, "_install_host_hook_trust") if operation == "install" else (codex_app_server, "remove_owned_hook_trust")
    original = getattr(module, name)
    def crash(*args):
        raise SimulatedProcessExit()
    monkeypatch.setattr(module, name, crash)
    invoke = adapter.codex_install if operation == "install" else adapter.codex_uninstall
    with pytest.raises(SimulatedProcessExit):
        invoke(maintenance_contract=path)
    journal, _, after = host_transition.load(home, maintenance.contract(path, op, home))
    assert journal["phase"] == "COMMITTED"
    assert all((home / n).read_bytes() == v if v is not None else not (home / n).exists() for n, v in after.items())
    monkeypatch.setattr(module, name, original)
    assert invoke(maintenance_contract=path)["ok"]
    assert not host_transition.pending(home)


def test_finalization_rechecks_effective_bytes_and_preserves_new_user_edits(tmp_path, monkeypatch, installed):
    from thaliris_codex import host_transition
    home, exe = installed
    path = intent(tmp_path, home, exe)
    original = adapter._install_host_hook_trust
    def changed(home, *args):
        result = original(home, *args)
        (home / "AGENTS.md").write_bytes(b"user change during trust step")
        return result
    monkeypatch.setattr(adapter, "_install_host_hook_trust", changed)
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"]
    assert result["status"] == "HOST_TRANSITION_PENDING"
    assert (home / "AGENTS.md").read_bytes() == b"user change during trust step"
    assert host_transition.pending(home)


@pytest.mark.parametrize("surface", ["thaliris-host-generations", "thaliris-host-maintenance.lock"])
def test_transition_metadata_conflicts_are_full_preflight_failures(surface, tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "home"
    home.mkdir()
    (home / surface).write_bytes(b"user-owned metadata path")
    exe, _ = pinned_test_thaliris
    before = snapshot(home)
    result = adapter.codex_install(codex_home=home, maintenance_contract=intent(tmp_path, home, exe))
    assert not result["ok"]
    assert not result["changed"]
    assert snapshot(home) == before


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows platform runner")
def test_pending_generation_is_recognized_before_python_dispatch(tmp_path, pinned_test_thaliris):
    from thaliris_codex import host_preflight, host_transition
    exe, _ = pinned_test_thaliris
    launcher = exe.parent / "dispatch.cmd"
    launcher.write_bytes(b"@echo off\r\necho unexpected-dispatch\r\n")
    home = tmp_path / "home"
    home.mkdir()
    manifest = runtime_identity.manifest_bytes(launcher)
    (home / runtime_identity.MANIFEST_NAME).write_bytes(manifest)
    (home / host_preflight.NAME).write_bytes(host_preflight.script_bytes())
    runner = home / lifecycle.HOST_RUN_SCRIPT_NAME
    runner.write_bytes(lifecycle.host_run_script_bytes(launcher, maintenance.digest(manifest)))
    (home / host_transition.NAME).write_bytes(b"pending generation evidence")
    result = subprocess.run([str(runner), "codex-bootstrap"], capture_output=True, timeout=15)
    assert result.returncode != 0
    assert b"HOST_TRANSITION_PENDING" in result.stdout
    assert b"unexpected-dispatch" not in result.stdout


def test_pending_generation_blocks_bootstrap_without_project_mutation(tmp_path, monkeypatch, installed):
    from thaliris_codex import host_transition
    home, exe = installed
    (home / host_transition.NAME).write_bytes(b"interrupted generation")
    project = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    before = snapshot(project)
    result = codex_bootstrap.bootstrap(project)
    assert result["status"] == "HOST_TRANSITION_PENDING"
    assert result["init_invoked"] is False
    assert snapshot(project) == before


def test_committed_replay_rejects_different_explicit_options(tmp_path, monkeypatch, installed):
    from thaliris_codex import host_transition
    home, exe = installed
    path = intent(tmp_path, home, exe)
    original = adapter._install_host_hook_trust
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *a: {"status": "FAILED"})
    assert not adapter.codex_install(maintenance_contract=path)["ok"]
    before = snapshot(home)
    result = adapter.codex_install(maintenance_contract=path, execution_constraint="luna-only")
    assert not result["ok"]
    assert snapshot(home) == before
    monkeypatch.setattr(adapter, "_install_host_hook_trust", original)
    assert adapter.codex_install(maintenance_contract=path)["ok"]
    assert not host_transition.pending(home)


def test_independent_historical_profile_needs_prior_authorization(tmp_path, installed):
    from tests.support.history import historical_blob
    from tests.host_maintenance_test_support import attest_prior_authorized_bytes
    home, exe = installed
    name = "agents/thaliris-focused-implementer.toml"
    historical = historical_blob("e4b6975889ef348e13e94521dc300f1e572b42a3:.codex/agents/thaliris-focused-implementer.toml")
    assert adapter._agent_profile_state(historical, Path(name).name) == "legacy"
    (home / name).write_bytes(historical)
    before = snapshot(home)
    path = intent(tmp_path, home, exe)
    assert not adapter.codex_install(maintenance_contract=path)["ok"]
    assert snapshot(home) == before
    attest_prior_authorized_bytes(home, {name: historical})
    assert adapter.codex_install(maintenance_contract=path)["ok"]
    assert (home / name).read_bytes() != historical


def test_os_lock_releases_after_actual_process_exit(tmp_path):
    import sys
    from thaliris_codex import host_transition
    home = tmp_path / "home"
    child = subprocess.run([sys.executable, "-c",
        "import os,sys; from pathlib import Path; from thaliris_codex.host_transition import locked; "
        "guard=locked(Path(sys.argv[1])); guard.__enter__(); os._exit(17)", str(home)],
        capture_output=True, timeout=15)
    assert child.returncode == 17, child.stderr
    assert (home / host_transition.LOCK_NAME).read_bytes() == host_transition.LOCK_BYTES
    with host_transition.locked(home):
        pass # acquiring succeeds after an actual abrupt process exit


def test_malformed_transition_finalization_is_preserved_without_mutation(tmp_path, monkeypatch, installed):
    from thaliris_codex import host_transition
    home, exe = installed
    path = intent(tmp_path, home, exe)
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *a: {"status": "FAILED"})
    assert not adapter.codex_install(maintenance_contract=path)["ok"]
    journal = home / host_transition.NAME
    value = json.loads(journal.read_bytes())
    value["finish"] = None
    journal.write_text(json.dumps(value), encoding="utf-8")
    before = snapshot(home)
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"]
    assert result["status"] == "HOST_TRANSITION_PENDING"
    assert snapshot(home) == before
