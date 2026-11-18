"""The 6.2 model generation: routing defaults, the Astra family guard and the 0.170.0 catalog."""
from __future__ import annotations

import json

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, controller_instructions, lifecycle, model_catalog_config as catalog, roles, task_authority
from tests.model_catalog_fixtures import CLI_0170, catalog_0170
from tests.test_nested_scanner import active, finish, identity, native_return, spawn, start, state  # noqa: F401
from tests.test_upgrade_continuity import _install_profiles, constrained, luna_spawn  # noqa: F401
from tests.test_preadmission_role_routing import project  # noqa: F401

SOL_ROLES = ("reviewer", "focused-implementer", "reasoning-specialist")
LUNA_ROLES = ("investigator", "implementer", "curator", "verifier")


def test_sol_roles_default_to_6_2_sol_and_luna_roles_are_unchanged():
    for role in SOL_ROLES:
        assert roles.ROLE_MODEL_ROUTING_DEFAULTS[role] == ("gpt-6.2-sol", "high")
    for role in LUNA_ROLES:
        assert roles.ROLE_MODEL_ROUTING_DEFAULTS[role] == ("gpt-6-luna", "max")
    routing = controller_instructions.render(section="routing")
    assert "at least `gpt-6.2-sol` at `high`" in routing
    assert "gpt-6.1-sol" not in routing


def test_astra_profiles_default_to_6_2_astra_and_stay_controller_only():
    for role in ("focused-implementer", "reasoning-specialist"):
        assert roles.agent_profiles()[f"thaliris-{role}-astra-medium.toml"] == ("gpt-6.2-astra", "medium", role)
        assert roles.agent_profiles()[f"thaliris-{role}-xhigh.toml"] == ("gpt-6.2-astra", "xhigh", role)
    registry = roles.render_registry_document().decode()
    assert "`gpt-6.2-astra`, `medium`" in registry and "`gpt-6.2-astra`, `xhigh`" in registry
    assert "gpt-6-astra" not in registry


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.2-astra", "gpt-7-astra", "gpt-7.1-astra"])
def test_astra_family_is_matched_by_meaning_not_literal(model):
    assert roles.is_astra_model(model)


@pytest.mark.parametrize("model", [None, 7, "", "gpt-6.2-sol", "gpt-6-luna", "astra", "gpt-astra",
                                   "gpt-6.2-astra-preview", "my-gpt-6-astra", "gpt-6.x-astra"])
def test_non_astra_models_are_not_astra(model):
    assert not roles.is_astra_model(model)


@pytest.mark.parametrize("model", ["gpt-6.2-astra", "gpt-7-astra"])
def test_nested_child_cannot_choose_any_astra_release(active, model):
    parent = start(active)
    denied = lifecycle.handle_hook(active, "PreToolUse", spawn(parent, model=model, reasoning_effort="xhigh"))
    assert "THALIRIS_ROLE_SESSION_DELEGATION" in denied and "Astra" in denied
    assert state(active)["pending_authorized_spawn"] is None


def test_nested_child_may_still_choose_6_2_sol(active):
    parent = start(active)
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(parent, model="gpt-6.2-sol", reasoning_effort="high")) == ""
    assert state(active)["pending_authorized_spawn"]["parent_agent_id_hash"] == lifecycle._identity_hash(parent["agent_id"])


@pytest.mark.parametrize("model", ["gpt-6.2-astra", "gpt-7-astra"])
def test_role_session_spawn_with_any_astra_release_is_refused(project, model):
    root, _home = project
    denied = lifecycle._child_pre_tool_output(root, {
        "agent_type": "thaliris-implementer", "tool_name": "spawn_agent",
        "tool_input": {"agent_type": "thaliris-investigator", "fork_turns": "none", "model": model}})
    assert "explicit Astra selection is Controller-only" in denied


def test_ordinary_spawn_routes_to_6_2_sol(active):
    request = spawn(role="reviewer", use_route_defaults=False)
    output = json.loads(lifecycle.handle_hook(active, "PreToolUse", request))["hookSpecificOutput"]
    assert (output["updatedInput"]["model"], output["updatedInput"]["reasoning_effort"]) == ("gpt-6.2-sol", "high")


