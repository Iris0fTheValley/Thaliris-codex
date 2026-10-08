"""The hook document's UTF-8 signature never changes its JSON object."""
from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

import pytest

from thaliris_codex import cli, codex_adapter, lifecycle, host_maintenance, diagnostics


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("signature", [b"", b"\xef\xbb\xbf"])
def test_hook_utf8_document_preserves_exact_payload(tmp_path, monkeypatch, replay, signature):
    payload = {"hook_event_name": "PreToolUse", "session_id": "session-雪",
               "tool_input": {"cmd": "literal \ufeff value", "metadata": ["🪷", None, 4]},
               "\ufefffield": "\ufeffleading and trailing\ufeff"}
    raw = signature + json.dumps(payload, ensure_ascii=False).encode("utf-8")
    received = []
    def guard(root, value, *_args):
        received.append(value)
        return ""
    monkeypatch.setattr(lifecycle, "maintenance_replay_check", guard)
    monkeypatch.setattr(codex_adapter, "audit_hook", lambda root, event, value, *_args: guard(root, value))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    argv = ["--root", str(tmp_path), "audit-hook", "PreToolUse"]
    if replay:
        argv += ["--maintenance-replay-contract", str(tmp_path / "contract.json")]
    assert cli.main(argv) == 0
    assert received == [payload]


@pytest.mark.parametrize("raw", [b"", b"\xef\xbb\xbf", b"not-json", b"{",
    b"\xff{}", b"\xef\xbb\xbf{\xff}", b"\xff\xfe{\x00}\x00",
    b"\xef\xbb\xbf\xef\xbb\xbf{}", b" \xef\xbb\xbf{}", b"{\xef\xbb\xbf}"])
def test_invalid_hook_document_still_reaches_replay_guard_as_invalid(tmp_path, monkeypatch, capsys, raw):
    received = []
    original = lifecycle.maintenance_replay_check
    def guard(root, value, filename):
        received.append(value)
        return original(root, value, filename)
    monkeypatch.setattr(lifecycle, "maintenance_replay_check", guard)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    assert cli.main(["--root", str(tmp_path), "audit-hook", "PreToolUse",
                     "--maintenance-replay-contract", str(tmp_path / "contract.json")]) == 0
    assert received == [None]
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("raw,stage,value", [
    (b"\xff{private-secret}", "decode", None),
    (b"{private-secret}", "json", None),
    (b"\xef\xbb\xbf\xef\xbb\xbf{}", "json", None),
    (b'["private-secret"]', "json-shape", ["private-secret"]),
    (b"null", "json-shape", None),
])
def test_transport_diagnostic_reports_actual_boundary_without_payload(tmp_path, monkeypatch, capsys, raw, stage, value):
    received = []
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(lifecycle, "maintenance_replay_check", lambda root, payload, filename:
                        received.append(payload) or lifecycle._permission_deny("TEST_DENIED"))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    assert cli.main(["--root", str(tmp_path), "audit-hook", "PreToolUse",
                     "--maintenance-replay-contract", str(tmp_path / "private-contract")]) == 0
    result = capsys.readouterr()
    assert received == [value]
    assert json.loads(result.out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert json.loads(result.err) == {"diagnostic": "thaliris-failure-v1", "stage": stage}
    assert "private" not in result.err and str(tmp_path) not in result.err


def test_receive_and_dispatch_diagnostics_do_not_serialize_exceptions(tmp_path, monkeypatch, capsys):
    class BrokenInput:
        def read(self):
            raise OSError("private-credential" * 10000)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=BrokenInput()))
    monkeypatch.setattr(lifecycle, "maintenance_replay_check", lambda *_args: lifecycle._permission_deny("TEST_DENIED"))
    argv = ["--root", str(tmp_path), "audit-hook", "PreToolUse",
            "--maintenance-replay-contract", str(tmp_path / "private-contract")]
    assert cli.main(argv) == 0
    result = capsys.readouterr()
    assert json.loads(result.err)["stage"] == "receive"
    assert json.loads(result.out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8"))
    def broken_guard(*_args):
        raise RuntimeError("private-credential" * 10000)
    monkeypatch.setattr(lifecycle, "maintenance_replay_check", broken_guard)
    assert cli.main(argv) == 2
    result = capsys.readouterr()
    assert json.loads(result.err)["stage"] == "dispatch"
    assert json.loads(result.out) == {"ok": False, "error": "HOOK_DISPATCH_FAILED"}
    assert "private" not in result.err + result.out
    assert len(result.err + result.out) < 256


def test_contract_document_and_runtime_identity_have_separate_failure_boundaries(tmp_path, capsys):
    filename = tmp_path / "private-contract.json"
    filename.write_text('{private-credential}', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        host_maintenance.contract(filename, "codex-install", tmp_path)
    assert json.loads(capsys.readouterr().err)["stage"] == "maintenance-contract"
    filename.write_text(json.dumps({"format": host_maintenance.FORMAT, "operation": "codex-install",
        "codex_home": str(tmp_path), "human_instruction": "private instruction", "executor": "private-token"}), encoding="utf-8")
    with pytest.raises(ValueError, match="independently selected runtime"):
        host_maintenance.contract(filename, "codex-install", tmp_path)
    result = capsys.readouterr()
    assert json.loads(result.err) == {"diagnostic": "thaliris-failure-v1", "stage": "runtime-identity"}
    assert "private" not in result.err and str(tmp_path) not in result.err


@pytest.mark.parametrize("exception", [OSError, ValueError, RuntimeError, AttributeError])
def test_diagnostic_sink_failure_cannot_change_refusal(monkeypatch, exception):
    class BrokenSink:
        def write(self, _value):
            raise exception("private sink failure")
    monkeypatch.setattr(sys, "stderr", BrokenSink())
    with pytest.raises(ValueError, match="independently selected runtime"):
        host_maintenance.selected_runtime("private-token")
    diagnostics.failure("untrusted-private-stage")
