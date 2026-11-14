"""Hook-shape compatibility: what the Host declares versus what the adapter reads.

Compatibility follows observed hook behaviour surfaces, never a version string.
Codex embeds its generated hook input JSON schemas (``include_str!`` of
``codex-rs/hooks/schema/generated``) in the CLI binary, so a read-only byte scan
of the resolved binary observes the exact Host declaration without running it.

The result is diagnostic and install-time evidence only. UNKNOWN never refuses
anything at runtime, and nothing is COMPATIBLE without an observed schema.
A live payload that lacks a key the adapter relies on keeps its existing
fail-closed handling; ``missing_payload_keys`` only names the gap.
"""
from __future__ import annotations

import hashlib
import json
import mmap
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

# Adapter event name -> generated schema title stem.
EVENT_SCHEMAS = {
    "SessionStart": "session-start",
    "UserPromptSubmit": "user-prompt-submit",
    "PreToolUse": "pre-tool-use",
    "PostToolUse": "post-tool-use",
    "SubagentStart": "subagent-start",
    "SubagentStop": "subagent-stop",
    "Stop": "stop",
}
_TOOL = ("tool_name", "tool")
_CALL = ("tool_use_id", "call_id", "tool_call_id")
_RESPONSE = ("tool_response", "tool_result", "result", "output")
# Keys the adapter interprets that every payload of the event must carry.
# Each entry lists accepted alternatives; any one of them satisfies it.
REQUIRED_INPUTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "SessionStart": (("session_id",), ("cwd",), ("source",)),
    "UserPromptSubmit": (("session_id",), ("cwd",), ("prompt",)),
    "PreToolUse": (("session_id",), ("cwd",), ("turn_id",), _TOOL, ("tool_input",), _CALL),
    "PostToolUse": (("session_id",), ("cwd",), ("turn_id",), _TOOL, ("tool_input",), _CALL, _RESPONSE),
    "SubagentStart": (("session_id",), ("cwd",), ("turn_id",), ("agent_id",), ("agent_type",)),
    "SubagentStop": (("session_id",), ("cwd",), ("turn_id",), ("agent_id",), ("agent_type",),
                     ("last_assistant_message",)),
    "Stop": (("session_id",), ("cwd",)),
}
# Keys the adapter reads when present: the Host must declare them, but a root
# actor's payload legitimately omits them, so they are not runtime gaps.
DECLARED_INPUTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "UserPromptSubmit": (("agent_id",), ("agent_type",)),
    "PreToolUse": (("agent_id",), ("agent_type",)),
    "PostToolUse": (("agent_id",), ("agent_type",)),
}
# Keys the Host schema declares nullable (``$ref: NullableString``): a present
# ``null`` is a valid observation, so only an absent key is a gap.
NULLABLE_INPUTS: dict[str, frozenset[str]] = {
    "SubagentStop": frozenset({"last_assistant_message"}),
}
DEFAULT_TOOL_NAMESPACE = "collaboration"
# MultiAgentV1 hook tool names (codex-rs/core/src/tools/handlers/multi_agents_spec.rs,
# rust-v0.169.0: the ``*_v1`` specs plus ``resume_agent``). V1 tools are not
# namespaced. ``features.multi_agent_v2`` is ``default_enabled: false`` there
# (codex-rs/features/src/lib.rs), so an absent setting selects V1.
V1_TOOL_NAMES = ("spawn_agent", "send_input", "resume_agent", "wait_agent", "close_agent")
_SCHEMA_NEEDLE = b'"$schema": "http://json-schema.org/draft-07/schema#"'
_MAX_SCHEMA_BYTES = 64 * 1024
_MAX_SCHEMAS = 1024


def _requirement(alternatives: tuple[str, ...]) -> str:
    return "|".join(alternatives)


def missing_payload_keys(event: str, payload: object) -> list[str]:
    """Name required adapter inputs absent from one live payload (bounded)."""
    if event not in REQUIRED_INPUTS or not isinstance(payload, dict):
        return []
    nullable = NULLABLE_INPUTS.get(event, frozenset())
    return [_requirement(alternatives) for alternatives in REQUIRED_INPUTS[event]
            if not any(key in payload if key in nullable else payload.get(key) is not None
                       for key in alternatives)][:16]


