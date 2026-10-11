"""Prompt contracts and real prior-generator ownership; no scheduler simulation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import types

import pytest

from thaliris_codex import codex_adapter as adapter, controller_instructions, roles, wait_guidance_config

FIXTURES = Path(__file__).parent / "fixtures/all-layer-wait-predecessor"


@pytest.mark.parametrize("role", [role for role in roles.role_choices() if role != "controller"])
def test_every_role_checks_independent_work_before_waiting(role):
    text = roles.get_role(role).instructions
    assert text.index("First continue independent work") < text.index("Only call wait_agent")
    assert "unfinished direct child whose result is necessary" in text
    assert "no other higher-priority work" in text
    assert "observe only your direct dependencies" in text
    assert "With confirmed meaningful-event early return and user interruption and no interim decision" in text
    assert "default to the supported 60-minute window (timeout_ms=3600000)" in text
    assert "completion can wake the parent early" in text
    assert "unconfirmed capabilities remain UNKNOWN" in text
    assert "Actual tool limits, explicit applicable higher-level limits and exceptions take precedence" in text
    assert "neither fixed 60 seconds nor fixed 60 minutes fits every task" in text
    assert "Windows are not execution deadlines" in text
    assert "tool maximum is capacity" not in text


@pytest.mark.parametrize("role", ["implementer", "focused-implementer", "reviewer"])
def test_scanner_parents_use_shared_events_and_direct_process_observation(role):
    text = roles.get_role(role).instructions
    for clause in (
        "waiting for an Investigator Scanner", "without per-child polling loops",
        "messages and timeouts do not prove completion", "exceptions do not fabricate terminal evidence",
        "A wake-only result needs one available exact native status check",
        "use valid completion once without repeated confirmation",
        "After timeout, reassess the necessary direct dependency and available independent work",
        "do not repeat useless waits indefinitely", "Do not substitute sleep",
        "high-frequency queries, heartbeat services or status-only model wakeups",
        "continue work without elapsed-time progress messages",
        "report only completion, key blockers, major discoveries or necessary upper-level decisions",
        "corresponding tool's actual waiting capability, not wait_agent parameters",
    ):
        assert clause in text


def test_controller_and_install_guidance_apply_all_layer_priority():
    for text in (controller_instructions.render(section="completion"), wait_guidance_config.GUIDANCE):
        text = " ".join(text.split())
        assert "independent work" in text and "higher-priority work" in text
        assert "direct dependencies" in text
        assert "user interruption" in text and "confirmed" in text
        assert "3600000" in text
        assert "exceptions do not fabricate terminal evidence" in text
        assert "After timeout, reassess" in text
        assert "avoid infinite useless waits" in text
        assert "only completion, key blockers, major discoveries" in text
        assert "elapsed-time" in text
        assert "not execution deadlines" in text or "not a required child execution duration" in text


def test_exact_previous_profiles_keep_filename_bound_ownership():
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
        assert adapter._ALL_LAYER_WAIT_PREDECESSOR_PROFILE_HASHES == manifest["profiles"]
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
