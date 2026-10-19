from copy import deepcopy

import pytest

from thaliris_codex import codex_adapter, native_wait_capability


SCHEMA = {"type": "object", "properties": {"timeout_ms": {
    "type": "integer", "minimum": 10000, "maximum": 3600000}}}


def test_schema_ceiling_does_not_certify_duration_wake_interruption_or_resume():
    result = native_wait_capability.classify(SCHEMA)
    assert result["status"] == result["schema_status"] == "PASS"
    assert result["max"] == 3600000
    assert result["default"] == "UNKNOWN"
    assert result["effective_max_wait_timeout_ms"] == "UNAVAILABLE"
    assert all(fact["status"] == "UNKNOWN" for fact in result["runtime"].values())


@pytest.mark.parametrize("change", [{"type": "number"}, {"minimum": True}, {"maximum": "3600000"},
    {"minimum": -1}, {"maximum": 1}, {"default": 1}, {"default": True}])
def test_unproven_or_malformed_schema_keeps_capability_unknown(change):
    schema = deepcopy(SCHEMA)
    schema["properties"]["timeout_ms"].update(change)
    assert native_wait_capability.classify(schema)["status"] == "UNKNOWN"


def test_one_message_wake_cannot_certify_other_runtime_properties():
    result = native_wait_capability.classify(SCHEMA, {
        "message_early_wake": {"status": "PASS", "source_ref": "selected-wait-call"},
        "automatic_resume": {"status": "PASS"},
        "completion_early_wake": True,
        "bounded_duration": {"status": []},
    })
    assert result["runtime"]["message_early_wake"]["status"] == "PASS"
    assert result["runtime"]["completion_early_wake"]["status"] == "UNKNOWN"
    assert result["native_completion_reenters_root"] == "UNKNOWN"


def test_runtime_resume_requires_its_own_observation_and_not_a_schema():
    result = native_wait_capability.classify(observations={
        "automatic_resume": {"status": "PASS", "source_ref": "exact-child-completion-ingress"}})
    assert result["schema_status"] == "UNKNOWN"
    assert result["native_completion_reenters_root"] == "PASS"


def test_active_schema_works_without_a_known_cli_version(monkeypatch):
    monkeypatch.setattr(codex_adapter, "_host_wait_mode_cached", lambda _runner: {"version": "UNKNOWN"})
    result = codex_adapter.host_wait_mode(wait_schema=SCHEMA)
    assert result["status"] == "PASS" and result["max"] == 3600000
    assert result["version"] == "UNKNOWN"
    blocking = codex_adapter.host_explicit_blocking_wait(wait_schema=SCHEMA)
    assert blocking["schema_max_wait_timeout_ms"] == 3600000
    assert blocking["release_hard_max_wait_timeout_ms"] == "UNAVAILABLE"
    assert codex_adapter.selected_continuation_mode(None, wait_schema=SCHEMA) == "BLOCKING_WAIT"


def test_selected_automatic_resume_is_independent_from_schema_support(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_adapter, "_host_wait_mode_cached", lambda _runner: {"version": "UNKNOWN"})
    observations = {"automatic_resume": {"status": "PASS", "source_ref": "actual-selected-completion"}}
    assert codex_adapter.selected_continuation_mode(tmp_path, runtime_observations=observations) == "EVENT_DRIVEN"


def test_unknown_wait_optimization_degrades_without_revoking_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_adapter, "host_wait_mode", lambda *_args: {"status": "UNKNOWN", "version": "UNKNOWN"})
    assert codex_adapter.host_explicit_blocking_wait()["status"] == "UNKNOWN"
    assert codex_adapter.selected_continuation_mode(tmp_path) == "STAGED_WAIT"
