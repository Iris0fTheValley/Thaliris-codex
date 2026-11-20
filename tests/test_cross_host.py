from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

import pytest

from thaliris import core
from thaliris_codex import cli, foreign_session, lifecycle, task_authority, xhost, xhost_runner
from tests.test_evidence_continuity_adapter import evidence_task, _event, _register_requirement


ABI = lifecycle.MANAGED_HOOK_ABI
RESULT = ('selected result\n```thaliris-claims\n{"claims":[{"requirement":"R1","polarity":"unknown",'
          '"text":"Check unavailable","evidence":"src/main.py:1","basis":"read"}]}\n```')


@pytest.fixture
def task(evidence_task, monkeypatch, tmp_path):
    root, task_id = evidence_task
    _register_requirement(root)
    monkeypatch.setattr(xhost, "selector_path", lambda value: tmp_path / "isolated-selectors" / (value + ".json"))
    runner = tmp_path / "trusted runner.cmd"
    runner.touch()
    monkeypatch.setattr(lifecycle, "_trusted_installed_runner", lambda: runner)
    return root, task_id


def reserve(root, **options):
    selection = {"candidate": "candidate-xhost", "requirement_refs": ["R1"], "prompt": "private selected prompt", **options}
    return xhost.reserve(root, role="investigator", base_revision=core._load_state(root)["revision"],
                         selection=selection, owner_hash=lifecycle._session_id_hash(_event()))


def hook_command(root, operation, **actor):
    runner = root / "trusted runner.cmd"
    prefix = "& " if os.name == "nt" else ""
    command = f"{prefix}'{runner}' --root '{root}' --task-id {core.selected_task(root)} {operation}"
    payload = _event(tool_name="Bash", tool_input={"command": command}, **actor)
    decision = lifecycle.handle_hook(root, "PreToolUse", payload, ABI)
    return json.loads(decision)["hookSpecificOutput"] if decision else {}


def ticket_for(root, handoff):
    output = hook_command(root, "xhost-run --handoff " + handoff)
    assert output["permissionDecision"] == "allow", output
    return re.search(r"--launch-ticket ([0-9a-f]{64})", output["updatedInput"]["command"])[1]


def reserve_id(root, **options):
    response = reserve(root, **options)
    handoff = response["foreign"]["handoff_id"]
    assert response["launch_args"] == ["xhost-run", "--handoff", handoff]
    assert "private selected prompt" not in str(response)
    return handoff


def test_controller_reservation_cas_and_exact_launcher_guard(task):
    root, task_id = task
    state = core._load_state(root)
    selection = {"candidate": "e", "requirement_refs": ["R1"], "prompt": "selected"}
    with pytest.raises(ValueError, match="XHOST_CONTROLLER_REQUIRED"):
        xhost.reserve(root, role="investigator", base_revision=state["revision"], selection=selection, owner_hash="forged")
    with pytest.raises(core.ThalirisError, match="revision"):
        xhost.reserve(root, role="investigator", base_revision=state["revision"] - 1, selection=selection,
                      owner_hash=lifecycle._session_id_hash(_event()))
    handoff = reserve_id(root)
    command = "xhost-run --handoff " + handoff
    with pytest.raises(ValueError, match="XHOST_LAUNCH_TICKET_REQUIRED"):
        xhost_runner.run(root, handoff, None)
    for invalid_actor in ({"agent_id": "child", "agent_type": "thaliris-implementer"},
                          {"readonly": True}, {"fenced": True}):
        assert hook_command(root, command, **invalid_actor)["permissionDecision"] == "deny"
    for denied in (command + " --launch-ticket fake", "xhost-run --handoff handoff-" + "f" * 32):
        assert hook_command(root, denied)["permissionDecision"] == "deny"
    unpinned = _event(tool_name="Bash", tool_input={"command": "thaliris " + command})
    assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", unpinned, ABI)
    wrong_session = {**_event(), "session_id": "other"}
    with pytest.raises(ValueError, match="XHOST_CONTROLLER_REQUIRED"):
        xhost.issue_launch_ticket(root, handoff, wrong_session)
    ticket = ticket_for(root, handoff)
    newer_ticket = ticket_for(root, handoff)
    assert newer_ticket != ticket
    with pytest.raises(ValueError, match="XHOST_LAUNCH_TICKET_REQUIRED"):
        xhost_runner.run(root, handoff, ticket)
    assert xhost.handoff_in(core._load_state(root), handoff)["run_state"] == "reserved"
    assert task_authority.check(root)["task_id"] == task_id