@pytest.mark.parametrize("source", ["bundled", "online"])
def test_0170_catalog_patches_including_6_2_models(source):
    raw = catalog_0170(source)
    patched, result = catalog.patch_catalog(raw, cli_version=CLI_0170, source=source)
    assert result["status"] == "COMPATIBLE", result
    expected = sum(1 for model in json.loads(raw)["models"] if catalog.TARGET in model["model_messages"]["instructions_template"])
    assert result["patched_templates"] == expected
    models = {model["slug"]: model for model in json.loads(patched)["models"]}
    for slug in ("gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-terra"):
        template = models[slug]["model_messages"]["instructions_template"]
        assert catalog.TARGET not in template
        assert catalog._MULTILINE_PREVIOUS + "\n" + catalog._NEXT in template
    assert models["gpt-6.2-sol"]["multi_agent_version"] == "v2"
    assert models["gpt-6.2-astra"]["minimal_client_version"] == "0.166.0"


@pytest.mark.parametrize("slug", ["gpt-6.2-sol", "gpt-6.2-astra"])
def test_known_6_2_models_keep_their_observed_target_context(slug):
    patched, result = catalog.patch_catalog(catalog_0170("bundled", previous_for=slug), cli_version=CLI_0170, source="bundled")
    assert patched is None and result["status"] == "TARGET_LOCATION_CHANGED" and result["model_slug"] == slug


def test_6_2_models_are_in_both_known_rosters_and_change_the_reuse_contract():
    for source in ("bundled", "online"):
        assert {"gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-terra"} <= catalog._MODEL_PROFILES[source]["matched"]
    for slug in ("gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-terra"):
        assert catalog._KNOWN_TARGET_CONTEXT[slug] == (catalog._MULTILINE_PREVIOUS, catalog._NEXT)


# --- continuity: ACTIVE tasks started before 6.2 ---------------------------

def test_active_task_child_routed_with_6_1_sol_finishes_after_the_default_change(active):
    child = start(active, "reviewer")
    assert state(active)["children"][0]["handoff_bound"] is True
    finish(active, child)
    assert lifecycle.native_execution_closed(active)
    assert codex_adapter.task_close(active, core.task_show(active)["state"]["revision"])["status"] == "DONE"


def test_constrained_task_with_gpt_6_astra_profiles_continues_after_6_2_render(constrained, monkeypatch):
    root, home = constrained
    # Simulate the predecessor release: its Astra profiles were rendered with gpt-6-astra.
    with monkeypatch.context() as predecessor:
        predecessor.setattr(roles, "ASTRA_DEFAULT_MODEL", "gpt-6-astra")
        _install_profiles(home, "luna-only")
    astra = home / "agents" / "thaliris-focused-implementer-xhigh.toml"
    assert b'model = "gpt-6-astra"' in astra.read_bytes()
    assert task_authority.check(root)["contract"]["execution_constraint"] == "luna-only"
    assert lifecycle.handle_hook(root, "PreToolUse", luna_spawn()) == ""
    # The current release re-renders the profiles with gpt-6.2-astra.
    _install_profiles(home, "luna-only")
    assert b'model = "gpt-6.2-astra"' in astra.read_bytes()
    assert task_authority.check(root)["contract"]["execution_constraint"] == "luna-only"
    child = dict(session_id="root-session", turn_id="child-turn", agent_id="child",
                 agent_type=roles.get_codex_binding("implementer").native_profile, model="gpt-6-luna")
    lifecycle.handle_hook(root, "PostToolUse", {**luna_spawn(), "tool_response": {"agent_id": "child", "nickname": None}})
    assert lifecycle._record_subagent_start(root, child)


def test_receipt_owns_gpt_6_astra_profiles_and_upgrades_them(tmp_path, monkeypatch, pinned_test_thaliris):
    from tests.host_maintenance_test_support import authorized_host_install
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    with monkeypatch.context() as predecessor:
        predecessor.setattr(roles, "ASTRA_DEFAULT_MODEL", "gpt-6-astra")
        assert authorized_host_install(tmp_path, pinned_test_thaliris)["ok"]
    profile = home / "agents" / "thaliris-reasoning-specialist-astra-medium.toml"
    written = profile.read_bytes()
    assert b'model = "gpt-6-astra"' in written
    assert codex_adapter._agent_profile_state(written, profile.name, home=home) == "legacy"
    assert authorized_host_install(tmp_path, pinned_test_thaliris)["ok"]
    assert b'model = "gpt-6.2-astra"' in profile.read_bytes()
