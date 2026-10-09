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


def require_local_prohibition(text, *, action, target):
    """Require negation in the same clause as a role action and its target."""
    clauses = re.split(r"[.!?;:\n]+", text.lower())
    action_pattern = re.compile(rf"\b{re.escape(action)}(?:s|ed|ing)?\b")
    target_pattern = re.compile(rf"\b{re.escape(target)}\b")
    negative_pattern = re.compile(r"\b(?:not|never|cannot|can't|mustn't|prohibited)\b")
    assert any(action_pattern.search(clause) and target_pattern.search(clause)
               and negative_pattern.search(clause) for clause in clauses), (
        f"missing local prohibition: {action} {target}"
    )


def test_concept_coverage_tolerates_rewording_but_keeps_required_boundaries():
    concepts("The Controller preserves acceptance and scope; readonly boundaries hold.",
             ("controller scope acceptance", "readonly boundaries"))
    with pytest.raises(AssertionError, match="readonly"):
        concepts("The Controller preserves scope and acceptance.", ("readonly boundaries",))


def prompt(role):
    return roles.get_role(role).instructions


def test_runtime_ownership_has_one_normal_layer_per_concern():
    global_text = adapter._global_agents_block().decode()
    project = adapter.render_managed()
    controller = controller_instructions.render()
    resident = codex_bootstrap.controller_guidance()
    concepts(global_text, ("installed pinned runner", "controller-instructions"),
             ("human decision", "isolation", "readonly boundaries"),
             ("unknown user-owned bytes", "native activation"))
    for controller_detail in ("authority-contract", "task-recover-state", "task-recover-authority", "offline_recovery.py"):
        assert controller_detail not in normalized(global_text)
        assert controller_detail in normalized(controller)
    for obsolete_admission_detail in ("task_start_receipt", "--bootstrap-receipt"):
        assert obsolete_admission_detail not in normalized(controller)
    for name in controller_instructions.RESIDENT_SECTIONS:
        # Necessary normal bootstrap returns the canonical guidance; no extra get
        # or full Controller injection into each fresh native child is required.
        section = controller_instructions.render(section=name)
        if name == "startup":
            concepts(resident, ("codex-bootstrap", "authority-contract", "explicit contract admission"))
        else:
            assert section.strip() in resident
            assert section.strip() not in global_text
    # Role microstyle and endpoint are not a second global runtime authority.
    for omitted in ("smallest relevant tests", "focused-test pass", "reviewer reopen"):
        assert omitted not in normalized(global_text)
    concepts(project, ("controller", "direction", "scope", "acceptance", "methods"),
             ("selected spawn handoff", "unselected material", "ordinary local repair"),
             ("controller instructions", "role docs", "codex protocol"))
    concepts(controller, ("decision-complete handoff", "authoritative source", "derived relationships", "verification entry"),
             ("workstreams", "convergence", "fresh ordinary"))
    assert "stale regions" not in normalized(project)
    assert "stale regions" in normalized(prompt("implementer"))
    assert "task-recover-authority" not in prompt("implementer")
    assert prompt("implementer") in adapter.render_role_packs()


@pytest.mark.parametrize("role", list(roles.native_role_definitions()), ids=lambda r: r.id)
def test_child_contract_is_private_selected_and_boundary_preserving(role):
    concepts(role.instructions, ("spawn message", "sole task-specific input"),
             ("preserve its decisions", "hard invariants", "acceptance"),
             ("decision-changing unknowns", "final", "contradictions"),
             ("working sets", "tool logs", "private", "no ordinary progress", "artifact"))
    assert "controller routes registered" not in normalized(role.instructions)


@pytest.mark.parametrize("role", ["implementer", "focused-implementer"])
def test_execution_observation_mutation_verification_and_recovery_loop(role):
    value = prompt(role)
    concepts(value, ("before mutation", "acceptance-relevant surfaces", "authoritative sources", "derived relationships", "verification entry"),
             ("reuse selected discovery", "decision-critical originals", "without repeating inventory"),
             ("coherent change", "verify", "repair ordinary local defects", "new evidence"),
             ("independent slices", "smallest meaningful tests", "coupled changes"),
             ("canonical sources", "existing sync path", "derived outputs"),
             ("stale regions", "reconstructing edits", "unsuitable methods", "change unsuitable methods"),
             ("cwd", "quoting", "mechanically", "environment mistakes"),
             ("no retry/tool/token/time/closure thresholds"),
             ("host schemas", "protocol", "identity", "serialization", "evidence"))
    assert normalized(roles._EXECUTOR_INSTRUCTIONS) in normalized(value)
    assert "ordinary regression" not in normalized(roles._EXECUTOR_INSTRUCTIONS)


