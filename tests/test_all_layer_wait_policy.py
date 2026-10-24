"""Prompt contracts and real prior-generator ownership; no scheduler simulation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import types

import pytest

from thaliris_codex import codex_adapter as adapter, controller_instructions, roles

FIXTURES = Path(__file__).parent / "fixtures/all-layer-wait-predecessor"


def test_controller_uses_the_canonical_parent_wait_policy_once():
    text = controller_instructions.render(section="completion")
    assert text.count(controller_instructions._WAITING_INSTRUCTIONS.strip()) == 1
    assert roles._WAITING_INSTRUCTIONS.strip() not in text
    assert "child notifications" in text
    assert "@WAITING_INSTRUCTIONS@" not in controller_instructions.resident("runner")


@pytest.mark.parametrize("fixture_name,hash_registry", [
    ("all-layer-wait-predecessor", adapter._ALL_LAYER_WAIT_PREDECESSOR_PROFILE_HASHES),
    ("role-wait-scope-predecessor", adapter._ROLE_WAIT_SCOPE_PREDECESSOR_PROFILE_HASHES),
])
def test_exact_previous_profiles_keep_filename_bound_ownership(fixture_name, hash_registry):
    FIXTURES = Path(__file__).parent / "fixtures" / fixture_name
    manifest = json.loads((FIXTURES / "provenance.json").read_text(encoding="utf-8"))
    source = (FIXTURES / "roles.py.blob").read_bytes()
    git_blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
    assert git_blob == manifest["roles_git_blob"]
    renderer = (FIXTURES / "profile_renderer.py.blob").read_bytes()
    assert hashlib.sha256(renderer).hexdigest() == manifest["renderer_sha256"]
    old = types.ModuleType("all_layer_wait_historical_roles")
    sys.modules[old.__name__] = old
    try:
        exec(compile(source, "historical_roles.py", "exec"), old.__dict__)
        namespace = {"roles": old, "json": json}
        exec(compile(renderer, "historical_profile_renderer.py", "exec"), namespace)
        assert hash_registry == manifest["profiles"]
        for policy, expected in manifest["profiles"].items():
            for name, (model, effort, role) in old.agent_profiles(None if policy == "default" else policy).items():
                raw = namespace["_agent_profile"](name[:-5], role, model, effort)
                assert hashlib.sha256(raw).hexdigest() == expected[name]
                assert adapter._agent_profile_state(raw, name) in {"current", "legacy"}
                assert adapter._agent_profile_state(raw + b"\n# user edit\n", name) == "user"
                wrong = "thaliris-curator.toml" if name != "thaliris-curator.toml" else "thaliris-investigator.toml"
                assert adapter._agent_profile_state(raw, wrong) == "user"
    finally:
        sys.modules.pop(old.__name__, None)
    historical_guidance = (FIXTURES / "guidance.txt").read_bytes()
    assert hashlib.sha256(historical_guidance).hexdigest() == manifest["guidance_sha256"]
    packs = (FIXTURES / "role-packs.md").read_bytes()
    assert hashlib.sha256(packs).hexdigest() == manifest["role_pack_sha256"]
    assert adapter._role_pack_state(packs) == "legacy"
    assert adapter._role_pack_state(packs + b"\nuser edit\n") == "user"
