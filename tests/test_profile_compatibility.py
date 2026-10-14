"""One target's effective binding must agree before a managed reservation."""
import json
from pathlib import Path

import pytest

from thaliris_codex import codex_adapter, lifecycle, roles
from tests.test_nested_scanner import active, spawn, start, state


def profile(folder, name="thaliris-implementer", *, model=None, effort=None, filename="user-name.toml"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(f'name = "{name}"\ndescription = "User definition"\ndeveloper_instructions = "User-owned role"\n'
                    + (f'model = "{model}"\n' if model is not None else "")
                    + (f'model_reasoning_effort = "{effort}"\n' if effort is not None else ""), encoding="utf-8")
    return path


def deny_without_reservation(root, request, diagnostic):
    before = state(root)
    denied = lifecycle.handle_hook(root, "PreToolUse", request)
    assert diagnostic in denied
    assert "updatedInput" not in denied
    assert state(root) == before


@pytest.mark.parametrize("role", list(roles.ROLE_MODEL_ROUTING_DEFAULTS))
@pytest.mark.parametrize("explicit", [False, True])
def test_every_ordinary_target_fixed_conflict_prevents_reservation(active, role, explicit):
    home = codex_adapter._codex_home()
    target = roles.get_codex_binding(role).native_profile
    path = profile(home / "agents", target, model="gpt-6.1-sol", effort="low", filename=target + ".toml")
    before = path.read_bytes()
    deny_without_reservation(active, spawn(role=role, use_route_defaults=explicit), "ROLE_PROFILE_BINDING_CONFLICT")
    assert path.read_bytes() == before


@pytest.mark.parametrize("scope", ["personal", "project"])
@pytest.mark.parametrize("fixed", [False, True])
def test_target_identity_uses_toml_name_and_allows_equivalent_outcome(active, scope, fixed):
    folder = codex_adapter._codex_home() / "agents" if scope == "personal" else active / ".codex" / "agents"
    path = profile(folder, model="gpt-6-luna" if fixed else None, effort="max" if fixed else None)
    original = path.read_bytes()
    output = json.loads(lifecycle.handle_hook(active, "PreToolUse", spawn(role="implementer", use_route_defaults=False)))
    assert output["hookSpecificOutput"]["updatedInput"]["model"] == "gpt-6-luna"
    assert path.read_bytes() == original


def test_nested_scanner_checks_its_target_only(active):
    parent = start(active)
    profile(active / ".codex" / "agents", "thaliris-investigator", model="gpt-6.1-sol")
    deny_without_reservation(active, spawn(parent, use_route_defaults=False), "ROLE_PROFILE_BINDING_CONFLICT")


def test_other_custom_and_managed_profile_conflicts_do_not_block_target(active):
    folder = active / ".codex" / "agents"
    profile(folder, "other-custom", model="gpt-6-astra")
    profile(folder, "thaliris-reviewer", model="gpt-6-astra", filename="other.toml")
    (folder / "broken-unrelated.toml").write_text("this is not TOML", encoding="utf-8")
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(role="implementer")) == ""


@pytest.mark.parametrize("name", ["thaliris-implementer", None])
def test_legacy_config_file_identity_and_relative_path_are_checked(active, name):
    home = codex_adapter._codex_home()
    path = profile(home / "custom", model="gpt-6.1-sol", effort="low")
    if name is None:
        path.write_text(path.read_text(encoding="utf-8").split("\n", 1)[1], encoding="utf-8")
    hint = "custom-alias" if name else "thaliris-implementer"
    config = home / "config.toml"
    config.write_text(f'[agents.{hint}]\nconfig_file = "custom/user-name.toml"\n', encoding="utf-8")
    original = config.read_bytes(), path.read_bytes()
    deny_without_reservation(active, spawn(role="implementer"), "ROLE_PROFILE_BINDING_CONFLICT")
    assert (config.read_bytes(), path.read_bytes()) == original


def test_model_only_preserves_native_configured_profile_effort(active):
    home = codex_adapter._codex_home()
    target = home / "agents" / "thaliris-implementer.toml"
    profile(target.parent, model="gpt-6.1-sol", effort="low", filename=target.name)
    request = spawn(role="implementer", use_route_defaults=False, model="gpt-6.1-sol")
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    assert "reasoning_effort" not in request["tool_input"]


def test_explicit_nondefault_pair_matching_fixed_profile_is_preserved(active):
    home = codex_adapter._codex_home()
    profile(home / "agents", model="gpt-6.1-sol", effort="low", filename="thaliris-implementer.toml")
    request = spawn(role="implementer", use_route_defaults=False, model="gpt-6.1-sol", reasoning_effort="low")
    original = dict(request["tool_input"])
    assert lifecycle.handle_hook(active, "PreToolUse", request) == ""
    assert request["tool_input"] == original


def test_declared_file_in_discovery_tree_is_not_duplicated_by_filename(active):
    home = codex_adapter._codex_home()
    path = profile(home / "agents" / "nested", model="gpt-6-luna", effort="max")
    (home / "config.toml").write_text('[agents.alias]\nconfig_file="agents/nested/user-name.toml"\n', encoding="utf-8")
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(role="implementer")) == ""
    assert path.is_file()


def test_effort_only_default_model_must_agree_with_profile(active):
    profile(codex_adapter._codex_home() / "agents", model="gpt-6.1-sol")
    deny_without_reservation(active, spawn(role="implementer", use_route_defaults=False, reasoning_effort="low"), "ROLE_PROFILE_BINDING_CONFLICT")


def test_conflicting_duplicate_effort_with_native_omission_is_unknown(active):
    profile(active / ".codex" / "agents", effort="low")
    deny_without_reservation(active, spawn(role="implementer", use_route_defaults=False, model="gpt-6-luna"), "ROLE_PROFILE_BINDING_UNKNOWN")


@pytest.mark.parametrize("shape", ["missing", "malformed", "bad-model", "bad-effort"])
def test_unverifiable_target_returns_unknown_without_reservation(active, shape):
    path = codex_adapter._codex_home() / "agents" / "thaliris-implementer.toml"
    if shape == "missing":
        path.unlink()
    elif shape == "malformed":
        path.write_text("invalid TOML", encoding="utf-8")
    else:
        path.write_text(path.read_text(encoding="utf-8") + ("\nmodel = 2\n" if shape == "bad-model" else "\nmodel_reasoning_effort = 2\n"), encoding="utf-8")
    deny_without_reservation(active, spawn(role="implementer"), "ROLE_PROFILE_BINDING_UNKNOWN")


def test_project_subdirectory_definitions_are_in_scope(active):
    cwd = active / "subdir"
    cwd.mkdir()
    profile(cwd / ".codex" / "agents", model="gpt-6.1-sol")
    request = spawn(role="implementer")
    request["cwd"] = str(cwd)
    deny_without_reservation(active, request, "ROLE_PROFILE_BINDING_CONFLICT")


def test_target_model_free_native_extensions_do_not_change_binding(active):
    path = profile(active / ".codex" / "agents")
    path.write_text(path.read_text(encoding="utf-8") + '\nprofile = "custom"\n[profiles.custom]\nmodel = "gpt-6-astra"\n[features]\nshell_tool = false\n[skills]\ninclude_instructions = false\n', encoding="utf-8")
    before = path.read_bytes()
    assert lifecycle.handle_hook(active, "PreToolUse", spawn(role="implementer")) == ""
    assert path.read_bytes() == before