def test_ordinary_converges_assignment_and_focused_endpoint_is_not_extended():
    ordinary, focused = prompt("implementer"), prompt("focused-implementer")
    concepts(ordinary, ("stable accepted direction", "deterministic convergence"),
             ("same session", "smallest acceptance-relevant"),
             ("original acceptance", "git closure", "unfinished assignment"))
    concepts(focused, ("full reasoning", "implementation", "runtime-feedback", "revision loop"),
             ("core solution", "hard invariants", "unknowns are resolved", "focused evidence"),
             ("remaining tasks", "causal model", "architecture", "contract", "scope", "acceptance", "direction"),
             ("pass alone", "endpoint"),
             ("regression", "lint", "build", "generated/docs sync", "compatibility", "deterministic defects", "project/package install-smoke", "git closure", "fresh ordinary"),
             ("shared guidance", "cannot extend"),
             ("exact candidate/diff", "evidence and limits", "remaining tasks", "escalation boundary"))
    assert "may remain in this workstream" not in normalized(focused)
    assert "runtime feedback" not in normalized(ordinary)
    concepts(focused, ("including package/install smoke", "evidence could change the core solution"),
             ("sync formal docs", "where they establish core semantics"))


def test_reviewer_critical_evidence_and_correction_boundary():
    reviewer = prompt("reviewer")
    concepts(reviewer, ("converged candidate", "original acceptance", "hard invariants", "cross-boundary"),
             ("non-writing",),
             ("counterevidence", "finding"), ("inadequate evidence", "unverified", "insufficient"),
             ("ready only", "evidence", "critical closure"),
             ("absence", "not verified acceptance"),
             ("bounded defect", "design unchanged", "fresh ordinary"),
             ("architecture", "contract", "invariant", "scope", "acceptance", "decision basis", "controller reopen"),
             ("finding", "affected surface", "needed validation"))
    require_local_prohibition(reviewer, action="repair", target="candidate")
    mutated = reviewer.replace("do not repair the candidate", "do repair the candidate", 1)
    assert mutated != reviewer
    with pytest.raises(AssertionError, match="local prohibition"):
        require_local_prohibition(mutated, action="repair", target="candidate")
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
    value = controller_instructions.render()
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
        concepts(value, ("wait only", "needed result", "unfinished", "without another wait"),
                 ("shared guidance", "cannot extend"))


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


def test_precision_and_operational_acceptance_are_controller_owned():
    controller = controller_instructions.render()
    concepts(controller, ("stable narrative base language", "precision-bearing original terms"),
             ("quotations", "distinctions", "user formulations", "materially"),
             ("blur", "broaden", "narrow", "expand"),
             ("forced monolingual", "random language switching", "bilingual repetition"),
             ("output language requirements", "compression and handoff"),
             ("operational artifact", "source", "revision", "provenance", "before delegation"),
             ("later workstream", "operational acceptance"),
             ("project/package", "fixtures", "isolated smoke", "packed artifacts", "project-local"),
             ("effective live", "global instructions", "profiles", "hooks", "trust", "separate"))
    assert normalized(controller).count("stable narrative base language") == 1
    assert "stable narrative base language" not in adapter._global_agents_block().decode()
    assert "stable narrative base language" in codex_bootstrap.controller_guidance()
    assert "stable narrative base language" not in adapter.render_managed()
    for role in roles.native_role_definitions():
        assert "stable narrative base language" not in role.instructions


def test_compatibility_authority_and_fresh_rerouting_preserve_semantic_endpoint():
    controller = controller_instructions.render()
    concepts(controller, ("independently deterministic", "accepted contract uniquely determines"),
             ("compatibility authority ambiguity remains semantic", "production behavior", "historical fixtures"),
             ("representative evidence", "dependency to controller", "does not mandate full regression"),
             ("same semantic closure", "fresh ordinary session", "explicit inputs", "independent acceptance"),
             ("accumulated debugging state adds no benefit", "distilled invariants", "green evidence"),
             ("provenance", "remaining acceptance", "blockers", "not raw history"),
             ("unchanged deterministic state", "runtime can wait", "meaningful or terminal event"))
    for role in ("implementer", "focused-implementer"):
        concepts(prompt(role), ("compatibility", "ownership", "security", "lifecycle", "contract"),
                 ("volume or difficulty alone does not require escalation"),
                 ("project/package smoke", "does not authorize live host maintenance"))
    concepts(prompt("focused-implementer"), ("production and historical fixtures", "compatibility authority undecided", "representative evidence"),
             ("return the dependency", "never call that mechanical compatibility"),
             ("full regression by default"))


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


def test_resident_waiting_observation_and_causal_contract_rejects_negation_reversal():
    value = controller_instructions.render()
    for text in (value, prompt("implementer"), prompt("focused-implementer")):
        concepts(text, ("observation", "tests", "processes", "ci", "controller", "result"),
                 ("substantive changes", "terminal evidence"),
                 ("tool maximum", "capacity", "higher-level duration limits", "precedence"),
                 ("original failure", "local reproduction", "root cause"))
        require_local_prohibition(text, action="recommend", target="duration")
        mutant = re.sub(r"\bnot a recommended duration\b", "a recommended duration", text)
        with pytest.raises(AssertionError, match="local prohibition"):
            require_local_prohibition(mutant, action="recommend", target="duration")
    require_local_prohibition(value, action="bypass", target="hooks")
    require_local_prohibition(value, action="poll", target="child")
    with pytest.raises(AssertionError, match="local prohibition"):
        require_local_prohibition(value.replace("Do not poll a finished child", "Do poll a finished child"), action="poll", target="child")
    concepts(value, ("active/pending", "slot", "not a lifetime quota", "proved terminal completion"),
             ("selected candidate", "criteria", "final product acceptance"),
             ("complete normal task context", "retrieval cost", "quality"))
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
