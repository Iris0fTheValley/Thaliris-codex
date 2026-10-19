"""Owned process behavior and exact provider correlation, without model requests."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from thaliris_codex.execution_wait import (
    Correlation, GitHubRunGate, Receipt, cancel, inspect, main, run_process, watch_github,
)


@pytest.fixture
def identity(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "--allow-empty", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    nested = root / "subdirectory"
    nested.mkdir()
    return Correlation.parse(dict(task_id="task", repo_root=str(root), cwd=str(nested), commit=commit,
                                  run_id="owned-run", attempt=1, parent_id="parent", child_id="child",
                                  owner_id="executor", kind="process"))


@pytest.mark.skipif(os.name != "nt", reason="local process execution requires Windows creation-time ownership")
@pytest.mark.parametrize(("script", "status", "exit_code", "stdout"), [
    ("pass", "SUCCEEDED", 0, b""),
    ("import time; print('progress',flush=True); time.sleep(.15); print('done')", "SUCCEEDED", 0, b"progress"),
    ("import sys; print('failed', file=sys.stderr); sys.exit(7)", "FAILED", 7, b""),
    ("print('error is just a word')", "SUCCEEDED", 0, b"error"),
])
def test_owned_process_output_is_durable_and_exit_is_structural(identity, tmp_path, script, status, exit_code, stdout):
    directory = tmp_path / "receipt"
    result = run_process(identity, directory, [sys.executable, "-c", script])
    assert result["status"] == status
    assert result["exit_code"] == exit_code
    assert result["semantic_done"] is False
    assert result["output_complete"] is True
    assert stdout in (directory / "stdout.bin").read_bytes()
    assert inspect(directory, identity) == result
    with pytest.raises(FileExistsError):
        run_process(identity, directory, [sys.executable, "-c", "pass"])


@pytest.mark.skipif(os.name != "nt", reason="local process execution requires Windows creation-time ownership")
def test_timeout_cancel_interrupt_and_spawn_failure(identity, tmp_path):
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    timed = run_process(identity, tmp_path / "timeout", sleeper, timeout=.15)
    assert timed["status"] == "TIMED_OUT" and timed["exit_code"] is not None
    assert timed["interruption_outcome"] == "TIMED_OUT"
    def cancellation(receipt):
        cancel(receipt.directory, identity)
    cancelled = run_process(identity, tmp_path / "cancel", sleeper, on_started=cancellation)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["interruption_outcome"] == "CANCELLED"
    def interrupt(_receipt):
        raise KeyboardInterrupt
    interrupted = run_process(identity, tmp_path / "interrupt", sleeper, on_started=interrupt)
    assert interrupted["status"] == "INTERRUPTED"
    assert interrupted["interruption_outcome"] == "INTERRUPTED"
    failed = run_process(identity, tmp_path / "missing", [str(tmp_path / "missing-executable")])
    assert failed["status"] == "ERROR" and failed["exit_code"] is None


@pytest.mark.skipif(os.name != "nt", reason="Windows creation-time Job Object runtime proof")
def test_cancel_owns_descendants_at_creation_and_preserves_unrelated_process(identity, tmp_path):
    ready, late, release = tmp_path / "ready", tmp_path / "late", tmp_path / "release"
    child = ("from pathlib import Path\nimport time\n"
             f"Path({str(ready)!r}).write_text('ready')\n"
             f"while not Path({str(release)!r}).exists(): time.sleep(.01)\n"
             f"Path({str(late)!r}).write_text('escaped')\ntime.sleep(60)")
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(60)"
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        def cancel_after_child_ready(receipt):
            import time
            deadline = time.monotonic() + 5
            while not ready.exists():
                assert time.monotonic() < deadline, "owned descendant did not start"
                threading.Event().wait(.01)
            cancel(receipt.directory, identity)
        result = run_process(identity, tmp_path / "tree", [sys.executable, "-c", parent],
                             on_started=cancel_after_child_ready)
        assert result["status"] == "CANCELLED"
        assert result["descendant_termination"] == "CONFIRMED_JOB_EMPTY"
        assert result["process_ownership"] == "WINDOWS_CREATION_JOB"
        assert result["output_complete"] is True
        assert unrelated.poll() is None
        # Side effects are released only after confirmed cleanup. A fixed delay
        # from readiness could expire before a loaded runner requested cancel.
        release.touch()
        assert not late.exists(), "descendant survived cancellation"
    finally:
        unrelated.terminate()
        unrelated.wait()


def test_ownership_failure_never_launches_uncontained_fallback(identity, tmp_path, monkeypatch):
    from thaliris_codex import owned_process
    def unavailable(*args):
        raise owned_process.TreeUnavailable("ownership unsupported")
    monkeypatch.setattr(owned_process, "launch", unavailable)
    result = run_process(identity, tmp_path / "unavailable", [sys.executable, "-c", "pass"])
    assert result["status"] == "UNKNOWN"
    assert result["descendant_termination"] == "NOT_STARTED"
    assert result["exit_code"] is None


def test_posix_runner_refuses_before_spawn_or_group_kill(monkeypatch):
    from types import SimpleNamespace
    from thaliris_codex import owned_process
    spawned, killed = [], []
    monkeypatch.setattr(owned_process.subprocess, "Popen", lambda *args, **kwargs: spawned.append(args))
    monkeypatch.setattr(owned_process, "os", SimpleNamespace(name="posix",
                                                               killpg=lambda *args: killed.append(args)))
    with pytest.raises(owned_process.TreeUnavailable, match="was not launched"):
        owned_process.launch([sys.executable, "-c", "pass"], ".")
    assert spawned == []
    assert killed == []
    assert not hasattr(owned_process, "PosixProcess")


@pytest.mark.skipif(os.name == "nt", reason="actual unsupported POSIX runner receipt")
def test_posix_runner_publishes_unknown_without_launching_command(identity, tmp_path):
    marker = tmp_path / "must-not-exist"
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
    directory = tmp_path / "unsupported"
    result = run_process(identity, directory, command)
    assert result["status"] == "UNKNOWN"
    assert result["descendant_termination"] == "NOT_STARTED"
    assert result["exit_code"] is None
    assert "was not launched" in result["error"]
    assert result["semantic_done"] is False
    assert inspect(directory, identity) == result
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows kill-on-close runtime proof")
def test_observer_hard_exit_kills_job_and_leaves_manual_unknown_receipt(identity, tmp_path):
    import ctypes
    from ctypes import wintypes
    import time
    path = tmp_path / "identity.json"
    path.write_text(json.dumps(asdict(identity)))
    ready, late, directory = tmp_path / "ready", tmp_path / "late", tmp_path / "hard-exit"
    release = tmp_path / "release"
    child = ("from pathlib import Path\nimport os,time\n"
             f"Path({str(ready.with_suffix('.new'))!r}).write_text(str(os.getpid()))\n"
             f"os.replace({str(ready.with_suffix('.new'))!r}, {str(ready)!r})\n"
             f"while not Path({str(release)!r}).exists(): time.sleep(.01)\n"
             f"Path({str(late)!r}).write_text('escaped')\ntime.sleep(60)")
    command = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(60)"
    helper = subprocess.Popen([sys.executable, "-m", "thaliris_codex.execution_wait", "run",
                               "--identity", str(path), "--receipt", str(directory), "--",
                               sys.executable, "-c", command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    child_handle = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert helper.poll() is None, helper.communicate()
            assert time.monotonic() < deadline, "owned descendant did not start"
            threading.Event().wait(.01)
        # Synchronize only with the exact live descendant of this fixture.
        # The handle grants no termination right and is never used for a PID kill.
        child_handle = kernel.OpenProcess(0x100000, False, int(ready.read_text()))
        assert child_handle, ctypes.WinError(ctypes.get_last_error())
        assert kernel.WaitForSingleObject(child_handle, 0) == 0x102
        helper.terminate()  # Exact owned observer handle, no PID lookup or enumeration.
        helper.communicate(timeout=5)
        assert kernel.WaitForSingleObject(child_handle, 5000) == 0, "descendant remained alive"
        release.touch()
        assert not late.exists(), "descendant escaped observer kill-on-close"
        result = inspect(directory, identity)
        assert result["status"] == "UNKNOWN"
        assert result["automatic_resume"] == "UNSUPPORTED"
    finally:
        if child_handle:
            kernel.CloseHandle(child_handle)
        if helper.poll() is None:
            helper.terminate()
            helper.communicate(timeout=5)


def test_receipt_correlation_is_not_liveness_or_authority(identity, tmp_path):
    directory = tmp_path / "receipt"
    Receipt(directory, identity)
    assert inspect(directory, identity)["status"] == "UNKNOWN"
    for field, value in (("task_id", "wrong"), ("parent_id", "wrong"), ("owner_id", "wrong"),
                         ("run_id", "wrong"), ("attempt", 2), ("commit", "f" * 40)):
        with pytest.raises(ValueError, match="correlation"):
            cancel(directory, replace(identity, **{field: value}))
    assert not (directory / "cancel.json").exists()
    assert cancel(directory, identity)["termination"] == "UNKNOWN"


def test_exact_worktree_commit_and_nested_repository(identity, tmp_path):
    with pytest.raises(ValueError, match="commit changed"):
        run_process(replace(identity, commit="f" * 40), tmp_path / "wrong", [sys.executable, "-c", "pass"])
    subprocess.run(["git", "init", "-q", identity.cwd], check=True)
    with pytest.raises(ValueError, match="nested repository"):
        run_process(identity, tmp_path / "nested", [sys.executable, "-c", "pass"])
    with pytest.raises(ValueError, match="canonical"):
        Correlation.parse({**asdict(identity), "cwd": str(tmp_path)})


@pytest.mark.skipif(os.name != "nt", reason="local process execution requires Windows creation-time ownership")
def test_process_revalidates_head_before_publishing_and_keeps_original_evidence(identity, tmp_path):
    def move_head(_receipt):
        subprocess.run(["git", "-C", identity.repo_root, "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty",
                        "-qm", "moved after start"], check=True)

    directory = tmp_path / "changed-head"
    result = run_process(identity, directory, [sys.executable, "-c", "print('finished')"],
                         on_started=move_head)
    assert result["status"] == "UNKNOWN"
    assert result["observed_outcome"] == "SUCCEEDED"
    assert result["checkout_association_at_finish"] == "UNKNOWN"
    assert result["exit_code"] == 0
    assert result["semantic_done"] is False
    assert b"finished" in (directory / "stdout.bin").read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="local process execution requires Windows creation-time ownership")
def test_process_revalidates_root_and_nested_repository_association(identity, tmp_path):
    def add_nested_repository(_receipt):
        subprocess.run(["git", "init", "-q", identity.cwd], check=True)

    result = run_process(identity, tmp_path / "changed-root", [sys.executable, "-c", "pass"],
                         on_started=add_nested_repository)
    assert result["status"] == "UNKNOWN"
    assert result["observed_outcome"] == "SUCCEEDED"
    assert result["checkout_association_at_finish"] == "UNKNOWN"
    assert result["exit_code"] == 0


@pytest.mark.skipif(os.name != "nt", reason="local process execution requires Windows creation-time ownership")
def test_checkout_identity_does_not_claim_dirty_or_untracked_bytes(identity, tmp_path):
    root = Path(identity.repo_root)
    tracked = root / "tracked.txt"
    tracked.write_text("committed bytes")
    subprocess.run(["git", "-C", identity.repo_root, "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", identity.repo_root, "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "tracked file"], check=True)
    identity = replace(identity, commit=subprocess.check_output(
        ["git", "-C", identity.repo_root, "rev-parse", "HEAD"], text=True).strip())
    tracked.write_text("dirty bytes absent from the receipt snapshot")
    (root / "untracked.txt").write_text("untracked bytes absent from the receipt snapshot")

    result = run_process(identity, tmp_path / "dirty-worktree", [sys.executable, "-c", "pass"])
    assert result["status"] == "SUCCEEDED"
    assert result["checkout_association_at_finish"] == "VERIFIED"
    assert result["workspace_bytes"] == "UNKNOWN"
    assert result["semantic_done"] is False


def ci_identity(identity):
    return replace(identity, kind="github-actions", repository="owner/repo", run_id="123")


def ci_run(identity, **changes):
    return {"id": 123, "repository": {"full_name": "owner/repo"}, "head_sha": identity.commit,
            "run_attempt": identity.attempt, "status": "in_progress", "conclusion": None, **changes}


def ci_job(identity, **changes):
    return {"id": 17, "run_id": 123, "head_sha": identity.commit, "run_attempt": identity.attempt,
            "status": "in_progress", "conclusion": None, **changes}


def test_ci_running_terminal_duplicate_late_wrong_attempt(identity):
    identity = ci_identity(identity)
    gate = GitHubRunGate(identity)
    running = ci_run(identity)
    assert gate.accept(running, [ci_job(identity)]) == "CONTINUE"
    assert gate.accept(running, [ci_job(identity)]) == "DUPLICATE"
    for changes in ({"id": 124}, {"head_sha": "f" * 40}, {"repository": {"full_name": "wrong/repo"}}):
        assert gate.accept({**running, **changes}, []) == "REJECTED_CORRELATION"
    assert gate.accept(ci_run(identity, run_attempt=2), []) == "REJECTED_ATTEMPT"
    assert gate.accept(running, [ci_job(identity, run_attempt=2)]) == "REJECTED_JOB_CORRELATION"
    completed = ci_run(identity, status="completed", conclusion="failure")
    assert gate.accept(completed, []) == "RUN_COMPLETED"
    assert gate.accept(completed, []) == "DUPLICATE"
    assert gate.accept({**running, "updated_at": "late"}, []) == "REJECTED_AFTER_TERMINAL"
    # An old attempt success cannot overwrite a new attempt's in-flight observation.
    new = GitHubRunGate(replace(identity, attempt=2))
    assert new.accept(ci_run(identity, status="completed", conclusion="success"), []) == "REJECTED_ATTEMPT"


@pytest.mark.parametrize(("run_changes", "job_changes", "expected"), [
    ({}, {}, "CONTINUE"),
    ({}, {"status": "completed", "conclusion": "failure"}, "JOB_DECISION_EVIDENCE"),
    ({}, {"status": "completed", "conclusion": "timed_out"}, "JOB_DECISION_EVIDENCE"),
    ({}, {"status": "completed", "conclusion": "action_required"}, "JOB_DECISION_EVIDENCE"),
    ({}, {"conclusion": "failure"}, "UNKNOWN"),
    ({"status": "waiting"}, {}, "INTERVENTION_REQUIRED"),
    ({"status": "completed", "conclusion": None}, {}, "UNKNOWN"),
    ({"status": "future-provider-state"}, {}, "UNKNOWN"),
])
def test_ci_meaningful_evidence_early_return(identity, run_changes, job_changes, expected):
    identity = ci_identity(identity)
    assert GitHubRunGate(identity).accept(ci_run(identity, **run_changes), [ci_job(identity, **job_changes)]) == expected


def test_ci_watcher_absorbs_unchanged_output_and_returns_structured_terminal(identity, tmp_path):
    identity = ci_identity(identity)
    snapshots = iter([(ci_run(identity), []), (ci_run(identity), []),
                      (ci_run(identity, status="completed", conclusion="success"), [])])
    result = watch_github(identity, tmp_path / "ci", interval=.001, snapshot=lambda _: next(snapshots))
    assert result["status"] == "RUN_COMPLETED" and result["run_completed"] is True
    assert result["semantic_done"] is False and result["observations"] == 3
    events = [json.loads(line) for line in (tmp_path / "ci" / "events.jsonl").read_text().splitlines()]
    assert [event["disposition"] for event in events] == ["CONTINUE", "DUPLICATE", "RUN_COMPLETED"]


def test_ci_terminal_is_downgraded_if_checkout_association_changes(identity, tmp_path):
    identity = ci_identity(identity)
    completed = ci_run(identity, status="completed", conclusion="success")

    def snapshot(_identity):
        subprocess.run(["git", "-C", identity.repo_root, "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty",
                        "-qm", "moved during CI observation"], check=True)
        return completed, []

    directory = tmp_path / "ci-changed-head"
    result = watch_github(identity, directory, snapshot=snapshot)
    assert result["status"] == "UNKNOWN"
    assert result["observed_outcome"] == "RUN_COMPLETED"
    assert result["run_completed"] is True
    assert result["conclusion"] == "success"
    assert result["checkout_association_at_finish"] == "UNKNOWN"
    event = json.loads((directory / "events.jsonl").read_text().splitlines()[0])
    assert event["disposition"] == "RUN_COMPLETED"


def test_ci_errors_timeout_and_cancel_preserve_unknown(identity, tmp_path):
    identity = ci_identity(identity)
    def fail(_):
        raise OSError("transport unavailable")
    assert watch_github(identity, tmp_path / "error", snapshot=fail)["status"] == "UNKNOWN"
    assert watch_github(identity, tmp_path / "timeout", interval=.2, timeout=.01,
                        snapshot=lambda _: (ci_run(identity), []))["status"] == "TIMED_OUT"
    def stop(_):
        cancel(tmp_path / "cancel-ci", identity)
        return ci_run(identity), []
    result = watch_github(identity, tmp_path / "cancel-ci", snapshot=stop)
    assert result["status"] == "CANCELLED" and result["remote_run_cancelled"] is False


@pytest.mark.skipif(os.name != "nt", reason="local process execution requires Windows creation-time ownership")
def test_cli_real_argv(identity, tmp_path, capsys):
    path = tmp_path / "identity.json"
    path.write_text(json.dumps(asdict(identity)))
    assert main(["run", "--identity", str(path), "--receipt", str(tmp_path / "cli"),
                 "--", sys.executable, "-c", "print('ok')"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"
