"""Exercise generated PowerShell and CMD hooks against isolated native fixtures."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import thaliris
from thaliris import core

from thaliris_codex import codex_adapter as adapter, host_maintenance as maintenance, host_transition, lifecycle, runtime_identity, runtime_setup
from tests.test_host_maintenance_contract import intent, snapshot
from tests.test_runtime_setup import source_wheel

pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows native preflight")


# The disposable wheel retains the real console launcher and all admission
# checks. Only its replay CLI entry emits bounded source locations and JSON
# transport metadata to stderr; no input content or exception message is recorded.
# This reaches failures that the production fail-closed response intentionally
# collapses to THALIRIS_HOST_MAINTENANCE_REPLAY_DENIED.
REPLAY_TRACE_ENTRY = '''
_native_replay_main = main
def main():
    import json, sys
    if "--maintenance-replay-contract" not in sys.argv:
        return _native_replay_main()
    events = []
    watched = {"maintenance_replay_check", "_trusted_host_maintenance_route",
               "_context_call", "_context_arguments", "contract", "selected_runtime",
               "load", "console_smoke", "managed_task_state"}
    def trace(frame, event, arg):
        module = frame.f_globals.get("__name__", "")
        if module.startswith(("thaliris.", "thaliris_codex.")):
            name = frame.f_code.co_name
            if event == "exception" or (event == "return" and name in watched):
                item = {"module": module, "function": name,
                        "line": frame.f_lineno, "event": event}
                if event == "exception":
                    item["exception"] = arg[0].__name__
                    if module == "thaliris_codex.cli" and isinstance(arg[1], json.JSONDecodeError):
                        error = arg[1]
                        item["input_char_count"] = len(error.doc)
                        item["json_error_position"] = error.pos
                        item["input_prefix_kind"] = ("empty" if not error.doc else
                            "bom" if error.doc.startswith(chr(0xfeff)) else
                            "object" if error.doc.lstrip().startswith("{") else
                            "array" if error.doc.lstrip().startswith("[") else "other")
                elif arg is False or arg is None:
                    item["result"] = str(arg)
                else:
                    item["result"] = "returned"
                events.append(item)
                if len(events) > 64:
                    del events[0]
        return trace
    sys.settrace(trace)
    try:
        return _native_replay_main()
    finally:
        sys.settrace(None)
        sys.stderr.write(json.dumps({"native_replay_trace": events}) + "\\n")
'''


@pytest.fixture(scope="module")
def replay_runtime(tmp_path_factory):
    source = tmp_path_factory.mktemp("native-replay-source")
    core_source = source_wheel(source, "thaliris", Path(thaliris.__file__).parent)
    diagnostic_package = source / "diagnostic-package" / "thaliris_codex"
    shutil.copytree(Path(lifecycle.__file__).parent, diagnostic_package)
    cli = diagnostic_package / "cli.py"
    cli.write_bytes(cli.read_bytes() + REPLAY_TRACE_ENTRY.encode("utf-8"))
    adapter_source = source_wheel(source, "thaliris_codex", diagnostic_package, entry=True)
    target = source / "venv"
    result = runtime_setup.create(target, core_source, adapter_source)
    return Path(result["executable"])


@pytest.fixture
def pending_native(tmp_path, monkeypatch, pinned_test_thaliris, replay_runtime):
    home = tmp_path / "home"
    project = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".codex").mkdir()
    (project / ".codex/thaliris.json").write_text("{}")
    core.init(project)
    core.task_start(project, "Isolated native maintenance replay fixture", None, None)
    monkeypatch.setenv("CODEX_HOME", str(home))

    def make_intent(exe, operation="codex-install", unicode=False):
        path = intent(tmp_path, home, exe, operation)
        value = json.loads(path.read_text(encoding="utf-8"))
        if unicode:
            value["human_instruction"] += " Unicode intent: 雪 🪷 \ufeffpreserved"
        contents = runtime_identity.manifest_bytes(exe)
        metadata = json.loads((exe.parent.parent / "Lib/site-packages/thaliris_codex-0.4.3.dist-info/direct_url.json").read_bytes())
        if "vcs_info" in metadata:
            source_pin = "git+" + metadata["url"] + "@" + metadata["vcs_info"]["commit_id"]
        else:
            source_pin = "sha256:" + metadata["archive_info"]["hashes"]["sha256"]
        selected = {"executable": str(exe), "runtime_sha256": maintenance.digest(contents), "source_pin": source_pin}
        value["executor"] = selected
        if operation == "codex-install":
            value["candidate"] = selected
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def prepare(*, distinct=False, operation="codex-install", prepared=False, unicode=False):
        old_exe = pinned_test_thaliris[0] if distinct else replay_runtime
        monkeypatch.setattr(adapter, "_host_install_executable", lambda *_a: (old_exe, maintenance.digest(old_exe.read_bytes()), None))
        assert adapter.codex_install(maintenance_contract=make_intent(old_exe, unicode=unicode))["ok"]
        old_manifest = (home / runtime_identity.MANIFEST_NAME).read_bytes()
        path = make_intent(replay_runtime, operation, unicode=unicode)
        monkeypatch.setattr(adapter, "_host_install_executable", lambda *_a: (replay_runtime, maintenance.digest(replay_runtime.read_bytes()), None))
        if operation == "codex-install":
            monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *_a: {"status": "FAILED"})
            assert not adapter.codex_install(maintenance_contract=path)["ok"]
        else:
            from thaliris_codex import codex_app_server
            monkeypatch.setattr(codex_app_server, "remove_owned_hook_trust", lambda *_a: (_ for _ in ()).throw(RuntimeError("interrupted trust")))
            assert not adapter.codex_uninstall(maintenance_contract=path)["ok"]
        if prepared:
            journal = home / host_transition.NAME
            record = json.loads(journal.read_bytes());record["phase"] = "PREPARED"
            journal.write_text(json.dumps(record))
        command = lifecycle._pinned_host_command(home / lifecycle.HOST_HOOK_SCRIPT_NAME, old_exe,
            maintenance.digest(old_exe.read_bytes()), maintenance.digest(old_manifest), "PreToolUse")
        payload = {"hook_event_name": "PreToolUse", "session_id": "native-controller-session", "cwd": str(project),
            "tool_name": "functions.exec_command", "tool_input": {"cmd": f"& '{replay_runtime}' {operation} --maintenance-contract '{path}'"}}
        return home, project, path, command, payload

    return prepare


def native(command, project, payload):
    prefix = 'powershell.exe -NoProfile -NonInteractive -Command "'
    assert command.startswith(prefix) and command.endswith('"')
    source = command[len(prefix):-1]
    before = snapshot(project)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", source],
        input=json.dumps(payload).encode(), cwd=project, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert snapshot(project) == before
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    if decision.get("permissionDecision") == "deny" and result.stderr:
        decision["nativeReplayDiagnostic"] = result.stderr.decode(errors="replace")
    return decision


def console_replay(executable, project, path, raw):
    before = snapshot(project)
    result = subprocess.run([str(executable), "--root", str(project), "audit-hook", "PreToolUse",
        "--maintenance-replay-contract", str(path)],
        input=raw, cwd=project, env=runtime_identity.child_environment(), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert snapshot(project) == before
    return json.loads(result.stdout)["hookSpecificOutput"]


@pytest.mark.parametrize("distinct", [False, True])
@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("operation", ["codex-install", "codex-uninstall"])
def test_exact_original_native_replay_admitted(pending_native, distinct, prepared, operation):
    home, project, path, command, payload = pending_native(distinct=distinct, prepared=prepared, operation=operation)
    before = snapshot(home)
    result = native(command, project, payload)
    # A string message preserves the full bounded trace in pytest/JUnit;
    # pytest truncates large dictionary assertion messages with saferepr.
    assert result["permissionDecision"] == "allow", json.dumps(result, indent=2)
    assert "UNKNOWN" in result["additionalContext"]
    assert snapshot(home) == before


@pytest.mark.parametrize("operation", ["codex-install", "codex-uninstall"])
def test_utf8_signature_preserves_native_and_console_replay(pending_native, replay_runtime, operation):
    home, project, path, command, payload = pending_native(distinct=True, operation=operation, unicode=True)
    payload["metadata"] = {"source": "雪 🪷", "\ufeffkey": "\ufeffvalue\ufeff"}
    before_home, before_project, contract = snapshot(home), snapshot(project), path.read_bytes()
    baseline = native(command, project, payload)
    assert baseline["permissionDecision"] == "allow", json.dumps(baseline, indent=2)
    for signature in (b"", b"\xef\xbb\xbf"):
        # Compare the native preflight decision to the same selected console
        # launcher's UTF-8 document boundary, including actual Unicode bytes.
        assert console_replay(replay_runtime, project, path,
            signature + json.dumps(payload, ensure_ascii=False).encode("utf-8")) == baseline
    assert path.read_bytes() == contract
    assert snapshot(home) == before_home
    assert snapshot(project) == before_project


def test_utf8_signature_never_weakens_console_replay_guards(pending_native, replay_runtime):
    home, project, path, command, payload = pending_native(distinct=True, unicode=True)
    before = snapshot(home)
    original = payload["tool_input"]["cmd"]
    invalid = [{**payload, **actor} for actor in ({"agent_id": "child"}, {"agent_type": "unknown"},
               {"readonly": True}, {"fenced": True})]
    invalid += [{**payload, "tool_input": {"cmd": cmd}} for cmd in (
        original.replace(str(replay_runtime), str(replay_runtime.with_name("unapproved.exe"))),
        original.replace(str(replay_runtime), str(replay_runtime) + "\ufeff"),
        original + " --execution-constraint luna-only",
        original + f" --maintenance-contract '{path}'")]
    invalid += [None, [], "unknown actor"]
    for value in invalid:
        for signature in (b"", b"\xef\xbb\xbf"):
            assert console_replay(replay_runtime, project, path,
                signature + json.dumps(value, ensure_ascii=False).encode("utf-8"))["permissionDecision"] == "deny"
    # A transport signature cannot repair drift in independently hashed intent.
    contract = path.read_bytes()
    intent = json.loads(contract)
    intent["human_instruction"] += " changed"
    path.write_text(json.dumps(intent, ensure_ascii=False), encoding="utf-8")
    try:
        for signature in (b"", b"\xef\xbb\xbf"):
            assert console_replay(replay_runtime, project, path,
                signature + json.dumps(payload).encode())["permissionDecision"] == "deny"
    finally:
        path.write_bytes(contract)
    assert snapshot(home) == before


@pytest.mark.parametrize("distinct", [False, True])
@pytest.mark.parametrize("actor", [{"agent_id": "native-child", "agent_type": "thaliris-focused-implementer"},
    {"agent_type": "thaliris-reviewer"}, {"readonly": True}, {"fenced": True}])
def test_native_pending_never_grants_denied_actor(pending_native, distinct, actor):
    home, project, path, command, payload = pending_native(distinct=distinct)
    before = snapshot(home)
    assert native(command, project, {**payload, **actor})["permissionDecision"] == "deny"
    assert snapshot(home) == before


@pytest.mark.parametrize("defect", ["contract", "other_executor", "missing_contract", "executable", "journal", "receipt",
    "unknown_managed_bytes", "state_directory", "session_fence", "abandoned_owner", "broken_fence", "broken_child_fence", "compound", "option_drift", "executor_snapshot"])
def test_native_replay_input_drift_fails_closed(pending_native, defect):
    home, project, path, command, payload = pending_native(distinct=True)
    restore = None
    if defect == "contract":
        value = json.loads(path.read_bytes()); value["human_instruction"] += " changed"
        path.write_text(json.dumps(value))
    elif defect == "other_executor":
        selected = Path(json.loads(path.read_bytes())["executor"]["executable"])
        payload["tool_input"]["cmd"] = payload["tool_input"]["cmd"].replace(
            str(selected), str(selected.with_name("unapproved.exe"))
        )
    elif defect == "missing_contract":
        path.unlink()
    elif defect == "executable":
        exe = Path(json.loads(path.read_bytes())["executor"]["executable"])
        original = exe.read_bytes();exe.write_bytes(original + b"drift")
        restore = lambda: exe.write_bytes(original)
    elif defect in {"journal", "receipt", "executor_snapshot"}:
        journal = home / host_transition.NAME
        value = json.loads(journal.read_bytes())
        if defect == "journal":
            value["phase"] = "UNKNOWN"
        elif defect == "executor_snapshot":
            value["executor_runtime"] = "invalid bytes"
        else:
            import base64
            value["before"][maintenance.RECEIPT_NAME] = base64.b64encode(b"unverifiable historical receipt").decode()
        journal.write_text(json.dumps(value))
    elif defect in {"unknown_managed_bytes", "state_directory"}:
        state = project / ".context" / "state.json"
        if defect == "state_directory":
            state.unlink();state.mkdir()
        else:
            state.write_text("unknown managed state")
    elif defect in {"session_fence", "abandoned_owner", "broken_fence", "broken_child_fence"}:
        hashes = [hashlib.sha256(payload["session_id"].encode()).hexdigest()]
        fence = lifecycle._abandoned_child_fence_path(project) if defect in {"abandoned_owner", "broken_child_fence"} else lifecycle._session_fence_path(project)
        fence.parent.mkdir(parents=True, exist_ok=True)
        fence.write_text("invalid fence" if defect in {"broken_fence", "broken_child_fence"} else json.dumps({"version": 1, "children": [],
            "owner_session_id_hashes" if defect == "abandoned_owner" else "session_id_hashes": hashes}))
    elif defect == "compound":
        payload["tool_input"]["cmd"] += "; Write-Output arbitrary"
    else:
        payload["tool_input"]["cmd"] += " --execution-constraint luna-only"
    before = snapshot(home)
    try:
        assert native(command, project, payload)["permissionDecision"] == "deny"
        assert snapshot(home) == before
    finally:
        if restore:
            restore()


def test_degraded_native_denies_child_other_executor_even_with_invalid_journal(pending_native):
    home, project, path, command, payload = pending_native(distinct=True)
    (home / host_transition.NAME).write_text("unverifiable journal")
    assert native(command, project, {**payload, "agent_id": "child"})["permissionDecision"] == "deny"


@pytest.mark.parametrize("defect", ["state", "option_drift"])
def test_native_replay_diagnostic_identifies_swallowed_guard_without_recording_inputs(pending_native, defect):
    home, project, path, command, payload = pending_native()
    if defect == "state":
        state = project / ".context" / "state.json"
        state.write_text("unknown managed state")
    else:
        payload["tool_input"]["cmd"] += " --execution-constraint luna-only"
    before = snapshot(home)
    result = native(command, project, payload)
    assert result["permissionDecision"] == "deny"
    diagnostic = json.loads(result["nativeReplayDiagnostic"])
    events = diagnostic["native_replay_trace"]
    if defect == "state":
        assert any(item["function"] == "maintenance_replay_check" and
                   item["event"] == "exception" and item["exception"] == "ValueError" for item in events)
    else:
        assert any(item["function"] == "_trusted_host_maintenance_route" and
                   item["event"] == "return" and item["result"] == "False" for item in events)
    assert len(events) <= 64
    assert all(set(item) <= {"module", "function", "line", "event", "exception", "result",
                            "input_char_count", "json_error_position", "input_prefix_kind"} for item in events)
    assert str(home) not in result["nativeReplayDiagnostic"]
    assert payload["session_id"] not in result["nativeReplayDiagnostic"]
    assert snapshot(home) == before


@pytest.mark.parametrize("raw,prefix", [(b"", "empty"),
    (b"private-input-canary", "other"), (b"\xef\xbb\xbf\xef\xbb\xbf{}", "bom")])
def test_replay_diagnostic_distinguishes_invalid_stdin_without_recording_content(tmp_path, monkeypatch, capsys, raw, prefix):
    from thaliris_codex import cli

    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys, "argv", ["thaliris", "--root", str(tmp_path), "audit-hook", "PreToolUse",
                                    "--maintenance-replay-contract", str(tmp_path / "contract.json")])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    entry = {"main": cli.main}
    exec(REPLAY_TRACE_ENTRY, entry)
    assert entry["main"]() == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    events = json.loads(output.err)["native_replay_trace"]
    errors = [item for item in events if item.get("exception") == "JSONDecodeError"]
    assert len(errors) == 1
    assert errors[0]["input_char_count"] == len(raw.decode("utf-8-sig"))
    assert errors[0]["json_error_position"] == 0
    assert errors[0]["input_prefix_kind"] == prefix
    assert "private-input-canary" not in output.err
    assert str(tmp_path) not in output.err


@pytest.mark.parametrize("operation", ["codex-install", "codex-uninstall"])
def test_native_admission_then_original_recovery_completes(pending_native, monkeypatch, operation):
    home, project, path, command, payload = pending_native(distinct=True, operation=operation)
    decision = native(command, project, payload)
    assert decision["permissionDecision"] == "allow", json.dumps(decision, indent=2)
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *_a: {"status": "TRUSTED",
        "trusted_count": len(lifecycle.HOOK_EVENTS), "enabled_count": len(lifecycle.HOOK_EVENTS)})
    from thaliris_codex import codex_app_server
    monkeypatch.setattr(codex_app_server, "remove_owned_hook_trust", lambda *_a: 7)
    invoke = adapter.codex_install if operation == "codex-install" else adapter.codex_uninstall
    result = invoke(maintenance_contract=path)
    assert result["ok"], result
    assert not host_transition.pending(home)
