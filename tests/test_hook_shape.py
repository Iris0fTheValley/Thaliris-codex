"""Hook-shape compatibility against the Host's own generated hook schemas.

The rust-v0.169.0 fixtures are upstream source JSON (see PROVENANCE.json).
They are evidence for the checker, not a version requirement.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
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
    assert result["schema_status"] == "COMPATIBLE" and result["matcher_status"] == "COMPATIBLE"
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


def test_matchers_without_observed_names_keep_the_top_level_unknown():
    # c-F1: an observed schema alone is not compatibility; the matcher is unobserved.
    result = hook_shape.check(upstream())
    assert result["schema_status"] == "COMPATIBLE"
    assert result["matcher_status"] == "UNKNOWN" and result["matchers"]["status"] == "UNKNOWN"
    assert result["status"] == "UNKNOWN"


def test_unmatched_observed_tool_name_is_incompatible():
    result = hook_shape.check(upstream(), tool_names=["collaborationspawn_agent", "multi_agent_v1send_input"])
    assert result["status"] == "INCOMPATIBLE"
    assert result["schema_status"] == "COMPATIBLE" and result["matcher_status"] == "INCOMPATIBLE"
    assert result["matchers"]["post_tool_unmatched"] == ["multi_agent_v1send_input"]
    # Without schemas a matcher mismatch is still reported.
    assert hook_shape.check(None, tool_names=["teamspawn_agent"])["status"] == "INCOMPATIBLE"


def test_observed_v1_and_mcp_names():
    result = hook_shape.check(upstream(), tool_names=["spawn_agent", "resume_agent", "mcp__srv__send_message"])
    assert result["matchers"]["observed_tool_names"] == ["resume_agent", "spawn_agent"]
    assert result["matchers"]["post_tool_unmatched"] == ["resume_agent"]
    assert result["status"] == "INCOMPATIBLE"


@pytest.mark.parametrize("namespace,v2,observed,status", [
    ("collaboration", True, (), "UNKNOWN"),
    ("team", True, (), "INCOMPATIBLE"),
    ("my-team", True, (), "INCOMPATIBLE"),
    (None, True, (), "UNKNOWN"),
    # V2 disabled, or not configured (default off on rust-v0.169.0): V1 names are unmatched.
    ("collaboration", False, (), "INCOMPATIBLE"),
    ("collaboration", False, ("collaborationspawn_agent",), "INCOMPATIBLE"),
    ("collaboration", None, (), "INCOMPATIBLE"),
    # Not configured, but namespaced V2 names were actually observed.
    ("collaboration", None, ("collaborationspawn_agent",), "UNKNOWN"),
    ("collaboration", None, ("spawn_agent",), "INCOMPATIBLE"),
])
def test_configured_tool_namespace_predicts_only_incompatibility(namespace, v2, observed, status):
    result = hook_shape.namespace_check(namespace, v2_enabled=v2, observed_tool_names=observed)
    assert result["status"] == status
    if status == "INCOMPATIBLE" and v2 is not True:
        assert result["post_tool_unmatched"] == ["resume_agent"]


@pytest.mark.parametrize("config,expected", [
    (None, ("collaboration", None)),
    (b"[features]\nmulti_agent_v2 = true\n", ("collaboration", True)),
    (b"[features]\nmulti_agent_v2 = false\n", ("collaboration", False)),
    (b'[features.multi_agent_v2]\nenabled = true\ntool_namespace = "team"\n', ("team", True)),
    (b"[features.multi_agent_v2]\nmulti_agent_mode_hint_text = \"\"\n", ("collaboration", None)),
    (b"not toml = = \n", (None, None)),
])
def test_configured_multi_agent_reads_v1_and_v2_settings(tmp_path, config, expected):
    if config is not None:
        (tmp_path / "config.toml").write_bytes(config)
    assert hook_shape._configured_multi_agent(tmp_path) == expected


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
    assert report["executable_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    # c-F1: the install path passes no observed names, so the matcher stays UNKNOWN.
    install = hook_shape.host_report(executable=str(binary), codex_home=tmp_path / "absent-home")
    assert install["schema_status"] == "COMPATIBLE" and install["matcher_status"] == "UNKNOWN"
    assert install["status"] == "INCOMPATIBLE"  # V2 not configured: V1 resume_agent is unmatched
    enabled = tmp_path / "v2-home"
    enabled.mkdir()
    (enabled / "config.toml").write_bytes(b"[features.multi_agent_v2]\nenabled = true\n")
    assert hook_shape.host_report(executable=str(binary), codex_home=enabled)["status"] == "UNKNOWN"


def test_identity_is_bound_to_the_same_bytes_as_the_schemas(tmp_path):
    binary = _embedded_binary(tmp_path, upstream())
    schemas, digest = hook_shape.embedded_identity(str(binary))
    assert schemas == upstream() and digest == hashlib.sha256(binary.read_bytes()).hexdigest()
    shim = tmp_path / "shim.exe"
    shim.write_bytes(b"MZ launcher shim without schemas")
    assert hook_shape.embedded_identity(str(shim)) == (None, None)


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
    # c-F6: the Host declares last_assistant_message nullable; a present null is not a gap.
    stop = {"session_id": "s", "cwd": "c", "turn_id": "t", "agent_id": "a", "agent_type": "x",
            "last_assistant_message": None}
    assert hook_shape.missing_payload_keys("SubagentStop", stop) == []
    assert hook_shape.missing_payload_keys("SubagentStop", {**stop, "agent_id": None}) == ["agent_id"]
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


@pytest.fixture
def fixture_host(tmp_path, monkeypatch) -> Path:
    """A fixture Host binary; tests never hash the real PATH binary."""
    directory = tmp_path / "host-bin"
    directory.mkdir()
    binary = _embedded_binary(directory, upstream())
    monkeypatch.setenv("THALIRIS_CODEX_EXECUTABLE", str(binary))
    return binary


def test_live_payload_gap_is_a_bounded_diagnostic_not_a_new_decision(tmp_path, managed_role_profile_home, fixture_host):
    root = _project(tmp_path / "repo")
    payload = {"session_id": "session-a", "cwd": str(root)}
    decision = lifecycle.handle_hook(root, "SubagentStop", payload)
    assert decision == ""
    gaps = _runtime_gaps(root)
    stamp = hashlib.sha256(fixture_host.read_bytes()).hexdigest()
    assert gaps == [{"status": "UNKNOWN", "event": "SubagentStop", "host_binary_sha256": stamp,
                     "missing_keys": ["turn_id", "agent_id", "agent_type", "last_assistant_message"]}]
    # Repeats do not grow the record.
    lifecycle.handle_hook(root, "SubagentStop", payload)
    assert len(_runtime_gaps(root)) == 1
    # A complete payload records nothing.
    lifecycle.handle_hook(root, "Stop", {"session_id": "session-b", "cwd": str(root)})
    assert len(_runtime_gaps(root)) == 1
    report = codex_adapter.doctor(root)["host_hook_shape"]
    assert report["runtime_payload_gaps"] == gaps
    assert report["runtime_payload_gaps_not_current"] == 0
    assert report["executable"] == str(fixture_host)
    assert report["runtime_refusal"] == "NEVER"
    assert set(report["config_capability"]) == {"developer_instructions", "multi_agent_mode_hint_text"}
    # A replaced Host binary makes the old gap not current: doctor no longer shows it.
    fixture_host.write_bytes(fixture_host.read_bytes() + b"\x00replaced")
    report = codex_adapter.doctor(root)["host_hook_shape"]
    assert report["runtime_payload_gaps"] == [] and report["runtime_payload_gaps_not_current"] == 1


def test_gap_is_deduplicated_before_the_lock_and_skipped_for_fenced_actors(
        tmp_path, managed_role_profile_home, fixture_host, monkeypatch):
    root = _project(tmp_path / "repo")
    payload = {"session_id": "session-d", "cwd": str(root)}
    lifecycle.handle_hook(root, "SubagentStop", payload)
    assert len(_runtime_gaps(root)) == 1
    real_lock = lifecycle.task_authority._lock
    taken = []

    def counting(root_):
        taken.append(root_)
        return real_lock(root_)
    with monkeypatch.context() as patched:
        patched.setattr(lifecycle.task_authority, "_lock", counting)
        patched.setattr(lifecycle, "_host_binary_stamp", lambda: pytest.fail("a duplicate must not hash the binary"))
        lifecycle._record_hook_shape_gap(root, "SubagentStop", payload)
    assert taken == []
    # A fenced actor's payload is refused before any diagnostic is recorded.
    lifecycle.handle_hook(root, "PreToolUse", {"session_id": "session-e", "cwd": str(root), "fenced": True,
                                               "tool_name": "Bash", "tool_input": {"command": "git status"}})
    assert all(gap["event"] != "PreToolUse" for gap in _runtime_gaps(root))


def test_pretool_records_raw_collaboration_names_the_matcher_would_miss(
        tmp_path, managed_role_profile_home, fixture_host):
    root = _project(tmp_path / "repo")
    base = {"session_id": "session-f", "cwd": str(root), "turn_id": "t", "tool_use_id": "u", "tool_input": {}}
    for name in ("teamspawn_agent", "resume_agent", "mcp__srv__send_message", "Bash", "teamspawn_agent"):
        lifecycle.handle_hook(root, "PreToolUse", {**base, "tool_name": name})
    names = []
    for path in (root / ".context" / "audit").glob("*/runtime.json"):
        names += json.loads(path.read_text(encoding="utf-8")).get("collaboration_tool_names_observed", [])
    assert names == ["teamspawn_agent", "resume_agent"]
    report = codex_adapter.doctor(root)["host_hook_shape"]
    assert report["matcher_status"] == "INCOMPATIBLE"
    assert sorted(report["matchers"]["post_tool_unmatched"]) == ["resume_agent", "teamspawn_agent"]
    assert report["status"] == "INCOMPATIBLE"


def test_pretool_gap_keeps_the_existing_decision(tmp_path, managed_role_profile_home, monkeypatch, fixture_host):
    root = _project(tmp_path / "repo")
    payload = {"session_id": "session-c", "cwd": str(root), "tool_name": "Bash",
               "tool_input": {"command": "git status"}}
    with monkeypatch.context() as patched:  # keep the fixture Host selected afterwards
        patched.setattr(lifecycle, "_record_hook_shape_gap", lambda *_args: None)
        without = lifecycle.handle_hook(root, "PreToolUse", dict(payload))
    with_diagnostic = lifecycle.handle_hook(root, "PreToolUse", dict(payload))
    assert with_diagnostic == without
    assert {"status": "UNKNOWN", "event": "PreToolUse", "missing_keys": ["turn_id", "tool_use_id|call_id|tool_call_id"],
            "host_binary_sha256": hashlib.sha256(fixture_host.read_bytes()).hexdigest()} in _runtime_gaps(root)