def test_reserve_command_requires_a_fresh_hook_ticket(task, capsys):
    root, task_id = task
    source = root / "packet.json"
    source.write_text(json.dumps({"candidate": "e", "requirement_refs": ["R1"], "prompt": "selected"}), encoding="utf-8")
    revision = core._load_state(root)["revision"]
    args = ["--root", str(root), "--task-id", task_id, "xhost-reserve", "--role", "investigator",
            "--base-revision", str(revision), "--input", str(source)]
    assert cli.main(args) == 2
    assert "XHOST_CONTROLLER_TICKET_REQUIRED" in capsys.readouterr().out
    output = hook_command(root, f"xhost-reserve --role investigator --base-revision {revision} --input '{source}'")
    ticket = re.search(r"--xhost-ticket ([0-9a-f]{64})", output["updatedInput"]["command"])[1]
    assert cli.main([*args, "--xhost-ticket", ticket]) == 0
    assert json.loads(capsys.readouterr().out)["launch_args"][0] == "xhost-run"
    assert cli.main([*args, "--xhost-ticket", ticket]) == 2
    assert "XHOST_CONTROLLER_TICKET_REQUIRED" in capsys.readouterr().out


def test_reserved_foreign_run_blocks_close_and_disposes_without_a_relay(task):
    root, task_id = task
    reservation = reserve(root)
    handoff = reservation["foreign"]["handoff_id"]
    diagnostic = lifecycle.native_execution_diagnostic(root)
    assert {"kind": "foreign-run-unresolved", "handoff_id": handoff, "run_state": "reserved"}.items() <= diagnostic["blockers"][0].items()
    disposed = lifecycle.task_dispose_dependency(root, handoff, reservation["revision"],
        diagnostic["expected_lifecycle_sha256"], "Controller discarded an unlaunched reservation")
    assert disposed["native_execution"] == "UNKNOWN"
    assert lifecycle.native_execution_closed(root)
    assert xhost.handoff_in(core._load_state(root), handoff)["run_state"] == "cancelled"
    assert task_authority.check(root)["task_id"] == task_id


def test_disposition_refuses_a_previously_issued_launch_ticket(task):
    root, task_id = task
    handoff = reserve_id(root)
    ticket = ticket_for(root, handoff)
    current = core._load_state(root)
    digest = task_authority.digest(lifecycle._lifecycle_path(root, task_id))
    lifecycle.task_dispose_dependency(root, handoff, current["revision"], digest, "Controller cancelled before workload")
    with pytest.raises(core.ThalirisError) as error:
        xhost_runner.run(root, handoff, ticket)
    assert error.value.code == "FOREIGN_RUN_STATE_CONFLICT"
    assert xhost.handoff_in(core._load_state(root), handoff)["run_state"] == "cancelled"
    assert task_authority.check(root)["task_id"] == task_id


def _simulate_claude(monkeypatch, script):
    monkeypatch.setattr(xhost_runner.shutil, "which", lambda _: sys.executable)
    monkeypatch.setattr(xhost_runner, "_claude_command", lambda exe, session, _config, _opts:
                        [exe, "-u", "-c", script, session, RESULT])