def _accept(found: dict[str, Any], conflicts: set[str], value: object) -> None:
    if not isinstance(value, dict):
        return
    title = value.get("title")
    if not isinstance(title, str) or not title.endswith(".command.input"):
        return
    if title in found and found[title] != value:
        conflicts.add(title)
    found[title] = value


def _scan(view: Any) -> dict[str, Any] | None:
    found: dict[str, Any] = {}
    conflicts: set[str] = set()
    decoder = json.JSONDecoder()
    position = 0
    scanned = 0
    while scanned < _MAX_SCHEMAS:
        index = view.find(_SCHEMA_NEEDLE, position)
        if index < 0:
            break
        position = index + 1
        scanned += 1
        start = view.rfind(b"{", max(0, index - 16), index)
        if start < 0:
            continue
        chunk = view[start:start + _MAX_SCHEMA_BYTES].decode("utf-8", "replace")
        try:
            value, _ = decoder.raw_decode(chunk)
        except ValueError:
            continue
        _accept(found, conflicts, value)
    if conflicts or not found:
        return None
    return found


def embedded_identity(executable: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Schemas and SHA-256 read from one mapping of the same bytes.

    The digest is returned only when those very bytes embed the Host's
    generated hook schemas, so a launcher shim (Scoop, Volta and similar)
    that merely starts the Host is never identified as the Host.
    """
    from .config_capability import LAUNCHER_SUFFIXES
    if not executable:
        return None, None
    path = Path(executable)
    if path.suffix.lower() in LAUNCHER_SUFFIXES:
        return None, None
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None, None
        with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as view:
            if view[:2] == b"#!":
                return None, None
            schemas = _scan(view)
            if schemas is None:
                return None, None
            return schemas, hashlib.sha256(view).hexdigest()
    except (OSError, ValueError):
        return None, None


def embedded_schemas(executable: str | None) -> dict[str, Any] | None:
    """Read the Host's generated hook input schemas from its binary, read-only.

    Returns None when no schema is observable (launcher script, packed or
    missing binary). Two different embedded schemas with one title are
    contradictory and also yield None.
    """
    return embedded_identity(executable)[0]


def directory_schemas(directory: Path) -> dict[str, Any] | None:
    """Load ``*.command.input.schema.json`` files, e.g. an upstream checkout."""
    found: dict[str, Any] = {}
    conflicts: set[str] = set()
    try:
        for path in sorted(Path(directory).glob("*.command.input.schema.json")):
            _accept(found, conflicts, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    if conflicts or not found:
        return None
    return found


def multi_agent_name(name: object) -> bool:
    """A raw Host tool name whose suffix is a multi-agent base name (any namespace form).

    MCP tools (``mcp__server__tool``) are server tools, not Host collaboration
    tools, even when their suffix happens to coincide.
    """
    from . import lifecycle
    return (isinstance(name, str) and 0 < len(name) <= 128 and not name.startswith("mcp__")
            and any(name.endswith(base) for base in lifecycle._COLLABORATION_TOOL_NAMES + V1_TOOL_NAMES))


def _multi_agent_names(names: Iterable[str] | None) -> list[str]:
    """Keep names that end in a known multi-agent tool name (any namespace form)."""
    return sorted({name for name in (names or ()) if multi_agent_name(name)})[:64]


def _matchers(tool_names: Iterable[str] | None) -> dict[str, Any]:
    """Check observed Host tool names against the registered matchers."""
    from . import lifecycle
    names = _multi_agent_names(tool_names)
    if not names:
        return {"status": "UNKNOWN", "reason": "no Host multi-agent tool names observed",
                "pre_tool_matcher": lifecycle.PRE_TOOL_MATCHER, "post_tool_unmatched": []}
    # PreToolUse uses the match-all matcher; PostToolUse is the only
    # completion observation and must select every multi-agent tool name.
    pre_ok = lifecycle.PRE_TOOL_MATCHER == "*"
    unmatched = [name for name in names if re.fullmatch(lifecycle.POST_TOOL_MATCHER, name) is None]
    return {"status": "COMPATIBLE" if pre_ok and not unmatched else "INCOMPATIBLE",
            "pre_tool_matcher": lifecycle.PRE_TOOL_MATCHER, "observed_tool_names": names,
            "post_tool_unmatched": unmatched}


def namespace_check(namespace: str | None, *, v2_enabled: bool | None = None,
                    observed_tool_names: Iterable[str] | None = ()) -> dict[str, Any]:
    """Predict, from Host config, names the PostToolUse matcher cannot select.

    Without MultiAgentV2 the Host uses the V1 tools, whose ``resume_agent`` the
    matcher does not select, so completion observation would be lost:
    INCOMPATIBLE. ``v2_enabled`` is True only for an explicit
    ``features.multi_agent_v2`` enable; None means it is not configured, which
    selects V1 on rust-v0.169.0 unless namespaced V2 tool names were actually
    observed. Codex serializes a namespaced V2 tool to hooks as ``namespace +
    name`` (``flat_tool_name``, rust-v0.169.0); earlier builds used
    ``namespace.name``. Any custom namespace is INCOMPATIBLE: the flattened
    form is never selected. This only ever reports INCOMPATIBLE or UNKNOWN; a
    prediction is not an observation of success.
    """
    from . import lifecycle
    v1_unmatched = [name for name in V1_TOOL_NAMES if re.fullmatch(lifecycle.POST_TOOL_MATCHER, name) is None]
    observed_v2 = any(lifecycle._tool_basename(name) != name for name in _multi_agent_names(observed_tool_names))
    if namespace is None:
        return {"status": "UNKNOWN", "tool_namespace": "UNKNOWN", "multi_agent_v2": "UNKNOWN",
                "reason": "Host config is unreadable"}
    v2 = "ENABLED" if v2_enabled is True else "DISABLED" if v2_enabled is False else "NOT_CONFIGURED"
    if v2_enabled is False or v2_enabled is None and not observed_v2:
        return {"status": "INCOMPATIBLE" if v1_unmatched else "UNKNOWN", "tool_namespace": namespace,
                "multi_agent_v2": v2,
                "reason": "multi_agent_v2 is not enabled, so the Host uses V1 tool names",
                "post_tool_unmatched": v1_unmatched}
    if namespace == DEFAULT_TOOL_NAMESPACE:
        return {"status": "UNKNOWN", "tool_namespace": namespace, "multi_agent_v2": v2,
                "reason": "default namespace"}
    unmatched = [form for name in lifecycle._COLLABORATION_TOOL_NAMES
                 for form in (namespace + name, namespace + "." + name)
                 if re.fullmatch(lifecycle.POST_TOOL_MATCHER, form) is None]
    return {"status": "INCOMPATIBLE", "tool_namespace": namespace, "multi_agent_v2": v2,
            "reason": "custom tool_namespace", "post_tool_unmatched": unmatched}


def check(schemas: Mapping[str, Any] | None, *, tool_names: Iterable[str] | None = None) -> dict[str, Any]:
    """Compare Host-declared hook inputs with the adapter's reliance.

    The schema check needs every registered event's schema and every
    relied-on key observed; a missing event, key or contradictory event
    constant is INCOMPATIBLE and unobservable schemas are UNKNOWN. The matcher
    check needs observed Host multi-agent tool names. The top-level status is
    COMPATIBLE only when both are COMPATIBLE, INCOMPATIBLE when either is,
    and otherwise UNKNOWN.
    """
    from . import lifecycle
    matchers = _matchers(tool_names)
    if not schemas:
        return {"status": "INCOMPATIBLE" if matchers["status"] == "INCOMPATIBLE" else "UNKNOWN",
                "schema_status": "UNKNOWN", "matcher_status": matchers["status"],
                "reason": "Host hook schemas are not observable",
                "events": list(lifecycle.HOOK_EVENTS), "matchers": matchers}
    missing_events: list[str] = []
    missing_keys: dict[str, list[str]] = {}
    contradictions: list[str] = []
    optional_in_host: dict[str, list[str]] = {}
    for event in lifecycle.HOOK_EVENTS:
        schema = schemas.get(EVENT_SCHEMAS[event] + ".command.input")
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict):
            missing_events.append(event)
            continue
        constant = properties.get("hook_event_name")
        if isinstance(constant, dict) and "const" in constant and constant["const"] != event:
            contradictions.append(event)
        required = set(schema.get("required") or ()) if isinstance(schema.get("required"), list) else set()
        for alternatives in REQUIRED_INPUTS[event] + DECLARED_INPUTS.get(event, ()):
            present = [key for key in alternatives if key in properties]
            if not present:
                missing_keys.setdefault(event, []).append(_requirement(alternatives))
            elif alternatives in REQUIRED_INPUTS[event] and not any(key in required for key in present):
                # Declared but optional: the runtime gap diagnostic covers it.
                optional_in_host.setdefault(event, []).append(_requirement(alternatives))
    schema_status = "INCOMPATIBLE" if missing_events or missing_keys or contradictions else "COMPATIBLE"
    statuses = {schema_status, matchers["status"]}
    result: dict[str, Any] = {
        "status": ("INCOMPATIBLE" if "INCOMPATIBLE" in statuses
                   else "COMPATIBLE" if statuses == {"COMPATIBLE"} else "UNKNOWN"),
        "schema_status": schema_status, "matcher_status": matchers["status"],
        "events": list(lifecycle.HOOK_EVENTS),
        "missing_events": missing_events, "missing_keys": missing_keys,
        "event_name_contradictions": contradictions,
        "declared_optional_required_keys": optional_in_host,
        "matchers": matchers,
    }
    return result


def _configured_multi_agent(codex_home: Path | None) -> tuple[str | None, bool | None]:
    """Read (never write) ``features.multi_agent_v2`` from user config.

    Returns the tool namespace (None when the config is unreadable) and the
    explicit V2 enable (True/False), or None when it is not configured.
    """
    import tomllib
    if codex_home is None:
        return None, None  # No Host home was observed: UNKNOWN, not "not configured".
    try:
        config = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_TOOL_NAMESPACE, None
    except (OSError, ValueError):
        return None, None
    features = config.get("features")
    table = features.get("multi_agent_v2") if isinstance(features, dict) else None
    enabled = table if type(table) is bool else table.get("enabled") if isinstance(table, dict) else None
    value = table.get("tool_namespace") if isinstance(table, dict) else None
    return (value if isinstance(value, str) and value else DEFAULT_TOOL_NAMESPACE,
            enabled if type(enabled) is bool else None)


def _configured_namespace(codex_home: Path | None) -> str | None:
    """Read (never write) features.multi_agent_v2.tool_namespace from user config."""
    return _configured_multi_agent(codex_home)[0]


def host_report(*, executable: str | None = None, codex_home: Path | None = None,
                observed_tool_names: Iterable[str] = ()) -> dict[str, Any]:
    """Diagnose the resolved Host binary. Read-only; never runs the binary."""
    from .config_capability import resolve_executable
    selected = executable or resolve_executable()
    schemas, digest = embedded_identity(selected)
    result = check(schemas, tool_names=observed_tool_names)
    configured, v2_enabled = _configured_multi_agent(codex_home)
    namespace = namespace_check(configured, v2_enabled=v2_enabled, observed_tool_names=observed_tool_names)
    result["tool_namespace"] = namespace
    if namespace["status"] == "INCOMPATIBLE":
        result["status"] = "INCOMPATIBLE"
    result["evidence"] = "EMBEDDED_GENERATED_HOOK_SCHEMAS" if schemas else "UNAVAILABLE"
    result["executable"] = selected or "UNKNOWN"
    result["executable_sha256"] = digest or "UNKNOWN"
    result["runtime_refusal"] = "NEVER"
    return result
