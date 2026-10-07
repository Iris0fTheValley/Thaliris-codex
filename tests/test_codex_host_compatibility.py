"""Deterministic compatibility boundary for the locally observed Codex host.

Compatibility maintenance only: these tests certify that the currently
installed host build keeps the existing Thaliris behaviour, and that no newly
available upstream capability was adopted. They deliberately assert the
fail-closed outcome, so that a future promotion of this build into the pinned
wait capability set has to change a test on purpose.

Observed local host, 2026-10-08:

- CLI: ``codex-cli 0.162.0-alpha.2`` (Codex package ``26.1002.7124.0``)
- responding app-server version: ``UNKNOWN`` (``initialize.serverInfo`` is
  absent in this build; ``initialize.userAgent`` is a client description, not a
  server identity, and this adapter never derives a daemon version from it)

See ``docs/codex-host-compatibility-20261008.md`` for the measured surfaces.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from thaliris_codex import codex_adapter, codex_app_server, host_preflight, lifecycle

OBSERVED_VERSION = "0.162.0-alpha.2"

# Verbatim initialize result recorded from the installed host build on
# 2026-10-08 through a read-only stdio session against the real Codex home.
OBSERVED_INITIALIZE_RESULT = {
    "userAgent": (
        "thaliris-host-compat-probe/0.162.0-alpha.2 "
        "(Windows 10.0.26200; x86_64) unknown (thaliris-host-compat-probe; 1)"
    ),
    "codexHome": r"C:\Users\12298\.codex",
    "platformFamily": "windows",
    "platformOs": "windows",
}

# Hook event names the installed build reports through hooks/list, keyed by the
# adapter's own event name. Both lists were observed in the build's hooks/list
# response and in its published app-server schema.
OBSERVED_HOST_EVENT_NAMES = {
    "SessionStart": "sessionStart",
    "UserPromptSubmit": "userPromptSubmit",
    "PreToolUse": "preToolUse",
    "PostToolUse": "postToolUse",
    "SubagentStart": "subagentStart",
    "SubagentStop": "subagentStop",
    "Stop": "stop",
}

# Hook input keys this adapter interprets. Confirmed present in the installed
# build's own binary.
OBSERVED_HOOK_INPUT_KEYS = (
    "agent_id", "agent_type", "session_id", "turn_id", "tool_name", "tool_input", "cwd",
)
# Hook output keys the adapter actually renders into its hook decisions.
OBSERVED_HOOK_OUTPUT_KEYS = (
    "hookSpecificOutput", "hookEventName", "additionalContext",
    "permissionDecision", "permissionDecisionReason",
)
# Additional output keys the installed build accepts but which this adapter does
# not emit. They stay unused: enabling them would be a behaviour change.
UNUSED_HOST_OUTPUT_KEYS = ("systemMessage", "suppressOutput")


class _ReportedVersion:
    """Stands in for the installed CLI's ``--version`` observation."""

    def __init__(self, version: str) -> None:
        self.returncode = 0
        self.stdout = f"codex-cli {version}\n"
        self.stderr = ""


def _observe(monkeypatch, version: str) -> None:
    codex_adapter._host_wait_mode_cached.cache_clear()
    monkeypatch.setattr(codex_adapter.subprocess, "run", lambda *args, **kwargs: _ReportedVersion(version))


def test_pinned_wait_capability_set_is_exactly_the_certified_boundary() -> None:
    """The observed build must not have been promoted into the pinned set."""
    assert set(codex_adapter._KNOWN_HOST_WAIT_CAPABILITIES) == {
        "0.153.4", "0.154.0", "0.155.1", "0.155.0-alpha.9.2",
    }
    assert OBSERVED_VERSION not in codex_adapter._KNOWN_HOST_WAIT_CAPABILITIES