def test_prebind_last_result_usage_and_no_duplicate_claims(task, monkeypatch):
    root, task_id = task
    handoff = reserve_id(root, claude_effort="high")
    ticket = ticket_for(root, handoff)
    real_process = xhost_runner._owned_process

    def process(argv, cwd, environment):
        state = core._load_state(cwd, active=True)
        foreign = xhost.handoff_in(state, handoff)
        assert foreign["run_state"] == "bound"
        assert foreign["foreign_session_hash"] == core.foreign_session_hash(argv[-2])
        assert foreign["transport_agent_id_hash"] == lifecycle._session_id_hash(_event())
        assert task_authority.check(cwd)["task_id"] == task_id
        assert environment[xhost.TASK_ENV] == task_id
        return real_process(argv, cwd, environment)

    monkeypatch.setattr(xhost_runner, "_owned_process", process)
    _simulate_claude(monkeypatch, """
import json, sys
_, session, final = sys.argv
prompt = sys.stdin.read()
assert 'private selected prompt' in prompt and 'claude_effort' not in prompt
def emit(**value): print(json.dumps(dict(value, session_id=session)), flush=True)
emit(type='system', subtype='init', tools=['Read', 'Grep', 'Glob'], mcp_servers=[], apiKeySource='ANTHROPIC_API_KEY')
emit(type='assistant', message={'content': [{'type': 'tool_use', 'name': 'Read', 'id': 'tool-1'}]})
emit(type='result', is_error=False, result='earlier result')
emit(type='result', is_error=False, result=final, duration_ms=15, total_cost_usd=0.02,
     modelUsage={'claude-model': {'outputTokens': 11}},
     usage={'input_tokens': 4, 'cache_read_input_tokens': 5, 'cache_creation_input_tokens': 2, 'output_tokens': 11})
""")
    assert xhost_runner.run(root, handoff, ticket)["foreign"]["run_state"] == "completed"
    assert xhost.result(root, handoff)["text"] == RESULT
    before = deepcopy(core._load_state(root))
    foreign = xhost.handoff_in(before, handoff)
    assert foreign["usage"] == {"model": "claude-model", "effort": "high", "input_tokens": 11, "output_tokens": 11,
        "total_tokens": 22, "duration_ms": 15, "cost_usd": 0.02, "cost_basis": "metered", "tool_uses": 1, "outcome": "completed"}
    assert foreign["result_source"] == "foreign-runner"
    assert before["evidence_continuity"]["observations"][0]["provenance"] == "foreign-runner"
    assert core.ingest_claims(before, handoff, RESULT)["already_ingested"] is True
    assert core._load_state(root) == before
    with pytest.raises(ValueError, match="XHOST_LAUNCH_TICKET_REQUIRED"):
        xhost_runner.run(root, handoff, ticket)
    assert task_authority.check(root)["task_id"] == task_id


@pytest.mark.parametrize("partial", [False, True])
def test_timeout_kills_process_tree_and_settles(task, monkeypatch, partial):
    root, task_id = task
    handoff = reserve_id(root)
    ticket = ticket_for(root, handoff)
    path = root / "survived"
    started_path = root / "grandchild-started"
    grandchild = "from pathlib import Path; import sys,time; time.sleep(2); Path(sys.argv[1]).touch()"
    script = ("import json,subprocess,sys,time\n"
              "sys.stdin.read()\n"
              f"subprocess.Popen([sys.executable,'-c',{grandchild!r},{str(path)!r}])\n"
              f"open({str(started_path)!r},'w').close()\n"
              + ("print(json.dumps({'session_id':sys.argv[1],'type':'assistant','message':{'content':[{'type':'text','text':'partial'}]}}),flush=True)\n"
                 if partial else "") + "time.sleep(30)\n")
    _simulate_claude(monkeypatch, script)
    monkeypatch.setitem(xhost_runner.TIMEOUTS, "investigator", 1.2)
    expected = "failed" if partial else "cancelled"
    assert xhost_runner.run(root, handoff, ticket)["foreign"]["run_state"] == expected
    assert started_path.is_file()
    assert task_authority.check(root)["task_id"] == task_id
    if partial:
        assert xhost.result(root, handoff)["text"] == "partial"
    # The subprocess explicitly backgrounds its own subprocess before timing out.
    # Wait on a process with the same delay to test the side effect after its deadline.
    subprocess.run([sys.executable, "-c", "import time; time.sleep(2.1)"], check=True)
    assert not path.exists()


