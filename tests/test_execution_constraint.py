"""Execution policy changes native bindings, never semantic authority."""
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, lifecycle, roles, task_authority


def install_profiles(home, constraint):
    agents = home / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name, (model, effort, role) in roles.agent_profiles(constraint).items():
        (agents / name).write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))


@pytest.fixture
def constrained(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "authority")
    install_profiles(home, "luna-only")
    codex_adapter.init(root)
    core.task_start(root, "constraint test", None, None)
    intent = dict(human_instruction="Use Luna for every worker", boundary="marker", invariants="Same roles",
                  acceptance="All roles available", execution_mode="delegated", execution_constraint="luna-only")
    task_authority.establish(root, core._load_state(root), intent, hashlib.sha256(b"root").hexdigest())
    return root, home


def spawn(role, **extra):
    return dict(session_id="root", turn_id="root-turn", tool_name="spawn_agent", tool_input=dict(
        agent_type=roles.get_codex_binding(role).native_profile, fork_turns="none", message="Selected marker task", **extra))


def child_event(role, *, model="gpt-6-luna", agent_id="child", turn_id="child-turn"):
    event = dict(session_id="root", turn_id=turn_id, agent_id=agent_id,
                 agent_type=roles.get_codex_binding(role).native_profile)
    if model is not None:
        event["model"] = model
    return event


def test_all_semantic_roles_share_constrained_execution_only():
    defaults = roles.agent_profiles()
    constrained = roles.agent_profiles("luna-only")
    assert constrained.keys() == defaults.keys()
    for binding in roles.iter_codex_bindings():
        name = binding.profile_filename
        assert constrained[name] == ("gpt-6-luna", "xhigh", binding.role_id)
        default = codex_adapter._agent_profile(name[:-5], binding.role_id, *defaults[name][:2])
        value = codex_adapter._agent_profile(name[:-5], binding.role_id, *constrained[name][:2])
        parsed = tomllib.loads(value.decode())
        assert parsed["developer_instructions"] == tomllib.loads(default.decode())["developer_instructions"]
        assert roles.resolve_native_profile(parsed["name"]).id == binding.role_id
        assert codex_adapter._agent_profile_state(value, name, "luna-only") == "current"
        assert codex_adapter._agent_profile_state(value + b"\n# user change", name, "luna-only") == "user"
    for role in ("focused-implementer", "reviewer", "reasoning-specialist"):
        assert defaults[roles.get_codex_binding(role).profile_filename][:2] == ("gpt-6.1-sol", "high")
    assert roles.get_codex_binding("controller").model is None
    assert not roles.repo_write_allowed("reviewer")
    assert not roles.repo_write_allowed("verifier")


@pytest.mark.parametrize("role", [binding.role_id for binding in roles.iter_codex_bindings()])
def test_same_semantic_role_identity_is_admitted(constrained, role):
    root, _ = constrained
    assert lifecycle._reserve_managed_spawn(root, spawn(role)) == ""
    state = core._load_state(root)
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, state["task_id"]), state["task_id"])
    assert ledger["pending_authorized_spawn"]["role"] == role
    assert ledger["pending_authorized_spawn"]["expected_agent_type"] == roles.get_codex_binding(role).native_profile


def test_luna_constraint_rejects_overrides_and_astra(constrained):
    root, _ = constrained
    for model in ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna"):
        assert "MODEL_OVERRIDE" in lifecycle._reserve_managed_spawn(root, spawn("focused-implementer", model=model))
    request = spawn("focused-implementer")
    request["tool_input"]["agent_type"] = "thaliris-focused-implementer-astra-medium"
    assert "EXECUTION_CONSTRAINT" in lifecycle._reserve_managed_spawn(root, request)


def test_external_anchor_freezes_execution_profiles(constrained):
    root, home = constrained
    anchor = task_authority.check(root)
    assert anchor["execution_profiles"]["home"] == str(home)
    install_profiles(home, None)
    with pytest.raises(ValueError, match="CONSTRAINT_MISMATCH"):
        task_authority.check(root)


def test_installation_requires_explicit_matching_task_constraint(constrained):
    root, _ = constrained
    with pytest.raises(ValueError, match="CONSTRAINT_MISMATCH"):
        codex_adapter.execution_profile_snapshot(root, None)


def test_native_role_config_shadow_is_not_trusted(constrained):
    root, home = constrained
    (home / "config.toml").write_text('[agents.thaliris-reviewer]\nconfig_file="custom.toml"\n')
    with pytest.raises(ValueError, match="CONFIG_SHADOW"):
        task_authority.check(root)


def test_partial_luna_install_is_not_admitted_as_legacy_default(tmp_path, monkeypatch):
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    install_profiles(home, "luna-only")
    reviewer = home / "agents" / "thaliris-reviewer.toml"
    model, effort, role = roles.agent_profiles()[reviewer.name]
    reviewer.write_bytes(codex_adapter._agent_profile(reviewer.stem, role, model, effort))
    with pytest.raises(ValueError, match="EXECUTION_PROFILE_CONSTRAINT_MISMATCH"):
        codex_adapter._installed_execution_constraint()