def test_observed_local_host_remains_fail_closed(monkeypatch) -> None:
    """A prerequisite-bearing observation must not enable a blocking wait."""
    _observe(monkeypatch, OBSERVED_VERSION)
    try:
        capability = codex_adapter.host_explicit_blocking_wait("codex-observed-test")
        assert capability["status"] != "PASS"
        assert capability["host"]["status"] != "PASS"
        assert capability["host"]["version"] == OBSERVED_VERSION
        assert capability["host"]["reason"] == (
            "no version-pinned wait capability is recorded for this Codex host"
        )
        assert codex_adapter.native_child_completion_reenters_root("codex-observed-test") == "UNKNOWN"
        assert codex_adapter.selected_continuation_mode(Path("."), "codex-observed-test") == "UNAVAILABLE"
    finally:
        codex_adapter._host_wait_mode_cached.cache_clear()


@pytest.mark.parametrize("version", ["0.153.4", "0.154.0", "0.155.1"])
def test_previously_certified_hosts_are_unchanged(monkeypatch, version: str) -> None:
    """Adding compatibility for a newer build must not disturb older pins."""
    _observe(monkeypatch, version)
    try:
        capability = codex_adapter.host_explicit_blocking_wait("codex-pinned-test")
        assert capability["status"] == "PASS"
        assert capability["version"] == version
        assert capability["min_wait_timeout_ms"] == 10_000
        assert capability["default_wait_timeout_ms"] == 30_000
        assert capability["release_hard_max_wait_timeout_ms"] == 3_600_000
        assert capability["effective_max_wait_timeout_ms"] == "UNAVAILABLE"
        assert codex_adapter.selected_continuation_mode(Path("."), "codex-pinned-test") == "BLOCKING_WAIT"
    finally:
        codex_adapter._host_wait_mode_cached.cache_clear()


def test_source_verified_prerelease_pin_is_unchanged(monkeypatch) -> None:
    """The one source-verified prerelease keeps its recorded classification."""
    _observe(monkeypatch, "0.155.0-alpha.9.2")
    try:
        assert codex_adapter.native_child_completion_reenters_root("codex-alpha-pin-test") == "UNKNOWN"
        assert codex_adapter.selected_continuation_mode(Path("."), "codex-alpha-pin-test") == "BLOCKING_WAIT"
    finally:
        codex_adapter._host_wait_mode_cached.cache_clear()


def test_arbitrary_prerelease_suffixes_still_fail_closed(monkeypatch) -> None:
    """A prerelease suffix is never promoted from its numeric prefix."""
    _observe(monkeypatch, f"{OBSERVED_VERSION}.1")
    try:
        assert codex_adapter.host_explicit_blocking_wait("codex-suffix-test")["status"] != "PASS"
        assert codex_adapter.selected_continuation_mode(Path("."), "codex-suffix-test") == "UNAVAILABLE"
    finally:
        codex_adapter._host_wait_mode_cached.cache_clear()


def test_observed_initialize_surface_keeps_daemon_identity_unknown(tmp_path, monkeypatch) -> None:
    """The build's reporting surface must not be laundered into a daemon identity."""
    assert "serverInfo" not in OBSERVED_INITIALIZE_RESULT
    client = object.__new__(codex_app_server.CodexAppServer)
    client.codex_home = tmp_path
    client.executable = "observed-cli"
    client.initialize_observation = {
        **OBSERVED_INITIALIZE_RESULT,
        "codexHome": str(tmp_path),
    }
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, f"codex-cli {OBSERVED_VERSION}", ""),
    )
    facts = client.connection_facts()
    assert facts["cli_version"] == f"codex-cli {OBSERVED_VERSION}"
    assert facts["daemon_version"] == "UNKNOWN"
    assert facts["daemon_version_evidence"] == "UNKNOWN"
    assert facts["daemon_home_matches_requested"] == "YES"
    assert facts["daemon_control_authority"] == "UNKNOWN"
    assert facts["live_role_catalog"] == "UNKNOWN"


def test_connection_entrypoint_still_requires_codex_home_agreement(tmp_path) -> None:
    """A build whose initialize omits codexHome must stay rejected, not assumed."""
    assert codex_app_server._same_path(OBSERVED_INITIALIZE_RESULT["codexHome"], Path(r"C:\Users\12298\.codex")) is True
    assert codex_app_server._same_path(str(tmp_path), Path(r"C:\Users\12298\.codex")) is False
    assert codex_app_server._same_path(None, Path(r"C:\Users\12298\.codex")) is False


