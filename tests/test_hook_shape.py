"""Hook-shape compatibility against the Host's own generated hook schemas.

The rust-v0.169.0 fixtures are upstream source JSON (see PROVENANCE.json).
They are evidence for the checker, not a version requirement.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from thaliris_codex import codex_adapter, hook_shape, lifecycle

FIXTURES = Path(__file__).parent / "fixtures" / "codex-hook-schemas" / "rust-v0.169.0"
PROVENANCE = json.loads((FIXTURES / "PROVENANCE.json").read_text(encoding="utf-8"))
UPSTREAM_V2_HOOK_NAMES = PROVENANCE["multi_agent_v2_hook_tool_names"]["names"]


def upstream() -> dict:
    schemas = hook_shape.directory_schemas(FIXTURES)
    assert schemas is not None
    return schemas


def test_upstream_0169_schemas_cover_every_registered_event_and_relied_on_key():
    schemas = upstream()
    assert {name.removesuffix(".command.input") for name in schemas} == set(hook_shape.EVENT_SCHEMAS.values())
    result = hook_shape.check(schemas, tool_names=UPSTREAM_V2_HOOK_NAMES)
    assert result["status"] == "COMPATIBLE"
    assert result["missing_events"] == [] and result["missing_keys"] == {}
    assert result["event_name_contradictions"] == []
    assert result["matchers"]["status"] == "COMPATIBLE"
    assert result["matchers"]["post_tool_unmatched"] == []
    # Root actors legitimately omit agent identity; the Host declares it optional.
    assert "agent_id" not in result["declared_optional_required_keys"].get("PreToolUse", [])


def test_every_registered_event_has_a_schema_mapping():
    assert tuple(hook_shape.EVENT_SCHEMAS) == tuple(lifecycle.HOOK_EVENTS)
    assert set(hook_shape.REQUIRED_INPUTS) == set(lifecycle.HOOK_EVENTS)


@pytest.mark.parametrize("event,key", [
    ("PreToolUse", "tool_use_id"), ("PostToolUse", "tool_response"), ("SubagentStop", "last_assistant_message"),
    ("SubagentStart", "agent_type"), ("SessionStart", "source"), ("Stop", "session_id"),
    ("UserPromptSubmit", "agent_id"),
])
def test_removed_key_is_incompatible_and_named(event, key):
    schemas = deepcopy(upstream())
    title = hook_shape.EVENT_SCHEMAS[event] + ".command.input"
    del schemas[title]["properties"][key]
    result = hook_shape.check(schemas, tool_names=UPSTREAM_V2_HOOK_NAMES)
    assert result["status"] == "INCOMPATIBLE"
    assert any(key in requirement.split("|") for requirement in result["missing_keys"][event])


def test_alias_keeps_a_requirement_satisfied():
    schemas = deepcopy(upstream())
    properties = schemas["pre-tool-use.command.input"]["properties"]
    properties["call_id"] = properties.pop("tool_use_id")
    assert hook_shape.check(schemas)["missing_keys"] == {}


def test_missing_event_and_contradictory_event_constant_are_incompatible():
    schemas = deepcopy(upstream())
    del schemas["subagent-stop.command.input"]
    assert hook_shape.check(schemas)["missing_events"] == ["SubagentStop"]
    schemas = deepcopy(upstream())
    schemas["stop.command.input"]["properties"]["hook_event_name"]["const"] = "SessionEnd"
    result = hook_shape.check(schemas)
    assert result["status"] == "INCOMPATIBLE" and result["event_name_contradictions"] == ["Stop"]


@pytest.mark.parametrize("schemas", [None, {}])
def test_unobservable_schemas_are_unknown_never_compatible(schemas):
    result = hook_shape.check(schemas, tool_names=UPSTREAM_V2_HOOK_NAMES)
    assert result["status"] == "UNKNOWN"


def test_matchers_without_observed_names_stay_unknown():
    result = hook_shape.check(upstream())
    assert result["status"] == "COMPATIBLE"  # input shape was observed
    assert result["matchers"]["status"] == "UNKNOWN"


def test_unmatched_observed_tool_name_is_incompatible():
    result = hook_shape.check(upstream(), tool_names=["collaborationspawn_agent", "multi_agent_v1send_input"])
    assert result["status"] == "INCOMPATIBLE"
    assert result["matchers"]["post_tool_unmatched"] == ["multi_agent_v1send_input"]


@pytest.mark.parametrize("namespace,status", [
    ("collaboration", "UNKNOWN"), ("team", "INCOMPATIBLE"), ("my-team", "INCOMPATIBLE"), (None, "UNKNOWN"),
])
def test_configured_tool_namespace_predicts_only_incompatibility(namespace, status):
    assert hook_shape.namespace_check(namespace)["status"] == status


def _embedded_binary(tmp_path: Path, schemas: dict, *, newline: str = "\r\n", name: str = "codex.exe") -> Path:
    blob = bytearray(b"MZ\x90\x00 unrelated bytes \x00\xff")
    for title, schema in schemas.items():
        text = json.dumps(schema, indent=2, sort_keys=True).replace("\n", newline)
        blob += b"\x00\x13" + title.encode() + text.encode() + b"\x00garbage"
    path = tmp_path / name
    path.write_bytes(bytes(blob))
    return path


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_embedded_generated_schemas_are_read_from_the_binary(tmp_path, newline):
    binary = _embedded_binary(tmp_path, upstream(), newline=newline)
    found = hook_shape.embedded_schemas(str(binary))
    assert found == upstream()
    report = hook_shape.host_report(executable=str(binary), codex_home=tmp_path / "absent-home",
                                    observed_tool_names=UPSTREAM_V2_HOOK_NAMES)
    assert report["status"] == "COMPATIBLE" and report["evidence"] == "EMBEDDED_GENERATED_HOOK_SCHEMAS"
    assert report["runtime_refusal"] == "NEVER"


def test_binary_scan_fails_safe(tmp_path):
    assert hook_shape.embedded_schemas(None) is None
    assert hook_shape.embedded_schemas(str(tmp_path / "missing.exe")) is None
    launcher = _embedded_binary(tmp_path, upstream(), name="codex.cmd")
    assert hook_shape.embedded_schemas(str(launcher)) is None
    packed = tmp_path / "packed.exe"
    packed.write_bytes(b"MZ compressed payload without schemas")
    assert hook_shape.embedded_schemas(str(packed)) is None
    assert hook_shape.host_report(executable=str(packed))["status"] == "UNKNOWN"
    # Two different schemas under one title are contradictory: no observation.
    conflicting = deepcopy(upstream())
    other = deepcopy(conflicting["stop.command.input"])
    other["properties"].pop("cwd")
    path = _embedded_binary(tmp_path, conflicting, name="dup.exe")
    with path.open("ab") as stream:
        stream.write(b"stop.command.input" + json.dumps(other, indent=2).encode())
    assert hook_shape.embedded_schemas(str(path)) is None


def test_host_report_reads_a_custom_namespace_without_writing(tmp_path):
    home = tmp_path / "codex-home"
    home.mkdir()
    config = b'[features.multi_agent_v2]\nenabled = true\ntool_namespace = "team"\n'
    (home / "config.toml").write_bytes(config)
    binary = _embedded_binary(tmp_path, upstream())
    report = hook_shape.host_report(executable=str(binary), codex_home=home)
    assert report["status"] == "INCOMPATIBLE"
    assert report["tool_namespace"]["tool_namespace"] == "team"
    assert (home / "config.toml").read_bytes() == config


def test_missing_payload_keys_names_only_required_inputs():
    assert hook_shape.missing_payload_keys("PreToolUse", {
        "session_id": "s", "cwd": "c", "turn_id": "t", "tool_name": "Bash", "tool_input": {},
        "tool_use_id": "u"}) == []  # a root actor has no agent_id
    assert hook_shape.missing_payload_keys("SubagentStop", {"session_id": "s"}) == [
        "cwd", "turn_id", "agent_id", "agent_type", "last_assistant_message"]
    assert hook_shape.missing_payload_keys("PreToolUse", {"tool": "Bash"})[:3] == ["session_id", "cwd", "turn_id"]
    assert hook_shape.missing_payload_keys("Unregistered", {}) == []


def _project(tmp_path: Path) -> Path:
    from thaliris_codex import roles
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    agents = codex_adapter._codex_home() / "agents"
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = agents / name
        if not profile.exists():
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    codex_adapter.init(tmp_path)
    return tmp_path


def _runtime_gaps(root: Path) -> list:
    gaps = []
    for path in (root / ".context" / "audit").glob("*/runtime.json"):
        gaps += json.loads(path.read_text(encoding="utf-8")).get("host_hook_shape", [])
    return gaps


def test_live_payload_gap_is_a_bounded_diagnostic_not_a_new_decision(tmp_path, managed_role_profile_home):
    root = _project(tmp_path / "repo")
    payload = {"session_id": "session-a", "cwd": str(root)}
    decision = lifecycle.handle_hook(root, "SubagentStop", payload)
    assert decision == ""
    gaps = _runtime_gaps(root)
    assert gaps == [{"status": "UNKNOWN", "event": "SubagentStop",
                     "missing_keys": ["turn_id", "agent_id", "agent_type", "last_assistant_message"]}]
    # Repeats do not grow the record.
    lifecycle.handle_hook(root, "SubagentStop", payload)
    assert len(_runtime_gaps(root)) == 1
    # A complete payload records nothing.
    lifecycle.handle_hook(root, "Stop", {"session_id": "session-b", "cwd": str(root)})
    assert len(_runtime_gaps(root)) == 1
    report = codex_adapter.doctor(root)["host_hook_shape"]
    assert report["runtime_payload_gaps"] == gaps
    assert report["runtime_refusal"] == "NEVER"
    assert set(report["config_capability"]) == {"developer_instructions", "multi_agent_mode_hint_text"}


def test_pretool_gap_keeps_the_existing_decision(tmp_path, managed_role_profile_home, monkeypatch):
    root = _project(tmp_path / "repo")
    payload = {"session_id": "session-c", "cwd": str(root), "tool_name": "Bash",
               "tool_input": {"command": "git status"}}
    monkeypatch.setattr(lifecycle, "_record_hook_shape_gap", lambda *_args: None)
    without = lifecycle.handle_hook(root, "PreToolUse", dict(payload))
    monkeypatch.undo()
    with_diagnostic = lifecycle.handle_hook(root, "PreToolUse", dict(payload))
    assert with_diagnostic == without
    assert {"status": "UNKNOWN", "event": "PreToolUse", "missing_keys": ["turn_id", "tool_use_id|call_id|tool_call_id"]} in _runtime_gaps(root)
