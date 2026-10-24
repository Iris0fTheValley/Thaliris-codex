from tests.host_maintenance_test_support import authorized_host_install, authorized_host_uninstall, legacy_file_hashes
"""Prompt contract concepts and ownership, not historical paragraph wording.

No model invocation: these tests prove emitted instruction contracts and safe
migration, not behavioral compliance or quality improvement by an LLM.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tomllib
import re
import ast
import sys
import types
import shlex

import pytest

from thaliris_codex import codex_adapter as adapter, codex_bootstrap, controller_instructions, roles
from tests.support.history import historical_blob


def normalized(text):
    return " ".join(text.lower().split())


def concepts(text, *groups):
    """Vocabulary coverage tolerates word order, inflection and connective edits.

    This is deliberately not a semantic/LLM compliance proof. Executable role,
    authority and lifecycle tests prove mechanical behavior; generated equality
    proves distribution. Historical ownership below always uses exact bytes.
    Negation and precision-bearing protocol identifiers remain required tokens.
    """
    def tokens(value):
        filler = {"a", "an", "the", "its", "their", "that", "this", "are", "is", "be", "and", "or", "of", "to", "in", "with", "by", "for"}
        return {word.removesuffix("s") for word in re.findall(r"[a-z0-9_]+", value.lower()) if word not in filler}
    available = tokens(text)
    for group in groups:
        for anchor in ((group,) if isinstance(group, str) else group):
            assert tokens(anchor) <= available, f"missing contract vocabulary: {tokens(anchor) - available}"


def prompt(role):
    return roles.get_role(role).instructions


def test_delegated_cognitive_ownership_is_in_resident_context_at_the_decision_points():
    # Structural distribution: the routing, handoff and durable sections are
    # delivered by the resident guidance; the Controller role itself carries no
    # second instruction copy.
    resident = codex_bootstrap.controller_guidance()
    for name in ("routing", "handoff", "durable"):
        assert controller_instructions.render(section=name).strip() in resident
    assert prompt("controller") == ""


def test_runtime_ownership_has_one_normal_layer_per_concern():
    global_text = adapter._global_agents_block().decode()
    controller = controller_instructions.render()
    resident = codex_bootstrap.controller_guidance()
    for controller_detail in ("authority-contract", "task-recover-state", "task-recover-authority", "offline_recovery.py"):
        assert controller_detail not in normalized(global_text)
        assert controller_detail in normalized(controller)
    for obsolete_admission_detail in ("task_start_receipt", "--bootstrap-receipt"):
        assert obsolete_admission_detail not in normalized(controller)
    for name in controller_instructions.RESIDENT_SECTIONS:
        # Necessary normal bootstrap returns the canonical guidance; no extra get
        # or full Controller injection into each fresh native child is required.
        if name != "startup":
            section = controller_instructions.render(section=name)
            assert section.strip() in resident
            assert section.strip() not in global_text
    assert "task-recover-authority" not in prompt("implementer")
    assert prompt("implementer") in adapter.render_role_packs()


def test_reviewer_is_not_repo_writing():
    assert not roles.repo_write_allowed("reviewer")


def test_discovery_challenge_knowledge_and_delegation_capabilities():
    for role in ("investigator", "curator", "reasoning-specialist", "verifier"):
        assert not roles.get_codex_binding(role).allowed_delegation_targets
        assert "fork_turns" not in prompt(role)
        assert "fork_context" not in prompt(role)
    for role in ("implementer", "focused-implementer", "reviewer"):
        assert roles.get_codex_binding(role).allowed_delegation_targets == frozenset({"investigator"})
        assert 'fork_turns="none"' in prompt(role)
        assert "fork_context=false" in prompt(role)


@pytest.mark.parametrize("execution_constraint", [None, "luna-only"])
def test_profile_delegation_text_matches_role_capability(execution_constraint):
    for name, (model, effort, role) in roles.agent_profiles(execution_constraint).items():
        value = tomllib.loads(adapter._agent_profile(name[:-5], role, model, effort).decode())["developer_instructions"]
        if roles.get_codex_binding(role).allowed_delegation_targets:
            assert 'fork_turns="none"' in value and "fork_context=false" in value
        else:
            assert "fork_turns" not in value and "fork_context" not in value


def test_controller_selects_roles_and_accounts_for_goals():
    assert not {"scanner", "executor", "astra"} & set(roles.role_choices())
    assert roles.resolve_native_profile("thaliris-focused-implementer-astra-medium").id == "focused-implementer"


def test_generated_sources_equal_derived_outputs():
    assert Path("AGENTS.md").read_text(encoding="utf-8") == adapter.render_managed()
    assert Path("docs/thaliris-controller.md").read_text(encoding="utf-8") == controller_instructions.render()
    assert Path("docs/thaliris-role-packs.md").read_text(encoding="utf-8") == adapter.render_role_packs()
    # Ignored project profiles are user/local state, not authoritative derived
    # artifacts. Admission still rejects shadows; tests never overwrite them.
    tracked = set(subprocess.check_output(["git", "ls-files", "--", ".codex/agents"], text=True).splitlines())
    for name, (model, effort, role) in roles.agent_profiles().items():
        path = Path(".codex/agents") / name
        if path.as_posix() in tracked:
            assert path.read_bytes() == adapter._agent_profile(name[:-5], role, model, effort)
        parsed = tomllib.loads(adapter._agent_profile(name[:-5], role, model, effort).decode())
        assert parsed["developer_instructions"] == roles.profile_instructions(role, name[:-5])


def test_pre_normalization_generated_ownership_is_exact_and_filename_bound():
    base = Path(__file__).parent / "fixtures/prompt-contract-before"
    provenance = json.loads((base / "provenance.json").read_text())
    assert provenance["revision"] == "6396e138a0ccde3e4e34e961912fa627c30c7ff1"
    for name, digest in provenance["profiles"].items():
        raw = (base / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        assert adapter._agent_profile_state(raw, name) == "legacy"
        assert adapter._agent_profile_state(raw + b"\n# user edit", name) == "user"
        other = next(item for item in provenance["profiles"] if item != name)
        assert adapter._agent_profile_state(raw, other) == "user"
    managed = (base / "managed.md").read_text(encoding="utf-8")
    assert hashlib.sha256(managed.encode()).hexdigest() == provenance["managed_sha256"]
    assert adapter._managed_agents_state(managed) == "legacy"
    assert adapter._managed_agents_state(managed.replace("<!-- thaliris:end -->", "edit\n<!-- thaliris:end -->")) == "user"
    packs = (base / "role-packs.md").read_bytes()
    assert hashlib.sha256(packs).hexdigest() == provenance["role_packs_sha256"]
    assert adapter._role_pack_state(packs) == "legacy"
    assert adapter._role_pack_state(packs + b"edit") == "user"
    registry = (base / "role-registry.md").read_bytes()
    assert hashlib.sha256(registry).hexdigest() == provenance["role_registry_sha256"]
    assert adapter._role_registry_state(registry) == "legacy"
    assert adapter._role_registry_state(registry + b"edit") == "user"


def test_orchestration_predecessor_is_independently_rendered_and_filename_bound():
    base = Path(__file__).parent / "fixtures/orchestration-before"
    proof = json.loads((base / "provenance.json").read_text(encoding="utf-8"))
    revision = "3d2d3026c9a81790219040f926baa2f975f8bce1"
    assert proof["revision"] == revision
    module = types.ModuleType("orchestration_immutable_roles")
    sys.modules[module.__name__] = module
    source = historical_blob(revision + ":src/thaliris_codex/roles.py")
    exec(compile(source, "immutable_roles.py", "exec"), module.__dict__)
    tree = ast.parse(historical_blob(revision + ":src/thaliris_codex/codex_adapter.py"))
    namespace = {"roles": module, "json": json}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_agent_profile"]
    exec(compile(ast.Module(functions, type_ignores=[]), "immutable_adapter.py", "exec"), namespace)
    for constraint in (None, "luna-only"):
        label = constraint or "default"
        for name, (model, effort, role) in module.agent_profiles(constraint).items():
            raw = (base / label / name).read_bytes()
            assert raw == namespace["_agent_profile"](name[:-5], role, model, effort)
            assert hashlib.sha256(raw).hexdigest() == proof["profiles"][label][name]
            assert adapter._agent_profile_state(raw, name, constraint) in {"current", "legacy"}
            assert adapter._agent_profile_state(raw + b"\n# private edit", name, constraint) == "user"
            wrong = next(item for item in module.agent_profiles(constraint) if item != name)
            assert adapter._agent_profile_state(raw, wrong, constraint) == "user"
    managed = (base / "managed.md").read_bytes()
    assert managed == historical_blob(revision + ":AGENTS.md")
    assert adapter._managed_agents_state(managed.decode()) == "legacy"
    assert adapter._managed_agents_state(managed.decode().replace("<!-- thaliris:end -->", "edit\n<!-- thaliris:end -->")) == "user"
    packs = (base / "role-packs.md").read_bytes()
    assert packs == historical_blob(revision + ":docs/thaliris-role-packs.md")
    assert adapter._role_pack_state(packs) == "legacy"
    assert adapter._role_pack_state(packs + b"edit") == "user"


def test_role_model_predecessor_is_independent_and_filename_bound():
    base = Path(__file__).parent / "fixtures/role-model-before"
    proof = json.loads((base / "provenance.json").read_text(encoding="utf-8"))
    revision = "5f80214bb8d4ef219851405b017f660c5f8b554e"
    assert proof["revision"] == revision
    module = types.ModuleType("role_model_immutable_roles")
    sys.modules[module.__name__] = module
    exec(compile(historical_blob(revision + ":src/thaliris_codex/roles.py"), "immutable_roles.py", "exec"), module.__dict__)
    tree = ast.parse(historical_blob(revision + ":src/thaliris_codex/codex_adapter.py"))
    namespace = {"roles": module, "json": json, "MANAGED_START": adapter.MANAGED_START, "MANAGED_END": adapter.MANAGED_END}
    renderers = {"_agent_profile", "_render_managed", "_render_role_packs", "_native_profile_facts", "_native_role_labels"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in renderers]
    exec(compile(ast.Module(functions, type_ignores=[]), "immutable_adapter.py", "exec"), namespace)
    assert proof["profiles"] == adapter._ROLE_MODEL_PREDECESSOR_PROFILE_HASHES
    for constraint in (None, "luna-only"):
        label = constraint or "default"
        for name, (model, effort, role) in module.agent_profiles(constraint).items():
            raw = (base / label / name).read_bytes()
            assert raw == namespace["_agent_profile"](name[:-5], role, model, effort)
            assert hashlib.sha256(raw).hexdigest() == proof["profiles"][label][name]
            assert adapter._agent_profile_state(raw, name, constraint) in {"current", "legacy"}
            assert adapter._agent_profile_state(raw + b"\n# private edit", name, constraint) == "user"
            other = next(candidate for candidate in proof["profiles"][label] if candidate != name)
            assert adapter._agent_profile_state(raw, other, constraint) == "user"
    for name, expected, state in (
        ("managed", namespace["_render_managed"]().encode(), lambda raw: adapter._managed_agents_state(raw.decode())),
        ("role_packs", namespace["_render_role_packs"]().encode(), adapter._role_pack_state),
        ("role_registry", module.render_registry_document(), adapter._role_registry_state),
    ):
        raw = (base / (name + ".md")).read_bytes()
        assert raw == expected
        assert hashlib.sha256(raw).hexdigest() == proof[name + "_sha256"]
        assert state(raw) in {"current", "legacy"}
        edited = raw.replace(b"<!-- thaliris:end -->", b"private edit\n<!-- thaliris:end -->") if name == "managed" else raw + b"private edit"
        assert state(edited) == "user"


def test_resident_sections_exclude_recovery_and_host_maintenance():
    assert set(controller_instructions.RESIDENT_SECTIONS).isdisjoint({"task-recovery", "host-maintenance"})


def test_selected_runner_quote_preserves_platform_shell_identity():
    path = Path("selected home/quote'and;$literal/runner")
    assert shlex.split(controller_instructions.runner_command(path, platform="posix")) == [str(path)]
    assert controller_instructions.runner_command(path, platform="nt") == "& '" + str(path).replace("'", "''") + "'"


@pytest.mark.parametrize("execution_constraint", [None, "luna-only"], ids=["default", "luna-only"])
def test_pre_normalization_luna_profiles_upgrade_and_remove_only_owned_bytes(
    tmp_path, monkeypatch, pinned_test_thaliris, execution_constraint
):
    fixture_dir = Path(__file__).parent / "fixtures/prompt-contract-before-luna-only"
    provenance = json.loads((fixture_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["revision"] == "6396e138a0ccde3e4e34e961912fa627c30c7ff1"
    assert provenance["execution_constraint"] == "luna-only"
    assert provenance["profiles"] == adapter._PRE_NORMALIZATION_LUNA_ONLY_PROFILE_HASHES

    historical = {name: (fixture_dir / name).read_bytes() for name in provenance["profiles"]}
    for name, raw in historical.items():
        assert hashlib.sha256(raw).hexdigest() == provenance["profiles"][name]
        assert adapter._agent_profile_state(raw, name) == "legacy"
        assert adapter._agent_profile_state(raw, name, "luna-only") == "legacy"
        assert adapter._agent_profile_state(raw + b"\n# user edit", name) == "user"
        other_name = next(candidate for candidate in historical if candidate != name)
        assert adapter._agent_profile_state(raw, other_name) == "user"

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    adapter.init(root)

    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    agents = home / "agents"
    agents.mkdir(parents=True)
    for name, raw in historical.items():
        (agents / name).write_bytes(raw)

    edited_name = "thaliris-focused-implementer.toml"
    edited = historical[edited_name] + b"\n# user edit"
    (agents / edited_name).write_bytes(edited)
    wrong_name = "thaliris-verifier.toml"
    wrong_filename_bytes = historical["thaliris-reasoning-specialist.toml"]
    wrong_target = agents / wrong_name
    wrong_target.write_bytes(wrong_filename_bytes)
    assert adapter._agent_profile_state(wrong_filename_bytes, wrong_name) == "user"

    before = {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()}
    installed = authorized_host_install(
        tmp_path, pinned_test_thaliris, execution_constraint=execution_constraint,
        _legacy_owned_bytes=legacy_file_hashes(
            home, [f"agents/{name}" for name in set(historical) - {edited_name, wrong_name}]
        ),
    )
    assert installed["ok"] is False
    assert installed["changed"] is False
    assert installed["manual_action_required"]
    assert (agents / edited_name).read_bytes() == edited
    assert wrong_target.read_bytes() == wrong_filename_bytes
    assert {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()} == before

    removed = authorized_host_uninstall(tmp_path, pinned_test_thaliris)
    assert removed["ok"] is True
    assert removed["changed"] is False
    assert {path.name: path.read_bytes() for path in agents.iterdir() if path.is_file()} == before
    assert (agents / edited_name).read_bytes() == edited
    assert wrong_target.read_bytes() == wrong_filename_bytes


def test_project_sync_preserves_nonowned_bytes_and_unknown_edits():
    base = Path(__file__).parent / "fixtures/prompt-contract-before/managed.md"
    old = base.read_text(encoding="utf-8")
    mixed = "private prefix\n" + old + "\nprivate suffix\n"
    updated = adapter._managed_agents(mixed)
    assert updated.startswith("private prefix\n") and updated.endswith("\nprivate suffix\n")
    assert adapter.render_managed().strip() in updated
    edited = mixed.replace("<!-- thaliris:end -->", "user edit\n<!-- thaliris:end -->")
    assert adapter._managed_agents(edited) == edited
    with pytest.raises(ValueError, match="damaged"):
        adapter._managed_agents(old + "<!-- thaliris:begin -->")
