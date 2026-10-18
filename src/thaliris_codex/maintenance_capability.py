"""Single-operation Hook observations, not human or Controller authentication.

The model selects the current user's instruction. The Hook checks mechanical
scope and known restrictions. Shared OS records cannot authenticate an otherwise
indistinguishable actor; missing native identity remains UNKNOWN.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

from . import host_maintenance, runtime_identity

FORMAT = "thaliris-maintenance-capability-v1"
TTL_NS = 10 * 60 * 1_000_000_000
ACTIONS = {"install", "update", "repair", "uninstall"}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def directory() -> Path:
    return Path.home() / ".thaliris" / "host-maintenance"


def _safe(path: Path) -> Path:
    path = path.absolute()
    host_maintenance.safe(path)
    return path


def _base(home: Path) -> Path:
    base = directory() / digest(os.path.normcase(str(home.absolute())).encode())
    if any(runtime_identity._is_link(p) for p in (base, *base.parents)):
        raise ValueError("unsafe maintenance observation directory")
    return base


@contextmanager
def _lock(home: Path):
    # Fail closed on contention or an interrupted owner. No stale-lock guessing.
    base = _base(home)
    base.mkdir(parents=True, exist_ok=True)
    path = base / "operation.lock"
    stream = path.open("xb")
    try:
        yield base
    finally:
        stream.close()
        path.unlink()


def _read(path: Path) -> dict:
    value = json.loads(_safe(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("invalid maintenance observation")
    return value


def _write(path: Path, value: dict) -> None:
    _safe(path)
    temporary = path.with_name(path.name + "." + secrets.token_hex(12))
    with temporary.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def restrictions(payload: dict) -> None:
    if (any(payload.get(key) is not None for key in
            ("agent_id", "agentId", "agent_type", "agentType", "agent_role", "agentRole",
             "parent_agent_id", "parentAgentId", "parent_agent_type")) or
            any(payload.get(key) is not None and payload.get(key) is not False for key in
                ("readonly", "fenced", "abandoned", "delegated", "is_subagent"))):
        raise ValueError("HOST_MAINTENANCE_ACTOR_DENIED")


def compatibility() -> dict:
    from . import lifecycle
    return {"hook_abi": lifecycle.MANAGED_HOOK_ABI,
            "hook_spec": lifecycle.managed_hook_spec_hash(),
            "protocol": lifecycle.CODEX_ADAPTER_PROTOCOL_VERSION}


def observe_prompt(home: Path, payload: dict, hook_abi: str | None) -> None:
    """A failed new observation must not leave the previous prompt usable."""
    try:
        _observe_prompt(home, payload, hook_abi)
    except (OSError, ValueError, TypeError, KeyError):
        session = payload.get("session_id")
        if isinstance(session, str) and session:
            base = _base(home)
            base.mkdir(parents=True, exist_ok=True)
            path = base / ("prompt-" + digest(session.encode()) + ".invalid")
            try:
                with path.open("xb"):
                    pass
            except FileExistsError:
                pass
        raise


def _observe_prompt(home: Path, payload: dict, hook_abi: str | None) -> None:
    restrictions(payload)
    session, prompt = payload.get("session_id"), payload.get("prompt")
    if not isinstance(session, str) or not session or not isinstance(prompt, str):
        raise ValueError("maintenance prompt observation unavailable")
    if hook_abi != compatibility()["hook_abi"]:
        raise ValueError("maintenance Hook ABI unavailable")
    session_hash = digest(session.encode())
    with _lock(home) as base:
        path = base / ("prompt-" + session_hash + ".json")
        previous = _read(path) if path.exists() else None
        if previous is not None and (previous.get("format") != FORMAT or
                type(previous.get("epoch")) is not int or previous["epoch"] < 1):
            raise ValueError("invalid previous maintenance prompt observation")
        _write(path, {"format": FORMAT, "session": session_hash,
            "home": str(home.absolute()), "epoch": previous["epoch"] + 1 if previous else 1,
            "prompt_sha256": digest(prompt.encode()), "observed_at_ns": time.time_ns(),
            "native_turn": digest(payload["turn_id"].encode()) if isinstance(payload.get("turn_id"), str) else None,
            **compatibility()})
        (base / ("prompt-" + session_hash + ".invalid")).unlink(missing_ok=True)


def _prompt(base: Path, home: Path, session_hash: str) -> dict:
    if not isinstance(session_hash, str) or re.fullmatch(r"[0-9a-f]{64}", session_hash) is None:
        raise ValueError("invalid maintenance session observation")
    if (base / ("prompt-" + session_hash + ".invalid")).exists():
        raise ValueError("latest maintenance prompt observation is unavailable")
    value = _read(base / ("prompt-" + session_hash + ".json"))
    if (value.get("format") != FORMAT or value.get("session") != session_hash or
            value.get("home") != str(home.absolute()) or type(value.get("epoch")) is not int or
            value["epoch"] < 1 or not re.fullmatch(r"[0-9a-f]{64}", value.get("prompt_sha256", "")) or
            any(value.get(key) != item for key, item in compatibility().items()) or
            type(value.get("observed_at_ns")) is not int or
            not 0 <= time.time_ns() - value["observed_at_ns"] <= TTL_NS):
        raise ValueError("current maintenance prompt observation unavailable")
    return value


def scope(args) -> dict:
    if args.action not in ACTIONS or not args.human_instruction.strip() or not args.current_user_intent:
        raise ValueError("select the actual current user maintenance intent")
    if not args.manifest or not re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256 or ""):
        raise ValueError("maintenance requires an externally selected release digest")
    from . import runtime_setup
    home = args.home.absolute()
    _safe(home / host_maintenance.RECEIPT_NAME)
    resume_sha = None
    if args.resume:
        resume_sha = digest(_safe(args.resume.absolute()).read_bytes())
    return {"action": args.action, "home": str(home), "project": str(args.project.absolute()),
            "manifest": args.manifest if args.manifest.startswith("https://") else str(Path(args.manifest).absolute()),
            "manifest_sha256": args.manifest_sha256,
            "cache": str(args.cache.absolute() if args.cache else runtime_setup.default_runtime_root()),
            "artifacts": str(args.artifacts.absolute()) if args.artifacts else None,
            "resume": str(args.resume.absolute()) if args.resume else None, "resume_sha256": resume_sha,
            "refresh_model_catalog": args.refresh_model_catalog,
            "instruction_sha256": digest(args.human_instruction.encode())}


def installed_identity(home: Path) -> str:
    raw = host_maintenance._installed(home)
    return digest(raw) if raw is not None else "ABSENT"


def updater_identity(home: Path) -> dict:
    """Use the existing trusted installed runtime, never self-hash unknown code."""
    raw = host_maintenance._installed(home)
    if raw is None:
        raise ValueError("installed updater unavailable; use separately trusted bootstrap")
    receipt = host_maintenance.ownership(home, raw, {})
    manifest = json.loads(raw)
    if Path(__file__).resolve().parent != Path(manifest["package_dir"]).resolve(strict=True):
        raise ValueError("maintenance verifier origin differs from installed runtime")
    selected = {"executable": manifest["executable"], "runtime_sha256": digest(raw),
                "source_pin": receipt["source_pin"]}
    if receipt.get("format") == host_maintenance.RELEASE_RECEIPT_FORMAT:
        selected["release_binding"] = receipt["release_binding"]
    executable, _ = host_maintenance.selected_runtime(selected)
    interpreter = executable.parent / ("python.exe" if os.name == "nt" else "python")
    if interpreter.resolve(strict=True) != Path(sys.executable).resolve(strict=True):
        raise ValueError("Hook updater differs from installed runtime")
    return {"python": str(interpreter), "console": str(executable.parent /
        ("thaliris-release.cmd" if os.name == "nt" else "thaliris-release")), "runtime_sha256": digest(raw)}


def check_fences(root: Path, session_hash: str, task_id: str | None) -> None:
    from . import lifecycle, task_authority
    from thaliris import core
    previous = core.selected_task(root)
    try:
        core.select_task(root, task_id)
        checked = task_authority.check(root)
        # Core check returns None for a retired task. Its deny-only fences and
        # abandonment still matter; retirement never restores a known actor.
        authority = task_authority.read(root) or checked
        if (authority is not None and (authority.get("status") == "ABANDONED" or
                session_hash in authority.get("fenced_sessions", [])) or
                lifecycle._session_fenced(root, session_hash)):
            raise ValueError("maintenance session is fenced or abandoned")
    finally:
        core.select_task(root, previous)


def issue(home: Path, payload: dict, request: dict, updater: dict, hook_abi: str | None,
          *, root: Path, task_id: str | None) -> str:
    restrictions(payload)
    session = payload.get("session_id")
    if not isinstance(session, str) or not session or hook_abi != compatibility()["hook_abi"]:
        raise ValueError("current maintenance session unavailable")
    session_hash = digest(session.encode())
    check_fences(root, session_hash, task_id)
    token = "m1." + session_hash + "." + secrets.token_hex(32)
    with _lock(home) as base:
        prompt = _prompt(base, home, session_hash)
        record = {"format": FORMAT, "scope": request, "updater": updater,
            "source_root": str(root.absolute()), "task_id": task_id,
            "session": session_hash, "prompt_epoch": prompt["epoch"],
            "source_prompt_sha256": prompt["prompt_sha256"],
            "installed_runtime_sha256": installed_identity(home),
            "created_at_ns": time.time_ns(), "state": "ISSUED", **compatibility(),
            "provenance": "MODEL_SELECTED_CURRENT_USER_INSTRUCTION", "host_actor_assurance": "UNKNOWN"}
        _write(base / (digest(token.encode()) + ".json"), record)
    return token


def consume(token: str, session_hash: str, request: dict, updater: dict) -> dict:
    if not isinstance(token, str) or not re.fullmatch(r"m1\.[0-9a-f]{64}\.[0-9a-f]{64}", token):
        raise ValueError("maintenance capability required")
    home = Path(request["home"])
    with _lock(home) as base:
        path = base / (digest(token.encode()) + ".json")
        record = _read(path)
        prompt = _prompt(base, home, session_hash)
        if (record.get("format") != FORMAT or record.get("state") != "ISSUED" or
                record.get("scope") != request or record.get("updater") != updater or
                record.get("session") != session_hash or token.split(".")[1] != session_hash or
                record.get("prompt_epoch") != prompt["epoch"] or
                record.get("source_prompt_sha256") != prompt["prompt_sha256"] or
                any(record.get(key) != value for key, value in compatibility().items()) or
                type(record.get("created_at_ns")) is not int or
                not 0 <= time.time_ns() - record["created_at_ns"] <= TTL_NS or
                record.get("installed_runtime_sha256") != installed_identity(home)):
            raise ValueError("maintenance capability scope, freshness or replay mismatch")
        check_fences(Path(record["source_root"]), session_hash, record["task_id"])
        record["state"] = "CONSUMED"
        _write(path, record)  # durable tombstone; concurrent consumers cannot reuse
    return record


def check_dispatch(record: dict, request: dict) -> None:
    """Recheck freshness before mutation; a later prompt needs a new operation."""
    home = Path(request["home"])
    with _lock(home) as base:
        prompt = _prompt(base, home, record["session"])
        if (record["scope"] != request or record["prompt_epoch"] != prompt["epoch"] or
                record["installed_runtime_sha256"] != installed_identity(home)):
            raise ValueError("maintenance intent changed before dispatch")
        if request["resume"] and digest(_safe(Path(request["resume"])).read_bytes()) != request["resume_sha256"]:
            raise ValueError("original resume contract changed before dispatch")
        if updater_identity(home) != record["updater"]:
            raise ValueError("approved updater changed before dispatch")
        check_fences(Path(record["source_root"]), record["session"], record["task_id"])
        # Runtime probes above can take time. A prompt event that could not
        # acquire this lock leaves an invalid marker, which must veto dispatch.
        if _prompt(base, home, record["session"])["epoch"] != record["prompt_epoch"]:
            raise ValueError("maintenance prompt changed during dispatch validation")


def standalone_allowed(home: Path) -> None:
    # Explicit baseline governance only, never a missing-token fallback.
    from . import lifecycle
    if any((home / name).exists() for name in
           (host_maintenance.RECEIPT_NAME, runtime_identity.MANIFEST_NAME, lifecycle.HOST_HOOK_SCRIPT_NAME)):
        raise ValueError("integrated maintenance requires a current Hook capability or exact contract")
