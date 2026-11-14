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
DEFAULT_TOOL_NAMESPACE = "collaboration"
_SCHEMA_NEEDLE = b'"$schema": "http://json-schema.org/draft-07/schema#"'
_MAX_SCHEMA_BYTES = 64 * 1024
_MAX_SCHEMAS = 1024


def _requirement(alternatives: tuple[str, ...]) -> str:
    return "|".join(alternatives)


def missing_payload_keys(event: str, payload: object) -> list[str]:
    """Name required adapter inputs absent from one live payload (bounded)."""
    if event not in REQUIRED_INPUTS or not isinstance(payload, dict):
        return []
    return [_requirement(alternatives) for alternatives in REQUIRED_INPUTS[event]
            if not any(payload.get(key) is not None for key in alternatives)][:16]


def _accept(found: dict[str, Any], conflicts: set[str], value: object) -> None:
    if not isinstance(value, dict):
        return
    title = value.get("title")
    if not isinstance(title, str) or not title.endswith(".command.input"):
        return
    if title in found and found[title] != value:
        conflicts.add(title)
    found[title] = value


def embedded_schemas(executable: str | None) -> dict[str, Any] | None:
    """Read the Host's generated hook input schemas from its binary, read-only.

    Returns None when no schema is observable (launcher script, packed or
    missing binary). Two different embedded schemas with one title are
    contradictory and also yield None.
    """
    from .config_capability import LAUNCHER_SUFFIXES
    if not executable:
        return None
    path = Path(executable)
    if path.suffix.lower() in LAUNCHER_SUFFIXES:
        return None
    found: dict[str, Any] = {}
    conflicts: set[str] = set()
    decoder = json.JSONDecoder()
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as view:
            if view[:2] == b"#!":
                return None
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
    except (OSError, ValueError):
        return None
    if conflicts or not found:
        return None
    return found


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


def _multi_agent_names(names: Iterable[str] | None) -> list[str]:
    """Keep names that end in a known multi-agent tool name (any namespace form)."""
    from . import lifecycle
    return sorted({name for name in (names or ()) if isinstance(name, str) and 0 < len(name) <= 128
                   and any(name.endswith(base) for base in lifecycle._COLLABORATION_TOOL_NAMES)})[:64]


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


def namespace_check(namespace: str | None) -> dict[str, Any]:
    """Predict, from Host config, names the PostToolUse matcher cannot select.

    Codex serializes a namespaced MultiAgentV2 tool to hooks as
    ``namespace + name`` (``flat_tool_name``, rust-v0.169.0); earlier builds
    used ``namespace.name``. Which form a build uses is not observed here, so
    any form the matcher misses for a configured namespace is reported: on
    such a build completion observation would be lost. This only ever reports
    INCOMPATIBLE or UNKNOWN; a prediction is not an observation of success.
    """
    from . import lifecycle
    if namespace is None:
        return {"status": "UNKNOWN", "tool_namespace": "UNKNOWN"}
    if namespace == DEFAULT_TOOL_NAMESPACE:
        return {"status": "UNKNOWN", "tool_namespace": namespace, "reason": "default namespace"}
    unmatched = [form for name in lifecycle._COLLABORATION_TOOL_NAMES
                 for form in (namespace + name, namespace + "." + name)
                 if re.fullmatch(lifecycle.POST_TOOL_MATCHER, form) is None]
    return {"status": "INCOMPATIBLE" if unmatched else "UNKNOWN", "tool_namespace": namespace,
            "post_tool_unmatched": unmatched}


def check(schemas: Mapping[str, Any] | None, *, tool_names: Iterable[str] | None = None) -> dict[str, Any]:
    """Compare Host-declared hook inputs with the adapter's reliance.

    COMPATIBLE needs every registered event's schema and every relied-on key
    observed. A missing event, key or contradictory event constant is
    INCOMPATIBLE. Without schemas the result is UNKNOWN, never COMPATIBLE.
    """
    from . import lifecycle
    matchers = _matchers(tool_names)
    if not schemas:
        return {"status": "UNKNOWN", "reason": "Host hook schemas are not observable",
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
    incompatible = bool(missing_events or missing_keys or contradictions)
    result: dict[str, Any] = {
        "status": "INCOMPATIBLE" if incompatible or matchers["status"] == "INCOMPATIBLE" else "COMPATIBLE",
        "events": list(lifecycle.HOOK_EVENTS),
        "missing_events": missing_events, "missing_keys": missing_keys,
        "event_name_contradictions": contradictions,
        "declared_optional_required_keys": optional_in_host,
        "matchers": matchers,
    }
    return result


def _configured_namespace(codex_home: Path | None) -> str | None:
    """Read (never write) features.multi_agent_v2.tool_namespace from user config."""
    import tomllib
    if codex_home is None:
        return DEFAULT_TOOL_NAMESPACE
    try:
        config = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_TOOL_NAMESPACE
    except (OSError, ValueError):
        return None
    features = config.get("features")
    table = features.get("multi_agent_v2") if isinstance(features, dict) else None
    value = table.get("tool_namespace") if isinstance(table, dict) else None
    return value if isinstance(value, str) and value else DEFAULT_TOOL_NAMESPACE


def host_report(*, executable: str | None = None, codex_home: Path | None = None,
                observed_tool_names: Iterable[str] = ()) -> dict[str, Any]:
    """Diagnose the resolved Host binary. Read-only; never runs the binary."""
    from .config_capability import resolve_executable
    selected = executable or resolve_executable()
    schemas = embedded_schemas(selected)
    result = check(schemas, tool_names=observed_tool_names)
    namespace = namespace_check(_configured_namespace(codex_home))
    result["tool_namespace"] = namespace
    if namespace["status"] == "INCOMPATIBLE":
        result["status"] = "INCOMPATIBLE"
    result["evidence"] = "EMBEDDED_GENERATED_HOOK_SCHEMAS" if schemas else "UNAVAILABLE"
    result["executable"] = selected or "UNKNOWN"
    result["runtime_refusal"] = "NEVER"
    return result