def test_dispose_cancels_a_bound_process_and_late_result(task, monkeypatch):
    root, task_id = task
    handoff = reserve_id(root)
    ticket = ticket_for(root, handoff)
    _simulate_claude(monkeypatch, "import sys,time; sys.stdin.read(); time.sleep(30)")
    started = threading.Event()
    real_collect = xhost_runner._collect

    def signal_started(*args):
        started.set()
        return real_collect(*args)

    monkeypatch.setattr(xhost_runner, "_collect", signal_started)
    result = []

    def launch():
        core.select_task(root, task_id)
        result.append(xhost_runner.run(root, handoff, ticket))

    worker = threading.Thread(target=launch)
    worker.start()
    assert started.wait(timeout=10)
    state = core._load_state(root)
    digest = task_authority.digest(lifecycle._lifecycle_path(root, task_id))
    assert lifecycle.task_dispose_dependency(root, handoff, state["revision"], digest, "stop this dependency")["ok"]
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert result[0]["foreign"]["run_state"] == "cancelled"
    assert xhost_runner._settle(root, handoff, "completed", RESULT, {})["run_state"] == "cancelled"
    assert "result_sha256" not in xhost.handoff_in(core._load_state(root), handoff)
    assert task_authority.check(root)["task_id"] == task_id


@pytest.mark.parametrize("handoff", ["H0123abcd", "handoff-" + "f" * 32])
def test_incoming_binding_exact_readonly_with_or_without_marker(task, monkeypatch, handoff):
    root, task_id = task
    session = str(uuid.uuid4())
    with task_authority._lock(root):
        state = core._load_state(root)
        record = {"id": handoff, "parent_handoff_id": None, "candidate": "incoming", "producer": "reviewer", "requirement_refs": ["R1"]}
        core.reserve_foreign_handoff(state, record, executor_host="codex", prompt="selected", root=root)
        digest = core.foreign_session_hash(session)
        core.register_foreign_launch(state, handoff, digest, "f" * 64)
        core.bind_foreign_session(state, digest)
        lifecycle._write_evidence_reservation(root, state, lifecycle._lifecycle_path(root, task_id), None)
    xhost.publish_selector(root, task_id, handoff, digest)
    event = {"cwd": str(root), "session_id": session, "tool_name": "exec_command", "tool_input": {"cmd": "Get-Content -LiteralPath README.md"}}
    before = core._state_path(root).read_bytes()
    assert "read-only foreign Thaliris child" in lifecycle.handle_hook(root, "SessionStart", event, ABI)
    assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", event, ABI)
    for command in ("Get-Content -LiteralPath ../outside", "rg --no-config --pre python foo", "rg --files", "Get-Content -LiteralPath README.md; whoami",
                    "codex exec pwd", "thaliris task-start new", "python -c print", "Get-Content -LiteralPath Env:HOME"):
        assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", {**event, "tool_input": {"cmd": command}}, ABI)
    for tool in ("Bash", "mcp__codex_app__list_projects", "spawn_agent", "apply_patch", "write_stdin"):
        assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", {**event, "tool_name": tool}, ABI)
    for tool, args in [("read_file", {"path": "README.md", "start_line": 2}), ("list_files", {}),
                       ("search_files", {"query": "readonly"})]:
        assert lifecycle.handle_hook(root, "PreToolUse", {**event, "tool_name": tool, "tool_input": args}, ABI) == ""
    for tool, args in [("mcp__s__read_file", {"path": "README.md"}), ("read_file", {"path": "../outside"}),
                       ("read_file", {"path": "README.md", "start_line": True}), ("list_files", {"cmd": "whoami"}),
                       ("search_files", {"query": ""})]:
        assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", {**event, "tool_name": tool, "tool_input": args}, ABI)
    monkeypatch.setenv("THALIRIS_FOREIGN_CHILD", "1")
    monkeypatch.setenv(xhost.TASK_ENV, str(uuid.uuid4()))
    monkeypatch.setenv(xhost.HANDOFF_ENV, handoff)
    assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", event, ABI)
    monkeypatch.setenv(xhost.TASK_ENV, task_id)
    assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", {**event, "session_id": str(uuid.uuid4())}, ABI)
    assert core._state_path(root).read_bytes() == before
    assert task_authority.check(root)["task_id"] == task_id
    state = core._load_state(root)
    core.cancel_foreign_run(state, handoff, "dispatched Host stopped")
    lifecycle._write_evidence_reservation(root, state, lifecycle._lifecycle_path(root, task_id), None)
    assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", event, ABI)


