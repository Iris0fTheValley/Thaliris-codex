"""Foreground, single-operation observation. No agent, daemon or task authority.

Run with ``python -m thaliris_codex.execution_wait --help``. Receipts are local
evidence, never semantic task completion. Only the command tree created here is controlled.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Callable
import uuid

from . import owned_process


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _write(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".new")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class Correlation:
    task_id: str
    repo_root: str
    cwd: str
    commit: str
    run_id: str
    attempt: int
    parent_id: str
    child_id: str
    owner_id: str
    kind: str
    repository: str = ""

    @classmethod
    def parse(cls, value: dict) -> Correlation:
        result = cls(**value)
        for key, item in asdict(result).items():
            if key not in {"attempt", "repository"} and (not isinstance(item, str) or not item.strip()):
                raise ValueError("invalid correlation: " + key)
        if type(result.attempt) is not int or result.attempt < 1:
            raise ValueError("invalid attempt")
        if result.kind not in {"process", "github-actions"}:
            raise ValueError("unsupported operation kind")
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", result.commit) is None:
            raise ValueError("exact commit required")
        root, cwd = Path(result.repo_root), Path(result.cwd)
        if (not root.is_absolute() or not cwd.is_absolute() or str(root.resolve()) != str(root)
                or str(cwd.resolve()) != str(cwd) or not cwd.is_relative_to(root)):
            raise ValueError("exact canonical repository/cwd required")
        if result.kind == "github-actions" and (
                not isinstance(result.repository, str) or re.fullmatch(r"[\w.-]+/[\w.-]+", result.repository) is None
                or not result.run_id.isdecimal()):
            raise ValueError("exact GitHub repository and numeric run ID required")
        return result

    def verify_checkout(self, expected: dict[str, str] | None = None) -> dict[str, str]:
        def git(*args: str) -> str:
            return subprocess.check_output(["git", "-C", self.cwd, *args], stderr=subprocess.PIPE, text=True).strip()
        root, cwd = Path(self.repo_root).resolve(strict=True), Path(self.cwd).resolve(strict=True)
        if str(root) != self.repo_root or str(cwd) != self.cwd or not cwd.is_relative_to(root):
            raise ValueError("repository/cwd canonical association changed")
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
            raise ValueError("wrong repository/worktree (including nested repository)")
        head = git("rev-parse", "HEAD")
        if head != self.commit:
            raise ValueError("checkout commit changed")
        association = {
            "root": str(root),
            "cwd": str(cwd),
            "head": head,
            "git_dir": str(Path(git("rev-parse", "--absolute-git-dir")).resolve(strict=True)),
            "git_common_dir": str(Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True)),
        }
        if expected is not None and association != expected:
            raise ValueError("checkout worktree association changed")
        return association


class Receipt:
    """One new directory, one foreground writer. Cancellation never kills by PID."""

    def __init__(self, directory: Path, identity: Correlation,
                 checkout_association: dict[str, str] | None = None):
        self.directory, self.identity = directory, identity
        directory.mkdir(parents=True, exist_ok=False)
        self.state = {"version": 1, "correlation": asdict(identity), "status": "RUNNING",
                      "semantic_done": False, "automatic_resume": "UNSUPPORTED", "observations": 0,
                      "checkout_association_at_start": checkout_association or "UNKNOWN",
                      "checkout_association_at_finish": "PENDING", "workspace_bytes": "UNKNOWN"}
        _write(directory / "state.json", self.state)

    def observe(self, event: dict, disposition: str) -> None:
        self.state["observations"] += 1
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(_json({"sequence": self.state["observations"], "event": event,
                                "disposition": disposition}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def cancelled(self) -> bool:
        request = self.directory / "cancel.json"
        if not request.exists():
            return False
        value = json.loads(request.read_text(encoding="utf-8"))
        if value != {"correlation": asdict(self.identity)}:
            raise ValueError("wrong cancellation correlation")
        return True

    def finish(self, status: str, **fields: object) -> dict:
        self.state.update(status=status, **fields)
        _write(self.directory / "state.json", self.state)
        return dict(self.state)


def inspect(directory: Path, identity: Correlation) -> dict:
    state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    if state["correlation"] != asdict(identity):
        raise ValueError("wrong receipt correlation")
    # A durable RUNNING record proves neither that its observer nor process lives.
    if state["status"] == "RUNNING":
        return {**state, "status": "UNKNOWN", "reason": "no terminal receipt; observer/process liveness unverified",
                "recovery": "inspect output files; reconcile the original tool session manually; do not relaunch from PID"}
    return state


def cancel(directory: Path, identity: Correlation) -> dict:
    state = inspect(directory, identity)
    if state["status"] != "UNKNOWN":
        return {"status": "ALREADY_TERMINAL", "receipt": state}
    target = directory / "cancel.json"
    value = {"correlation": asdict(identity)}
    temporary = directory / ("cancel-" + uuid.uuid4().hex + ".new")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)  # Atomic publication without replacing unknown bytes.
        except FileExistsError:
            if json.loads(target.read_text(encoding="utf-8")) != value:
                raise ValueError("wrong cancellation correlation")
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "CANCEL_REQUESTED", "termination": "UNKNOWN"}


def _finish_for_checkout(receipt: Receipt, identity: Correlation, expected: dict[str, str],
                         status: str, **fields: object) -> dict:
    try:
        identity.verify_checkout(expected)
    except Exception as exc:
        return receipt.finish("UNKNOWN", observed_outcome=status,
                              checkout_association_at_finish="UNKNOWN",
                              checkout_verification_error=type(exc).__name__ + ": " + str(exc), **fields)
    return receipt.finish(status, checkout_association_at_finish="VERIFIED",
                          workspace_bytes="UNKNOWN", **fields)


def run_process(identity: Correlation, directory: Path, command: list[str], *,
                timeout: float | None = None, stream: bool = False,
                on_started: Callable[[Receipt], None] | None = None) -> dict:
    if identity.kind != "process" or not command or any(not isinstance(arg, str) for arg in command):
        raise ValueError("process argv required")
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive")
    checkout_association = identity.verify_checkout()
    receipt = Receipt(directory, identity, checkout_association)
    started = time.monotonic()
    process = None
    readers: list[threading.Thread] = []
    handles = []
    output_errors: list[str] = []
    status, error = "UNKNOWN", None
    try:
        # No shell, inherited stdin, PID lookup, detached observer or sandbox override.
        process = owned_process.launch(command, identity.cwd)
        receipt.state["pid"] = process.pid  # Diagnostic only; never a resume/kill capability.
        receipt.state["process_ownership"] = process.ownership
        _write(directory / "state.json", receipt.state)
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            target = (directory / (name + ".bin")).open("xb", buffering=0)
            handles.append(target)
            def drain(pipe=pipe, target=target):
                try:
                    while chunk := os.read(pipe.fileno(), 65536):
                        target.write(chunk)
                        if stream:
                            sys.stderr.buffer.write(chunk)
                            sys.stderr.buffer.flush()
                except (OSError, ValueError) as exc:
                    output_errors.append(type(exc).__name__)
                finally:
                    pipe.close()
            reader = threading.Thread(target=drain, daemon=True)
            readers.append(reader)
            reader.start()
        if on_started:
            on_started(receipt)
        # These are local cancellation checks, never model wakeups or process polling calls.
        while True:
            try:
                exit_code = process.wait(timeout=0.1)
                status = "SUCCEEDED" if exit_code == 0 else "FAILED"
                break
            except subprocess.TimeoutExpired:
                if receipt.cancelled():
                    status = "CANCELLED"
                    break
                if timeout is not None and time.monotonic() - started >= timeout:
                    status = "TIMED_OUT"
                    break
    except KeyboardInterrupt:
        status = "INTERRUPTED"
    except owned_process.TreeUnavailable as exc:
        status, error = "UNKNOWN", str(exc)
    except Exception as exc:
        status, error = "ERROR", type(exc).__name__ + ": " + str(exc)
    finally:
        descendant_termination = "NOT_STARTED" if process is None else "UNKNOWN"
        if process is not None:
            try:
                descendant_termination = process.close_tree()
            except Exception as exc:
                status, error = "UNKNOWN", "tree cleanup: " + type(exc).__name__ + ": " + str(exc)
        for reader in readers:
            reader.join(timeout=0.2)
        readers_finished = all(not reader.is_alive() for reader in readers)
        output_complete = readers_finished and not output_errors
        if readers_finished:
            for handle in handles:
                handle.close()
    interruption_outcome = status if status in {"CANCELLED", "TIMED_OUT", "INTERRUPTED"} else None
    if interruption_outcome and descendant_termination == "UNKNOWN":
        status, error = "UNKNOWN", "owned group stopped; whole-tree termination unverified"
    return _finish_for_checkout(receipt, identity, checkout_association, status,
                                exit_code=process.returncode if process else None,
                                error=error, elapsed_seconds=time.monotonic() - started,
                                interruption_outcome=interruption_outcome,
                                output_complete=output_complete, output_errors=output_errors,
                                descendant_termination=descendant_termination,
                                output_files=[str(directory / (name + ".bin")) for name in ("stdout", "stderr")])


class GitHubRunGate:
    """Classify authenticated REST response shapes, never words in logs."""

    def __init__(self, identity: Correlation):
        if identity.kind != "github-actions":
            raise ValueError("GitHub Actions identity required")
        self.identity = identity
        self.seen: set[str] = set()
        self.terminal = False

    def accept(self, run: dict, jobs: list[dict]) -> str:
        expected = self.identity
        if (str(run.get("id")) != expected.run_id or run.get("head_sha") != expected.commit
                or run.get("repository", {}).get("full_name") != expected.repository):
            return "REJECTED_CORRELATION"
        if run.get("run_attempt") != expected.attempt:
            return "REJECTED_ATTEMPT"
        # Only this selected attempt's jobs endpoint is used by the transport.
        for job in jobs:
            if (str(job.get("run_id")) != expected.run_id or job.get("head_sha") != expected.commit
                    or job.get("run_attempt") != expected.attempt):
                return "REJECTED_JOB_CORRELATION"
        fingerprint = hashlib.sha256(_json([run, jobs]).encode()).hexdigest()
        if fingerprint in self.seen:
            return "DUPLICATE"
        self.seen.add(fingerprint)
        if self.terminal:
            return "REJECTED_AFTER_TERMINAL"
        status, conclusion = run.get("status"), run.get("conclusion")
        if status == "completed":
            if not isinstance(conclusion, str) or not conclusion:
                return "UNKNOWN"
            self.terminal = True
            return "RUN_COMPLETED"
        if conclusion == "action_required" or status == "waiting":
            return "INTERVENTION_REQUIRED"
        if any(job.get("conclusion") in {"failure", "timed_out", "action_required"}
               and job.get("status") == "completed" for job in jobs):
            return "JOB_DECISION_EVIDENCE"
        if any(job.get("conclusion") is not None and job.get("status") != "completed" for job in jobs):
            return "UNKNOWN"
        if status not in {"queued", "in_progress", "requested", "pending"}:
            return "UNKNOWN"
        return "CONTINUE"


def github_snapshot(identity: Correlation) -> tuple[dict, list[dict]]:
    def request(path: str) -> dict:
        result = subprocess.run(["gh", "api", "--hostname", "github.com", path], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=30, check=False)
        if result.returncode:
            # Avoid echoing authentication diagnostics, URLs or personal configuration.
            raise RuntimeError("GitHub API request failed: exit " + str(result.returncode))
        return json.loads(result.stdout)
    base = f"repos/{identity.repository}/actions/runs/{identity.run_id}"
    run = request(base)
    if run.get("status") == "completed":
        return run, []  # Full-run terminal evidence survives unavailable job details.
    jobs: list[dict] = []
    page = 1
    while True:
        value = request(f"{base}/attempts/{identity.attempt}/jobs?per_page=100&page={page}")
        rows = value["jobs"]
        jobs.extend(rows)
        if len(rows) < 100:
            break
        page += 1
    return run, jobs


def watch_github(identity: Correlation, directory: Path, *, interval: float = 30,
                 snapshot=github_snapshot, timeout: float | None = None) -> dict:
    if interval <= 0 or timeout is not None and timeout <= 0:
        raise ValueError("positive interval/timeout required")
    checkout_association = identity.verify_checkout()
    receipt, gate = Receipt(directory, identity, checkout_association), GitHubRunGate(identity)
    started = time.monotonic()
    try:
        while True:
            if receipt.cancelled():
                return _finish_for_checkout(receipt, identity, checkout_association,
                                            "CANCELLED", remote_run_cancelled=False)
            run, jobs = snapshot(identity)
            disposition = gate.accept(run, jobs)
            receipt.observe({"run": run, "jobs": jobs}, disposition)
            if disposition not in {"CONTINUE", "DUPLICATE"}:
                return _finish_for_checkout(receipt, identity, checkout_association, disposition,
                                            run_completed=disposition == "RUN_COMPLETED",
                                            conclusion=run.get("conclusion"),
                                            elapsed_seconds=time.monotonic() - started)
            end = time.monotonic() + interval
            while time.monotonic() < end:
                if receipt.cancelled():
                    return _finish_for_checkout(receipt, identity, checkout_association,
                                                "CANCELLED", remote_run_cancelled=False)
                if timeout is not None and time.monotonic() - started >= timeout:
                    return _finish_for_checkout(receipt, identity, checkout_association,
                                                "TIMED_OUT", remote_run_cancelled=False)
                threading.Event().wait(min(0.1, end - time.monotonic()))
    except KeyboardInterrupt:
        return _finish_for_checkout(receipt, identity, checkout_association,
                                    "INTERRUPTED", remote_run_cancelled=False)
    except Exception as exc:
        return _finish_for_checkout(
            receipt, identity, checkout_association, "UNKNOWN",
            error=type(exc).__name__ + ": " + str(exc),
            recovery="inspect receipt; retry observation explicitly in a new receipt directory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "github", "inspect", "cancel"))
    parser.add_argument("--identity", required=True, type=Path, help="UTF-8 correlation JSON; selection is not authority")
    parser.add_argument("--receipt", required=True, type=Path, help="new directory for run/github; existing for inspect/cancel")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--stream", action="store_true", help="show owned stdout/stderr on stderr; may cause tool output yields")
    selected = list(sys.argv[1:] if argv is None else argv)
    boundary = selected.index("--") if "--" in selected else len(selected)
    command = selected[boundary + 1:]
    args = parser.parse_args(selected[:boundary])
    try:
        identity = Correlation.parse(json.loads(args.identity.read_text(encoding="utf-8-sig")))
        if args.action == "run":
            result = run_process(identity, args.receipt, command, timeout=args.timeout, stream=args.stream)
        elif args.action == "github":
            result = watch_github(identity, args.receipt, interval=args.interval, timeout=args.timeout)
        else:
            result = {"inspect": inspect, "cancel": cancel}[args.action](args.receipt, identity)
        print(_json(result))
        return 0 if result["status"] in {"SUCCEEDED", "RUN_COMPLETED", "CANCEL_REQUESTED", "ALREADY_TERMINAL"} else 1
    except (ValueError, OSError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(_json({"status": "ERROR", "error": type(exc).__name__ + ": " + str(exc), "semantic_done": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
