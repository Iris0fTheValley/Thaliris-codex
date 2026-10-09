"""Recoverable disk generations, bound to the original maintenance intent.

Native hook trust is a separate, idempotent post-commit step. Until that step
finishes, the durable journal fences normal runtime admission. Recovery never
accepts a new candidate's rendering as evidence about the preceding generation.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from contextlib import contextmanager

NAME = "thaliris-host-transition.json"
FORMAT = "thaliris-host-transition-v1"
LOCK_NAME = "thaliris-host-maintenance.lock"
LOCK_BYTES = b"thaliris-host-maintenance-lock-v1\n"


def _publish(path, contents):
    """Publish complete durable metadata without replacing existing evidence."""
    import os
    import tempfile
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".host-transition-", delete=False) as output:
            temporary = Path(output.name)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def locked(home):
    """OS-released lock; an interrupted process never leaves a stale grant."""
    import os
    from .host_maintenance import safe
    path = home / LOCK_NAME
    safe(path)
    home.mkdir(parents=True, exist_ok=True)
    try:
        _publish(path, LOCK_BYTES)
    except FileExistsError:
        pass
    if path.read_bytes() != LOCK_BYTES:
        raise ValueError("unowned Host maintenance lock file; preserve for review")
    with path.open("r+b") as stream:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _encode(values):
    return {name: base64.b64encode(value).decode("ascii") if value is not None else None
            for name, value in values.items()}


def _decode(values):
    if not isinstance(values, dict):
        raise ValueError("invalid Host transition snapshot")
    return {name: base64.b64decode(value, validate=True) if isinstance(value, str)
            else None if value is None else _invalid() for name, value in values.items()}


def _invalid():
    raise ValueError("invalid Host transition bytes")


def pending(home: Path) -> bool:
    from .host_maintenance import safe
    path = home / NAME
    safe(path)
    return path.exists()


def _write(home, record):
    from .codex_adapter import _atomic_host_write
    _atomic_host_write(home / NAME, (json.dumps(record, sort_keys=True) + "\n").encode())


def _observe(home, names, *, targets=None):
    from .host_maintenance import safe
    result = {}
    for name in names:
        path = Path(targets[name]) if targets and name in targets else home / name
        safe(path)
        result[name] = path.read_bytes() if path.exists() else None
    return result


def _apply(home, values, *, rollback=False, targets=None):
    from .codex_adapter import _atomic_host_write
    from .host_maintenance import RECEIPT_NAME, safe
    from . import lifecycle, host_preflight
    guards = (host_preflight.NAME, lifecycle.HOST_RUN_SCRIPT_NAME, lifecycle.HOST_HOOK_SCRIPT_NAME)
    # Establish guarded entrypoints before changing definitions, including an
    # upgrade from a pre-journal generation. On rollback restore all definitions
    # before restoring its old entrypoints. The journal commits only afterward.
    def order(name):
        if name in guards:
            return (2 if rollback else 0, guards.index(name), name)
        return (1, 1 if name == RECEIPT_NAME else 0, name)
    for name in sorted(values, key=order):
        path = Path(targets[name]) if targets and name in targets else home / name
        safe(path)
        value = values[name]
        if (path.read_bytes() if path.exists() else None) == value:
            continue
        if value is None:
            path.unlink()
        else:
            _atomic_host_write(path, value)


def _profile_name(name):
    # Only receipt-authorized native profile files can widen a candidate's set.
    return isinstance(name, str) and name.startswith("agents/") and name.endswith(".toml") and (
        len(name.split("/")) == 2 and name.split("/")[1] not in {".toml", "..toml"}
        and "\\" not in name and ":" not in name)


def load(home, intent):
    from . import host_maintenance as maintenance, runtime_identity, lifecycle, host_preflight, roles, mode_hint_config
    path = home / NAME
    maintenance.safe(path)
    record = json.loads(path.read_bytes())
    if not isinstance(record, dict) or record.get("format") != FORMAT or record.get("phase") not in {"PREPARED", "COMMITTED"}:
        raise ValueError("invalid Host transition journal; preserve for review")
    if record.get("contract_sha256") != intent["contract_sha256"] or record.get("operation") != intent["operation"]:
        raise ValueError("HOST_TRANSITION_PENDING: replay the original maintenance contract")
    if "executor_runtime" in record:
        _, executor_runtime = maintenance.selected_runtime(intent["executor"])
        if base64.b64decode(record["executor_runtime"], validate=True) != executor_runtime:
            raise ValueError("Host transition executor differs from original approval")
    finish = record.get("finish")
    if not isinstance(finish, dict) or not isinstance(finish.get("changed_files"), list) or any(
            not isinstance(name, str) for name in finish["changed_files"]):
        raise ValueError("invalid Host transition finalization record; preserve for review")
    if intent["operation"] == "codex-uninstall" and (
            not isinstance(finish.get("keys"), list) or any(not isinstance(key, str) or not key for key in finish["keys"]) or
            type(finish.get("inert")) is not bool or not isinstance(finish.get("preserved"), list) or
            any(not isinstance(name, str) for name in finish["preserved"])):
        raise ValueError("invalid uninstall transition finalization record; preserve for review")
    before, after = _decode(record.get("before")), _decode(record.get("after"))
    targets = maintenance.instruction_targets(intent, home)
    if record.get("instruction_targets", {}) != targets:
        raise ValueError("Host transition instruction targets differ from original approval")
    if set(before) != set(after):
        raise ValueError("invalid Host transition surface")
    prior = before.get(runtime_identity.MANIFEST_NAME)
    if (maintenance.digest(prior) if prior is not None else "ABSENT") != intent.get("installed_runtime_sha256"):
        raise ValueError("Host transition prior identity differs from original approval")
    if prior is not None:
        prior_record = runtime_identity.validate_manifest_record(prior)
        runtime_identity.validate_existing_manifest(
            prior, Path(prior_record["executable"]), maintenance.digest(prior)
        )
    # Validate historical receipt structure independently of effective files.
    old_receipt = before.get(maintenance.RECEIPT_NAME)
    ownership = maintenance.validate_ownership(old_receipt, prior, intent)
    mode_hint_config.validate(ownership.get(mode_hint_config.RECORD_KEY), home)
    if "mode_hint_record" in finish:
        mode_hint_config.validate(finish["mode_hint_record"], home)
    if intent["operation"] == "codex-install":
        executable, approved = maintenance.selected_runtime(intent["candidate"])
        if after.get(runtime_identity.MANIFEST_NAME) != approved or finish.get("candidate") != str(executable) or (
                finish.get("runtime") != approved.decode() or finish.get("sha") != json.loads(approved)["executable_sha256"] or
                finish.get("execution_constraint") != intent.get("execution_constraint")):
            raise ValueError("Host transition candidate differs from original approval")
        next_receipt = maintenance.validate_ownership(after.get(maintenance.RECEIPT_NAME), approved, intent)
        mode_hint_config.validate(next_receipt.get(mode_hint_config.RECORD_KEY), home)
        if "mode_hint_record" in finish and finish["mode_hint_record"] != next_receipt.get(mode_hint_config.RECORD_KEY):
            raise ValueError("Host transition native mode hint differs from receipt")
        if "mode_hint_status" in finish and (not isinstance(finish["mode_hint_status"], dict) or
                finish["mode_hint_status"].get("status") not in {"PLANNED", "MANAGED", "USER_CHANGED_PRESERVED",
                    "USER_EMPTY_PRESERVED", "USER_CUSTOM_PRESERVED", "VERSION_SUPPORT_UNKNOWN", "STRUCTURE_UNSUPPORTED_PRESERVED"}):
            raise ValueError("invalid Host transition native mode hint status")
        if finish.get("mode_hint_status", {}).get("status") == "PLANNED" and ownership.get(mode_hint_config.RECORD_KEY) is not None:
            raise ValueError("Host transition cannot reacquire a managed native mode hint")
        if finish.get("mode_hint_status", {}).get("status") in {"PLANNED", "MANAGED"} and finish.get("mode_hint_record") is None:
            raise ValueError("Host transition native mode hint lacks ownership evidence")
        if "mode_hint_phase" in finish and (finish["mode_hint_phase"] not in {"ATTEMPTING", "APPLIED"} or
                finish.get("mode_hint_status", {}).get("status") != "PLANNED"):
            raise ValueError("invalid Host transition native mode hint attempt")
        if finish.get("mode_hint_phase") == "APPLIED" and (not isinstance(finish.get("mode_hint_result"), dict) or
                type(finish["mode_hint_result"].get("changed")) is not bool):
            raise ValueError("invalid Host transition native mode hint result")
        migrations = maintenance.migrated_instructions(intent, home, before, executable, finish["sha"])
        if any(after.get(name) != value for name, value in migrations.items()):
            raise ValueError("Host transition instructions differ from original approval")
        for name, identity in next_receipt.get("owned_bytes", {}).items():
            contents = (maintenance._global_owned_bytes(after.get("AGENTS.md", b""))
                        if name == "AGENTS.md#global" else after.get(name))
            if contents is None or maintenance.digest(contents) != identity:
                raise ValueError("Host transition receipt differs from effective planned bytes")
        hooks = json.loads(after.get("hooks.json", b"{}"))
        maintenance._require_only_owned_host_hooks(hooks, next_receipt, after.get("hooks.json", b"{}"), home)
        for event, handlers in next_receipt.get("hook_handlers", {}).items():
            if any(handler not in hooks.get("hooks", {}).get(event, []) for handler in handlers):
                raise ValueError("Host transition receipt differs from effective planned hooks")
    elif after.get(runtime_identity.MANIFEST_NAME) is not None:
        raise ValueError("uninstall transition retains an active runtime")
    elif "mode_hint_record" in finish and finish["mode_hint_record"] != ownership.get(mode_hint_config.RECORD_KEY):
        raise ValueError("uninstall transition native mode hint differs from prior receipt")
    allowed = {runtime_identity.MANIFEST_NAME, maintenance.RECEIPT_NAME, "AGENTS.md", "hooks.json",
               lifecycle.HOST_HOOK_SCRIPT_NAME, lifecycle.HOST_RUN_SCRIPT_NAME, host_preflight.NAME}
    allowed.update("agents/" + name for name in roles.agent_profiles())
    allowed.update(name for name in ownership.get("owned_bytes", {}) if _profile_name(name))
    allowed.update(targets)
    if set(before) - allowed:
        raise ValueError("Host transition contains an unapproved surface")
    observed = _observe(home, before, targets=targets)
    for name, contents in observed.items():
        accepted = (after[name],) if record["phase"] == "COMMITTED" else (before[name], after[name])
        if contents not in accepted:
            raise ValueError(f"Host transition input changed: {name}; preserve for review")
    return record, before, after


def resume(home, intent, finalize):
    """Roll PREPARED back before replanning, or return COMMITTED for trust finish."""
    if not pending(home):
        return None
    with locked(home):
        # Another caller may have completed while this caller observed pending.
        if not pending(home):
            return None
        record, before, after = load(home, intent)
        if record["phase"] == "COMMITTED":
            return finalize(home, record)
        targets = record.get("instruction_targets", {})
        _apply(home, before, rollback=True, targets=targets)
        if _observe(home, before, targets=targets) != before:
            raise ValueError("Host transition rollback verification failed")
        (home / NAME).unlink()
    return None


def begin(home, intent, before, writes, deletes, finish):
    from .host_maintenance import instruction_targets
    targets = instruction_targets(intent, home)
    names = set(before) | set(writes) | set(deletes)
    previous = {name: before.get(name) for name in names}
    after = previous | writes | {name: None for name in deletes}
    if _observe(home, names, targets=targets) != previous:
        raise ValueError("maintenance input changed before transition preparation")
    record = {"format": FORMAT, "phase": "PREPARED", "operation": intent["operation"],
              "contract_sha256": intent["contract_sha256"], "before": _encode(previous),
              "after": _encode(after), "finish": finish}
    if targets:
        record["instruction_targets"] = targets
    from .host_maintenance import selected_runtime
    _, executor_runtime = selected_runtime(intent["executor"])
    record["executor_runtime"] = base64.b64encode(executor_runtime).decode("ascii")
    # Exclusive creation prevents silently replacing an unfinished generation.
    from .host_maintenance import safe
    safe(home / NAME)
    home.mkdir(parents=True, exist_ok=True)
    committed = record | {"phase": "COMMITTED"}
    archive = home / archive_name(committed)
    safe(archive)
    if archive.exists() and archive.read_bytes() != (json.dumps(committed, sort_keys=True) + "\n").encode():
        raise ValueError("Host generation archive conflict; preserve for review")
    # Publish complete bytes exclusively. An interrupted preparation cannot
    # leave a truncated recovery record in front of otherwise unchanged files.
    _publish(home / NAME, (json.dumps(record, sort_keys=True) + "\n").encode())
    _apply(home, after, targets=targets)
    if _observe(home, names, targets=targets) != after:
        raise ValueError("Host transition generation verification failed")
    record["phase"] = "COMMITTED"
    _write(home, record)
    return record


def archive_name(record):
    import hashlib
    return "thaliris-host-generations/" + hashlib.sha256(
        (json.dumps(record, sort_keys=True) + "\n").encode()).hexdigest() + ".json"


def complete(home, record):
    """Retain exact authorized before/after generations outside the active path."""
    from . import codex_adapter, host_maintenance, runtime_identity
    after = _decode(record["after"])
    if _observe(home, after, targets=record.get("instruction_targets", {})) != after:
        raise ValueError("Host generation changed during finalization; preserve for review")
    manifest = after.get(runtime_identity.MANIFEST_NAME)
    if manifest is not None:
        selected = runtime_identity.validate_manifest_record(manifest)
        runtime_identity.validate_manifest(manifest, Path(selected["executable"]), host_maintenance.digest(manifest))
    path = home / archive_name(record)
    host_maintenance.safe(path)
    contents = (json.dumps(record, sort_keys=True) + "\n").encode()
    if path.exists() and path.read_bytes() != contents:
        raise ValueError("Host generation archive conflict; preserve for review")
    if not path.exists():
        codex_adapter._atomic_host_write(path, contents)
    (home / NAME).unlink()
