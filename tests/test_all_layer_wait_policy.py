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


@pytest.mark.parametrize("role", ["controller", "implementer", "focused-implementer", "reviewer"])
def test_delegating_roles_check_independent_work_before_waiting(role):
    text = controller_instructions._WAITING_INSTRUCTIONS if role == "controller" else roles._instructions(role)
    assert text.index("First continue independent work") < text.index("Only call wait_agent")
    assert "monitoring, rereading, repeated searching or patrolling the same delegated Workstream is not independent work" in text.lower().replace("workstream", "Workstream")
    assert "wait for a decision-changing native event" in text.lower()
    assert "unfinished direct child whose result is necessary" in text
    assert "no other higher-priority work" in text
    assert "observe only your direct dependencies" in text
    assert "unconfirmed capabilities remain UNKNOWN" in text
    if role == "controller":
        assert "With confirmed meaningful-event early return and user interruption and no interim decision" in text
        assert "default to the supported 60-minute window (timeout_ms=3600000); completion can wake the parent early" in text
        assert "Windows are not execution deadlines" in text
        assert "Actual tool limits, explicit applicable higher-level limits and exceptions take precedence" in text
        assert "neither fixed 60 seconds nor fixed 60 minutes fits every task" in text
    else:
        assert "tool's documented limits, meaningful-event early return and user interruption" in text
        assert "3600000" not in text and "60-minute" not in text
        assert "semantically usable FINAL without another lifecycle wait" in text
    assert "tool maximum is capacity" not in text


@pytest.mark.parametrize("role", ["implementer", "focused-implementer", "reviewer"])
def test_scanner_parents_use_shared_events_and_direct_process_observation(role):
    text = roles.get_role(role).instructions
    for clause in (
        "fresh Investigator Scanner", "without per-child polling loops",
        "messages and timeouts do not prove completion", "exceptions do not fabricate terminal evidence",
        "A wake-only result needs one available exact native status check",
        "use valid completion once without repeated confirmation",
        "After timeout, reassess the necessary direct dependency and available independent work",
        "do not repeat useless waits indefinitely", "Do not substitute sleep",
        "high-frequency queries, heartbeat services or status-only model wakeups",
        "Continue work without elapsed-time progress messages",
        "report only completion, key blockers, major discoveries or necessary upper-level decisions",
        "corresponding tool's actual waiting capability, not wait_agent parameters",
    ):
        assert clause in text


@pytest.mark.parametrize("role", ["investigator", "curator", "verifier", "reasoning-specialist"])
def test_non_delegating_roles_only_receive_work_notification_evidence_principles(role):
    text = roles.get_role(role).instructions
    assert "Continue necessary independent work before waiting" in text
    assert "Messages, timeouts and exceptions do not prove completion" in text
    assert "no ordinary progress, heartbeat or partial-completion messages" in text
    for parent_policy in ("wait_agent", "3600000", "60-minute", "direct child", "wake-only", "per-child polling"):
        assert parent_policy not in text
    assert "Do not delegate" in text


def test_controller_uses_the_canonical_parent_wait_policy_once():
    text = controller_instructions.render(section="completion")
    assert text.count(controller_instructions._WAITING_INSTRUCTIONS.strip()) == 1
    assert roles._WAITING_INSTRUCTIONS.strip() not in text
    assert "child notifications" in text
    assert "@WAITING_INSTRUCTIONS@" not in controller_instructions.resident("runner")


def test_optional_user_guidance_grants_no_parent_or_closing_role():
    text = wait_guidance_config.GUIDANCE
    assert "grants no role or authority" in text
    assert "applicable role instructions and the selected handoff" in text
    for role_policy in ("wait_agent", "3600000", "Controller", "Implementer", "Scanner", "final acceptance"):
        assert role_policy not in text


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