def test_task_start_rejects_default_intent_on_partial_luna_install(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "authority")
    install_profiles(home, "luna-only")
    reviewer = home / "agents" / "thaliris-reviewer.toml"
    model, effort, role = roles.agent_profiles()[reviewer.name]
    reviewer.write_bytes(codex_adapter._agent_profile(reviewer.stem, role, model, effort))
    codex_adapter.init(root)
    contract = tmp_path / "default-contract.json"
    contract.write_text(json.dumps(dict(
        human_instruction="Use the default role policy", boundary="test repository",
        invariants="Preserve current routing", acceptance="Admit only a coherent installation",
        execution_mode="delegated",
    )), encoding="utf-8")
    monkeypatch.setattr(lifecycle, "consume_task_start_attestation", lambda *_args: None)
    with pytest.raises(ValueError, match="EXECUTION_PROFILE_CONSTRAINT_MISMATCH"):
        codex_adapter.task_start(root, "goal", None, None, authority_contract=str(contract))
    assert not (root / ".context" / "state.json").exists()


def test_pure_default_install_remains_legacy_compatible(tmp_path, monkeypatch):
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    install_profiles(home, None)
    assert codex_adapter._installed_execution_constraint() is None


def test_child_cannot_replace_execution_policy(constrained):
    root, _ = constrained
    request = spawn("focused-implementer")
    assert lifecycle.handle_hook(root, "PreToolUse", request) == ""
    child = child_event("focused-implementer")
    assert lifecycle._record_subagent_start(root, child)
    result = lifecycle.handle_hook(root, "PreToolUse", dict(child, tool_name="Bash", tool_input=dict(
        command='thaliris task-start other --authority-contract replacement.json')))
    assert "CONTROL_STATE_MUTATION" in result
    assert task_authority.check(root)["contract"]["execution_constraint"] == "luna-only"


def test_nested_scanner_inherits_policy_and_exact_parent(constrained):
    root, _ = constrained
    assert lifecycle.handle_hook(root, "PreToolUse", spawn("focused-implementer")) == ""
    parent = child_event("focused-implementer", agent_id="parent", turn_id="parent-turn")
    assert lifecycle._record_subagent_start(root, parent)
    request = dict(spawn("investigator"), **parent)
    assert lifecycle.handle_hook(root, "PreToolUse", request) == ""
    scanner = child_event("investigator", agent_id="scanner", turn_id="scanner-turn")
    assert lifecycle._record_subagent_start(root, scanner)
    task = core._load_state(root)
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task["task_id"]), task["task_id"])
    assert ledger["children"][1]["role"] == "investigator"
    assert ledger["children"][1]["depth"] == 2
    assert ledger["children"][1]["parent_agent_id_hash"] == ledger["children"][0]["agent_id_hash"]
    assert task_authority.check(root)["contract"]["execution_constraint"] == "luna-only"
    assert "DELEGATION" in lifecycle.handle_hook(root, "PreToolUse", dict(spawn("reviewer"), **scanner))


@pytest.mark.parametrize(("model", "status"), [("gpt-6.1-sol", "MISMATCH"), (None, "MISSING")])
def test_constrained_child_model_mismatch_or_missing_leaves_handoff_unbound(constrained, model, status):
    root, _ = constrained
    assert lifecycle.handle_hook(root, "PreToolUse", spawn("focused-implementer")) == ""
    child = child_event("focused-implementer", model=model)
    assert lifecycle.handle_hook(root, "SubagentStart", child) == ""
    task = core._load_state(root)
    ledger = lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task["task_id"]), task["task_id"])
    assert ledger["children"][-1]["execution_constraint_model_status"] == status
    assert ledger["children"][-1]["handoff_bound"] is False
    assert ledger["pending_authorized_spawn"] is not None
    result = lifecycle.handle_hook(root, "PreToolUse", dict(child, tool_name="Bash", tool_input={"command": "Get-Content README.md"}))
    assert "BOUND_ROLE_SESSION_REQUIRED" in result


