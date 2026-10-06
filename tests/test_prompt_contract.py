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

import pytest

from thaliris_codex import codex_adapter as adapter, roles


def normalized(text):
    return " ".join(text.lower().split())


def concepts(text, *groups):
    """Each concept has short semantic anchors, not a whole fixed paragraph."""
    text = normalized(text)
    for group in groups:
        assert all(anchor in text for anchor in group), group


def prompt(role):
    return roles.get_role(role).instructions


def test_runtime_ownership_has_one_normal_layer_per_concern():
    global_text = adapter._global_agents_block().decode()
    project = adapter.render_managed()
    concepts(global_text, ("codex-bootstrap", "task_start_receipt", "authority-contract"),
             ("invalid_state", "task-recover-state", "task-recover-authority"),
             ("offline_recovery.py", "unknown", "fences"),
             ("global", "security", "activation"))
    # Role microstyle and endpoint are not a second global runtime authority.
    for omitted in ("smallest relevant tests", "focused-test pass", "reviewer reopen"):
        assert omitted not in normalized(global_text)
    concepts(project, ("controller", "direction", "scope", "acceptance", "methods"),
             ("decision-complete", "authoritative", "derived", "verification entry"),
             ("workstreams", "convergence", "fresh ordinary"))
    assert "stale text" not in normalized(project)
    assert "stale text" in normalized(prompt("implementer"))
    assert "task-recover-authority" not in prompt("implementer")
    assert prompt("implementer") in adapter.render_role_packs()


@pytest.mark.parametrize("role", list(roles.native_role_definitions()), ids=lambda r: r.id)
def test_child_contract_is_private_selected_and_boundary_preserving(role):
    concepts(role.instructions, ("spawn message", "sole task-specific input"),
             ("controller", "direction", "scope", "acceptance", "routing"),
             ("hard invariants", "decided boundaries", "decision-changing unknown", "final"),
             ("private", "no ordinary progress", "distilled result", "artifact"))
    assert "controller routes registered" not in normalized(role.instructions)


@pytest.mark.parametrize("role", ["implementer", "focused-implementer"])
def test_execution_observation_mutation_verification_and_recovery_loop(role):
    value = prompt(role)
    concepts(value, ("before first mutation", "current mutation surfaces", "authoritative", "derived", "verification entry"),
             ("completed investigator discovery", "decision-critical originals", "without repeating"),
             ("observation", "coherent semantic mutation", "verify", "repair from new evidence"),
             ("independently verifiable", "smallest relevant tests", "coupled"),
             ("authoritative source", "existing generator", "derived outputs"),
             ("stale", "bounded authoritative region", "reconstruct", "method", "change methods"),
             ("cwd", "quoting", "mechanically", "without restarting semantic inquiry"),
             ("no", "retry", "tool", "token", "time", "thresholds"),
             ("host protocol", "serialization", "identity", "schemas", "evidence"))
    assert normalized(roles._EXECUTOR_INSTRUCTIONS) in normalized(value)
    assert "ordinary regression" not in normalized(roles._EXECUTOR_INSTRUCTIONS)


def test_ordinary_converges_assignment_and_focused_endpoint_is_not_extended():
    ordinary, focused = prompt("implementer"), prompt("focused-implementer")
    concepts(ordinary, ("stable accepted direction", "deterministic convergence"),
             ("same session", "smallest acceptance-relevant"),
             ("original acceptance", "git closure", "unfinished assignment"))
    concepts(focused, ("full reasoning", "implementation", "runtime feedback", "revision loop"),
             ("core implementation", "hard invariants", "unknowns are resolved", "focused evidence"),
             ("remaining tasks", "causal model", "architecture", "contract", "scope", "acceptance", "direction"),
             ("pass alone", "endpoint"),
             ("regression", "lint", "build", "synchronization", "compatibility", "deterministic defects", "installation", "git closure", "fresh ordinary"),
             ("shared executor guidance", "does not extend"),
             ("candidate sources or diff", "evidence and limits", "remaining tasks", "escalation boundary"))
    assert "may remain in this workstream" not in normalized(focused)
    assert "runtime feedback" not in normalized(ordinary)
    concepts(focused, ("installation or smoke feedback", "semantic defect"),
             ("formal documentation", "establishes core semantics"))


def test_reviewer_critical_evidence_and_correction_boundary():
    concepts(prompt("reviewer"), ("converged candidate", "original acceptance", "hard invariants", "cross-boundary"),
             ("non-writing", "do not repair"),
             ("counterevidence", "finding"), ("inadequate evidence", "unverified", "insufficient"),
             ("ready only", "evidence", "critical closure"),
             ("absence", "not verified acceptance"),
             ("bounded defect", "design unchanged", "fresh ordinary"),
             ("architecture", "contract", "invariant", "scope", "acceptance", "decision basis", "controller reopen"),
             ("finding", "affected surface", "needed validation"))
    assert not roles.repo_write_allowed("reviewer")


