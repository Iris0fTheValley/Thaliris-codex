"""Independent released-source witnesses, never current-output ownership claims."""
import hashlib
import json
from pathlib import Path
import sys
import types

from thaliris_codex import codex_adapter


def test_released_profiles_upgrade_only_with_exact_bytes_and_filename():
    base = Path(__file__).parent / "fixtures/execution-observation-predecessor"
    proof = json.loads((base / "provenance.json").read_text(encoding="utf-8"))
    roles = (base / "roles.py.blob").read_bytes()
    renderer = (base / "profile_renderer.py.blob").read_bytes()
    packs = (base / "role-packs.md").read_bytes()
    assert hashlib.sha256(roles).hexdigest() == proof["roles_sha256"]
    assert hashlib.sha1(b"blob " + str(len(roles)).encode() + b"\0" + roles).hexdigest() == proof["roles_git_blob"]
    assert hashlib.sha256(renderer).hexdigest() == proof["renderer_sha256"]
    assert hashlib.sha1(b"blob " + str(len(packs)).encode() + b"\0" + packs).hexdigest() == proof["role_pack_git_blob"]
    assert hashlib.sha256(packs).hexdigest() == proof["role_pack_sha256"]
    assert codex_adapter._role_pack_state(packs) == "legacy"
    assert codex_adapter._role_pack_state(packs + b"\nuser edit") == "user"
    module = types.ModuleType("observation_predecessor_witness")
    sys.modules[module.__name__] = module
    try:
        exec(compile(roles, "released_roles.py", "exec"), module.__dict__)
        namespace = {"json": json, "roles": module}
        exec(compile(renderer, "released_renderer.py", "exec"), namespace)
        assert proof["profiles"] == codex_adapter._EXECUTION_OBSERVATION_PREDECESSOR_PROFILE_HASHES
        for constraint in (None, "luna-only"):
            for name, (model, effort, role) in module.agent_profiles(constraint).items():
                raw = namespace["_agent_profile"](name[:-5], role, model, effort)
                assert hashlib.sha256(raw).hexdigest() == proof["profiles"][constraint or "default"][name]
                assert codex_adapter._agent_profile_state(raw, name, constraint) == "legacy"
                assert codex_adapter._agent_profile_state(raw + b"\n# user edit", name, constraint) == "user"
                other = next(item for item in module.agent_profiles() if item != name)
                assert codex_adapter._agent_profile_state(raw, other, constraint) == "user"
    finally:
        sys.modules.pop(module.__name__, None)