@pytest.mark.parametrize("config_change", ["added", "removed"])
def test_constrained_admission_requires_sessionstart_config_snapshot(tmp_path, monkeypatch, pinned_test_thaliris, config_change):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "authority")
    install_profiles(home, "luna-only")
    codex_adapter.init(root)
    config = home / "config.toml"
    if config_change == "removed":
        config.write_text("[features]\nhooks = true\n", encoding="utf-8")
    session_id = "constraint-admission-session"
    codex_adapter.audit_hook(root, "SessionStart", {"session_id": session_id, "source": "startup", "cwd": str(root)})
    if config_change == "added":
        config.write_text("[features]\nhooks = true\n", encoding="utf-8")
    else:
        config.unlink()
    contract = tmp_path / "authority-contract.json"
    contract.write_text(json.dumps(dict(
        human_instruction="Use the constrained role profiles", boundary="test repository",
        invariants="Preserve semantic roles", acceptance="Reject stale public configuration",
        execution_mode="delegated", execution_constraint="luna-only",
    )), encoding="utf-8")
    bridge = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    command = f'thaliris task-start goal --controller-bridge-sha256 {bridge} --authority-contract "{contract}"'
    request = dict(session_id=session_id, turn_id="start-turn", cwd=str(root), tool_name="Bash", tool_input={"command": command})
    output = lifecycle._issue_task_start_attestation(root, request, lifecycle.MANAGED_HOOK_ABI)
    rewritten = json.loads(output)["hookSpecificOutput"]["updatedInput"]["command"]
    token = rewritten.rsplit("--hook-attestation ", 1)[1]
    with pytest.raises(ValueError, match="EXECUTION_CONFIGS_REQUIRE_FRESH_HOST_SESSION"):
        codex_adapter.task_start(root, "goal", None, None, token, bridge, str(contract))
    assert not (root / ".context" / "state.json").exists()


def test_policy_is_bound_to_one_shot_contract_digest(constrained):
    root, _ = constrained
    path = root / "selected.json"
    selected = task_authority.check(root)["contract"]
    path.write_text(json.dumps(selected))
    bridge = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    request = dict(session_id="other", turn_id="other-turn", cwd=str(root), tool_name="Bash", tool_input=dict(
        command=f'thaliris task-start test --bootstrap-receipt {bridge} --authority-contract "{path}"'))
    output = lifecycle._issue_task_start_attestation(root, request, lifecycle.MANAGED_HOOK_ABI)
    token = json.loads(output)["hookSpecificOutput"]["updatedInput"]["command"].split("--hook-attestation ")[1]
    path.write_text(json.dumps({key:value for key,value in selected.items() if key != "execution_constraint"}))
    with pytest.raises(ValueError, match="MANAGED_CURRENT_SESSION_NOT_ATTESTED"):
        lifecycle.consume_task_start_attestation(root, token, bridge, task_authority.digest(path))


def test_constraint_contract_has_no_implicit_or_arbitrary_policy(tmp_path):
    value = dict(human_instruction="human", boundary="bound", invariants="keep", acceptance="check", execution_mode="delegated")
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value))
    assert task_authority.contract(str(path)) == value
    for policy in (None, "sol", {"model": "gpt-6-luna"}):
        path.write_text(json.dumps(dict(value, execution_constraint=policy)))
        with pytest.raises(ValueError, match="UNSUPPORTED_EXECUTION_CONSTRAINT"):
            task_authority.contract(str(path))


def test_constraint_install_preserves_unknown_profile_bytes(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    install_profiles(home, None)
    target = home / "agents" / "thaliris-reviewer.toml"
    target.write_bytes(target.read_bytes() + b"\n# user edit")
    before = target.read_bytes()
    result = codex_adapter.codex_install(execution_constraint="luna-only")
    assert str(target) in result["manual_action_required"]
    assert target.read_bytes() == before
    assert result["host_profile_definition_present"] == "NO"


def test_constrained_installation_diagnostics_and_owned_removal(tmp_path, monkeypatch, pinned_test_thaliris):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    codex_adapter.init(root)
    result = codex_adapter.codex_install(execution_constraint="luna-only")
    assert result["ok"]
    diagnostic = codex_adapter.doctor(root)
    assert diagnostic["role_registry"]["installed_execution_constraint"] == "luna-only"
    assert all(p["ownership"] == "current" and p["expected"] == p["actual"]
               for p in diagnostic["drift_evidence"]["profile_definitions"])
    result = codex_adapter.codex_uninstall()
    assert all(f"agents/{name}" in result["files"] for name in roles.agent_profiles())


def test_split_registry_upgrade_uses_independent_immutable_bytes():
    original = Path("tests/fixtures/codex-split-role-registry-158690b.md").read_bytes()
    # Exact 158690bdc087fbe3ce5f4c61e4a356ddbac89e0e Git blob,
    # independently compared with that revision's roles renderer.
    assert hashlib.sha256(original).hexdigest() == "8a1393b2e175860242923d7387a6207b44fb13fc5b2900b10219458264ca3fad"
    assert codex_adapter._role_registry_state(original) == "legacy"
    assert codex_adapter._role_registry_state(original + b"\n# user change") == "user"


def test_direct_facade_establish_rejects_unknown_constraint(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "authority")
    core.init(root)
    core.task_start(root, "Explicit intent", None, None)
    selected = dict(human_instruction="human", boundary="bound", invariants="keep", acceptance="check", execution_mode="delegated", execution_constraint="unsupported-policy")
    with pytest.raises(ValueError, match="UNSUPPORTED_EXECUTION_CONSTRAINT"):
        task_authority.establish(root, core._load_state(root), selected, "session")
    assert task_authority.read(root) is None