def test_discovery_challenge_knowledge_and_delegation_capabilities():
    concepts(prompt("investigator"), ("facts", "broad evidence", "architecture decisions", "controller"),
             ("batch", "stop", "sufficient"),
             ("exact source locations", "affected surfaces", "unknowns", "covered and uncovered", "by area"))
    concepts(prompt("reasoning-specialist"), ("independently challenge", "framing", "decision basis"),
             ("hidden assumptions", "causal model", "premature convergence", "alternatives"),
             ("coherent", "unexpected", "critical missing facts"))
    concepts(prompt("curator"), ("controller-selected", "prior memory", "index", "canonical sources"),
             ("provenance", "historical", "traceable"), ("no write", "sufficient"))
    for role in ("investigator", "curator", "reasoning-specialist", "verifier"):
        assert not roles.get_codex_binding(role).allowed_delegation_targets
    for role in ("implementer", "focused-implementer", "reviewer"):
        assert roles.get_codex_binding(role).allowed_delegation_targets == frozenset({"investigator"})
        concepts(prompt(role), ("fresh investigator", "scanner", 'fork_turns="none"'))


def test_controller_selects_roles_and_accounts_for_goals():
    value = adapter.render_managed()
    concepts(value, ("minimum necessary", "work shape", "not a ladder", "threshold"),
             ("investigator", "broad facts", "architecture"),
             ("ordinary implementer", "deterministic convergence", "focused implementer", "coupled"),
             ("automatic routing stops at sol", "astra", "current-task", "authorization"),
             ("luna-only", "semantic roles", "forbids astra"),
             ("every explicit user goal", "addressed", "deferred", "dependency"))
    assert not {"scanner", "executor", "astra"} & set(roles.role_choices())
    assert roles.resolve_native_profile("thaliris-focused-implementer-astra-medium").id == "focused-implementer"


def test_profile_styles_remain_specific_without_extending_endpoint():
    base = prompt("focused-implementer")
    sol = roles.profile_instructions("focused-implementer", "thaliris-focused-implementer")
    astra = roles.profile_instructions("focused-implementer", "thaliris-focused-implementer-astra-medium")
    assert sol.startswith(base) and astra.startswith(base)
    assert "With the Sol" in sol and "explicitly user-authorized Astra" not in sol
    assert "explicitly user-authorized Astra" in astra and "With the Sol" not in astra
    assert "With the Sol" not in base
    for value in (sol, astra):
        concepts(value, ("known unfinished scanner", "needed", "after its final", "without another wait"),
                 ("shared executor guidance", "does not extend"))


def test_generated_sources_equal_derived_outputs():
    assert Path("AGENTS.md").read_text(encoding="utf-8") == adapter.render_managed()
    assert Path("docs/thaliris-role-packs.md").read_text(encoding="utf-8") == adapter.render_role_packs()
    for name, (model, effort, role) in roles.agent_profiles().items():
        path = Path(".codex/agents") / name
        if path.is_file():
            assert path.read_bytes() == adapter._agent_profile(name[:-5], role, model, effort)
        parsed = tomllib.loads(adapter._agent_profile(name[:-5], role, model, effort).decode())
        assert parsed["developer_instructions"] == roles.profile_instructions(role, name[:-5])


def test_precision_and_operational_acceptance_are_controller_owned():
    project = adapter.render_managed()
    concepts(project, ("stable narrative base language", "precision-bearing original terms"),
             ("quotations", "distinctions", "user formulations", "materially"),
             ("blur", "broaden", "narrow", "expand"),
             ("forced monolingual", "random language switching", "bilingual repetition"),
             ("output language requirements", "compression and handoff"),
             ("operational artifact", "source", "revision", "provenance", "before delegation"),
             ("later workstream", "operational acceptance"),
             ("project/package", "fixtures", "isolated smoke", "packed artifacts", "project-local"),
             ("effective live", "global instructions", "profiles", "hooks", "trust", "separate"))
    assert normalized(project).count("stable narrative base language") == 1
    assert "stable narrative base language" not in adapter._global_agents_block().decode()
    for role in roles.native_role_definitions():
        assert "stable narrative base language" not in role.instructions


def test_compatibility_authority_and_fresh_rerouting_preserve_semantic_endpoint():
    project = adapter.render_managed()
    concepts(project, ("independently deterministic", "accepted contract uniquely determines"),
             ("compatibility authority ambiguity remains semantic", "production behavior", "historical fixtures"),
             ("representative evidence", "dependency to controller", "does not mandate full regression"),
             ("same semantic closure", "fresh ordinary session", "explicit inputs", "independent acceptance"),
             ("accumulated debugging state adds no benefit", "distilled invariants", "green evidence"),
             ("provenance", "remaining acceptance", "blockers", "not raw history"))
    for role in ("implementer", "focused-implementer"):
        concepts(prompt(role), ("authority ambiguity", "compatibility", "ownership", "security", "lifecycle", "contract"),
                 ("many failures", "many files", "long regression alone", "do not require escalation"),
                 ("project installation closure excludes effective live host", "separate authority"))
    concepts(prompt("focused-implementer"), ("production behavior", "historical fixtures", "representative evidence"),
             ("dependency to controller", "do not classify", "mechanical compatibility"),
             ("full regression by default"))
    concepts(project, ("unchanged deterministic state", "runtime can wait", "meaningful or terminal event"))


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
