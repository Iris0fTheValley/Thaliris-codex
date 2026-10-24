"""Role-local decisions, Controller distribution and exact predecessor ownership.

Prompt assertions prove the emitted contract, not a model's behavioral compliance.
The fixture pins immutable source/renderer bytes independently of this candidate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tomllib
import types

from thaliris_codex import codex_adapter as adapter, codex_bootstrap, controller_instructions, roles


def test_child_profiles_keep_local_decisions_without_controller_routing_or_protocols():
    controller = controller_instructions.resident("runner")
    assert controller.strip() in codex_bootstrap.controller_guidance().replace(
        codex_bootstrap._controller_guidance_runner(), "runner"
    )
    for policy in (None, "luna-only"):
        for name, (model, effort, role) in roles.agent_profiles(policy).items():
            text = tomllib.loads(adapter._agent_profile(name[:-5], role, model, effort).decode())["developer_instructions"]
            assert "task-observe" in text
            if roles.get_codex_binding(role).allowed_delegation_targets:
                assert 'fork_turns="none"' in text and "fork_context=false" in text
                assert roles._FOCUSED_SCANNER_INSTRUCTIONS in text


def test_role_ownership_predecessor_migrates_only_exact_filename_bound_bytes():
    base = Path(__file__).parent / "fixtures/role-ownership-before"
    proof = json.loads((base / "provenance.json").read_text(encoding="utf-8"))
    assert proof["commit"] == "936fac07f73d6405a3300aafcc6262d176aa6b61"
    source = (base / "roles.py.blob").read_bytes()
    assert hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest() == proof["roles_git_blob"]
    renderer = (base / "profile_renderer.py.blob").read_bytes()
    assert hashlib.sha256(renderer).hexdigest() == proof["renderer_sha256"]
    old = types.ModuleType("role_ownership_immutable_roles")
    sys.modules[old.__name__] = old
    try:
        exec(compile(source, "immutable_roles.py", "exec"), old.__dict__)
        namespace = {"roles": old, "json": json}
        exec(compile(renderer, "immutable_profile_renderer.py", "exec"), namespace)
        assert proof["profiles"] == adapter._ROLE_OWNERSHIP_PREDECESSOR_PROFILE_HASHES
        for policy, expected in proof["profiles"].items():
            constraint = None if policy == "default" else policy
            for name, (model, effort, role) in old.agent_profiles(constraint).items():
                raw = namespace["_agent_profile"](name[:-5], role, model, effort)
                assert hashlib.sha256(raw).hexdigest() == expected[name]
                assert adapter._agent_profile_state(raw, name, constraint) == "legacy"
                assert adapter._agent_profile_state(raw + b"\n# user edit", name, constraint) == "user"
                other = next(candidate for candidate in expected if candidate != name)
                assert adapter._agent_profile_state(raw, other, constraint) == "user"
    finally:
        sys.modules.pop(old.__name__, None)
    managed = (base / "managed.md").read_bytes()
    assert hashlib.sha256(managed).hexdigest() == proof["managed_sha256"]
    assert hashlib.sha256(managed.removesuffix(b"\n")).hexdigest() == proof["managed_span_sha256"]
    assert adapter._managed_agents_state(managed.decode()) == "legacy"
    assert adapter._managed_agents_state(managed.decode().replace("<!-- thaliris:end -->", "user edit\n<!-- thaliris:end -->")) == "user"
    packs = (base / "role-packs.md").read_bytes()
    assert hashlib.sha256(packs).hexdigest() == proof["role_pack_sha256"]
    assert adapter._role_pack_state(packs) == "legacy"
    assert adapter._role_pack_state(packs + b"user edit") == "user"