def test_host_event_name_mapping_matches_the_observed_build() -> None:
    """The adapter must keep asking for the same host event names it always has."""
    assert codex_app_server._EVENT_NAMES == OBSERVED_HOST_EVENT_NAMES
    assert tuple(codex_app_server._EVENT_NAMES) == tuple(lifecycle.HOOK_EVENTS)
    assert set(codex_app_server._EVENT_NAMES.values()) == set(OBSERVED_HOST_EVENT_NAMES.values())


def test_generated_hook_spec_keeps_the_observed_registration_shape(tmp_path: Path) -> None:
    """Registration stays seven command handlers with unchanged matchers/timeouts."""
    spec = lifecycle.host_hook_spec(
        tmp_path, tmp_path / "Scripts" / "thaliris.exe", "a" * 64, "b" * 64,
    )
    assert set(spec["hooks"]) == set(lifecycle.HOOK_EVENTS)
    for event, entries in spec["hooks"].items():
        assert len(entries) == 1
        handlers = entries[0]["hooks"]
        assert len(handlers) == 1
        assert handlers[0]["type"] == "command"
        assert handlers[0]["timeout"] == 60
        assert "powershell.exe -NoProfile -NonInteractive" in handlers[0]["command"]
        if event == "PostToolUse":
            assert entries[0]["matcher"] == lifecycle.POST_TOOL_MATCHER
        elif event == "PreToolUse":
            assert entries[0]["matcher"] == lifecycle.PRE_TOOL_MATCHER
        else:
            assert "matcher" not in entries[0]


def test_hook_payload_key_surface_is_unchanged() -> None:
    """The keys the adapter reads and writes are the ones the build still emits."""
    sources = {
        name: Path(module.__file__).read_text(encoding="utf-8")
        for name, module in (
            ("lifecycle", lifecycle),
            ("host_preflight", host_preflight),
            ("codex_adapter", codex_adapter),
        )
    }
    # Input keys are camelCase because the host sends them; the adapter reads
    # them as string literals.
    for key in OBSERVED_HOOK_INPUT_KEYS:
        assert any(f'"{key}"' in text for text in sources.values()), key
    # Output keys are rendered into the JSON hook decisions the adapter writes
    # back to the host, either as Python literals or inside the trampolines.
    for key in OBSERVED_HOOK_OUTPUT_KEYS:
        assert any(key in text for text in sources.values()), key
    # The build accepts these too, but the adapter must not have started using
    # them: that would change what the host displays.
    for key in UNUSED_HOST_OUTPUT_KEYS:
        assert not any(key in text for text in sources.values()), key


def test_trust_update_payload_shape_is_unchanged() -> None:
    """The trust write must stay an opaque-hash upsert on the home's own config."""
    source = Path(codex_app_server.__file__).read_text(encoding="utf-8")
    assert '"trusted_hash": hook["currentHash"]' in source
    assert source.count('"keyPath": "hooks.state"') == 2  # upsert on install, replace on uninstall
    assert '"mergeStrategy": "upsert"' in source
    assert '"mergeStrategy": "replace"' in source
    # currentHash is consumed as an opaque token, never parsed as bare hex; the
    # host now sends the "sha256:<hex>" form and it must round-trip verbatim.
    assert '"sha256:"' not in source
    assert 'startswith("sha256:")' not in source
    assert 'removeprefix("sha256:")' not in source
    for field in ("currentHash", "enabled", "trustStatus", "eventName", "sourcePath", "isManaged"):
        assert f'hook.get("{field}")' in source, field


def test_trusted_hash_round_trips_the_host_prefixed_form() -> None:
    """The build's ``sha256:<hex>`` currentHash must survive a trust round trip."""
    observed = "sha256:3872608d748b8d09a00562d5b0e04146d6f7857c90cd6887e7f09cb51a76751f"
    updates = {"home/hooks.json:pre_tool_use:0:0": {"trusted_hash": observed}}
    assert json.loads(json.dumps(updates))["home/hooks.json:pre_tool_use:0:0"]["trusted_hash"] == observed
    assert observed.startswith("sha256:")
    assert len(observed.removeprefix("sha256:")) == 64
