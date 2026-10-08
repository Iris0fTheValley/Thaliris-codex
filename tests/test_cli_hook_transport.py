"""The hook document's UTF-8 signature never changes its JSON object."""
from __future__ import annotations

import io
import json
import sys

import pytest

from thaliris_codex import cli, codex_adapter, lifecycle


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