def test_foreign_marker_without_selector_stays_unbound_and_skips_telemetry(task, monkeypatch):
    root, _task_id = task
    monkeypatch.setenv(foreign_session.MARKER_ENV, "1")
    monkeypatch.delenv(xhost.TASK_ENV, raising=False)
    monkeypatch.delenv(xhost.HANDOFF_ENV, raising=False)
    session = str(uuid.uuid4())
    event = {"cwd": str(root), "session_id": session, "tool_name": "read_file",
             "tool_input": {"path": "README.md"}}
    before = core._state_path(root).read_bytes()
    selected = core.selected_task(root)

    assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", event, ABI)
    start = lifecycle.handle_hook(root, "SessionStart", event, ABI)
    assert "no live, exact handoff binding" in start
    assert lifecycle.handle_hook(root, "PostToolUse", event, ABI) == ""
    assert core._state_path(root).read_bytes() == before
    assert core.selected_task(root) == selected


def test_incoming_selector_ids_use_core_labels_but_require_exact_live_ledger_rows(task, monkeypatch):
    root, task_id = task
    event_base = {"cwd": str(root), "tool_name": "read_file", "tool_input": {"path": "README.md"}}
    before = core._state_path(root).read_bytes()
    for identifier in ("Hdeadbeef", "bad handoff id"):
        session = str(uuid.uuid4())
        session_hash = core.foreign_session_hash(session)
        xhost.publish_selector(root, task_id, identifier, session_hash)
        event = {**event_base, "session_id": session}
        assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", event, ABI)
        assert core._state_path(root).read_bytes() == before

    malformed_session = str(uuid.uuid4())
    malformed_selector = xhost.selector_path(core.foreign_session_hash(malformed_session))
    malformed_selector.parent.mkdir(parents=True, exist_ok=True)
    malformed_selector.write_text('{"root":', encoding="utf-8")
    monkeypatch.setenv(foreign_session.MARKER_ENV, "1")
    monkeypatch.delenv(xhost.TASK_ENV, raising=False)
    monkeypatch.delenv(xhost.HANDOFF_ENV, raising=False)
    malformed_event = {**event_base, "session_id": malformed_session}
    assert '"permissionDecision":"deny"' in lifecycle.handle_hook(root, "PreToolUse", malformed_event, ABI)
    assert lifecycle.handle_hook(root, "PostToolUse", malformed_event, ABI) == ""
    assert core._state_path(root).read_bytes() == before


@pytest.mark.skipif(os.environ.get("THALIRIS_TEST_REAL_CLAUDE") != "1", reason="requires a configured Claude Code subscription")
def test_real_claude_launcher(task, capsys):
    root, task_id = task
    (root / "selected.txt").write_text("Thaliris selected fixture identifier AC79YQ\n", encoding="utf-8")
    expected = "AC79YQ"
    handoff = reserve_id(root,
        prompt="Read selected.txt using the Read tool and report the fixture identifier. End with an empty thaliris-claims block.")
    ticket = ticket_for(root, handoff)
    assert cli.main(["--root", str(root), "--task-id", task_id, "xhost-run",
                     "--handoff", handoff, "--launch-ticket", ticket]) == 0
    launched = json.loads(capsys.readouterr().out)
    stored = xhost.result(root, handoff)["text"]
    foreign = xhost.handoff_in(core._load_state(root), handoff)
    assert task_authority.check(root)["task_id"] == task_id
    if launched["foreign"]["run_state"] == "failed" and "can't use your Claude subscription" in stored:
        assert foreign["usage"]["outcome"] == "failed"
        assert foreign["usage"]["cost_basis"] == "subscription-notional"
        pytest.skip("Claude's native subscription entitlement refusal was recorded; semantic result unavailable")
    assert launched["foreign"]["run_state"] == "completed", launched
    assert expected in stored
    assert foreign["usage"]["tool_uses"] >= 1
    assert foreign["usage"]["output_tokens"] > 0
    assert foreign["usage"]["model"].startswith("claude-")
