"""Classify selected native wait evidence without guessing from a CLI version.

Callers supply the actual selected session's schema/observations. This module
does not load user assertions, subscribe to Desktop, or resume another thread.
Schema limits describe accepted arguments, not effective runtime duration.
"""
from __future__ import annotations

from typing import Any


RUNTIME_FACTS = (
    "bounded_duration", "completion_early_wake", "message_early_wake",
    "user_interruption", "automatic_resume",
)


def classify(schema: object = None, observations: object = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "UNKNOWN", "schema_status": "UNKNOWN",
        "explicit_timeout_supported": "UNKNOWN", "min": "UNKNOWN", "default": "UNKNOWN",
        "max": "UNKNOWN", "effective_max_wait_timeout_ms": "UNAVAILABLE",
        "native_completion_reenters_root": "UNKNOWN",
        "runtime": {name: {"status": "UNKNOWN"} for name in RUNTIME_FACTS}}
    # A runtime fact needs its own source; one wake reason never proves another.
    if isinstance(observations, dict):
        for name in RUNTIME_FACTS:
            fact = observations.get(name)
            if (isinstance(fact, dict) and isinstance(fact.get("status"), str)
                    and fact["status"] in {"PASS", "UNSUPPORTED"}
                    and isinstance(fact.get("source_ref"), str) and fact["source_ref"].strip()):
                result["runtime"][name] = {"status": fact["status"], "source_ref": fact["source_ref"]}
        result["native_completion_reenters_root"] = result["runtime"]["automatic_resume"]["status"]
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return result
    properties = schema.get("properties")
    timeout = properties.get("timeout_ms") if isinstance(properties, dict) else None
    if not isinstance(timeout, dict) or timeout.get("type") != "integer":
        return result
    low, high, default = (timeout.get(key) for key in ("minimum", "maximum", "default"))
    if (type(low) is not int or type(high) is not int or not 0 < low <= high
            or default is not None and (type(default) is not int or not low <= default <= high)):
        return result
    result.update({"status": "PASS", "schema_status": "PASS", "explicit_timeout_supported": True,
        "min": low, "max": high, "default": default if default is not None else "UNKNOWN"})
    return result
