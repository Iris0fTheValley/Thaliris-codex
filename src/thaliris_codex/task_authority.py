"""Codex compatibility facade for Core-owned external task authority.

Codex chooses its security paths, session facts, lifecycle snapshots and fences.
Core stores selected intent and restores the original protected bytes. Neither
layer proves human authorship or universal native Root identity.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import threading

from thaliris import authority, core
from thaliris.authority import MODES, digest

SECURITY_PATHS = (".context/config.json", ".codex/thaliris.json", ".codex/hooks.json", ".codex/config.toml")
_held_task_locks = threading.local()
# Adapter-owned anchor fields and the value an anchor written before the field
# existed implies. Reads tolerate their absence so an older anchor loads; the
# next checked capture persists them. An absent lifecycle digest still fails
# closed when a ledger exists that the anchor never recorded.
ADAPTER_FIELD_DEFAULTS = {"fenced_sessions": (), "fenced_agents": (), "lifecycle_sha256": "ABSENT"}


class ExecutionConstraintUnsatisfied(ValueError):
    """The frozen execution constraint is unknown or the installation leaves it.

    Managed control is refused; task-abandon and task-close stay available
    because they dispatch no native work under the constraint.
    """


def _with_adapter_defaults(record: dict | None) -> dict | None:
    if record is None:
        return None
    for name, default in ADAPTER_FIELD_DEFAULTS.items():
        if name not in record:
            record[name] = list(default) if isinstance(default, tuple) else default
    return record


@contextmanager
def _lock(root: Path):
    """Share Core's task lock across adapter reads and coupled writes.

    Adapter helpers may reenter on the same thread; Core remains the single
    cross-process lock owner. This prevents checking an intermediate digest
    between a checked state append and its authority checkpoint.
    """
    key = root.resolve()
    held = getattr(_held_task_locks, "roots", set())
    if key in held:
        yield
        return
    with core._lock(root):
        _held_task_locks.roots = held | {key}
        try:
            yield
        finally:
            _held_task_locks.roots = held


def directory() -> Path:
    # Deliberately independent of CODEX_HOME and repository configuration.
    return Path.home() / ".thaliris" / "task-authority"


def _store(root: Path, task_id: str | None = None) -> authority.AuthorityStore:
    return authority.AuthorityStore(root, directory(), protected_paths=SECURITY_PATHS, task_id=task_id)


def path(root: Path) -> Path:
    return _store(root).path()


def read(root: Path) -> dict | None:
    return _with_adapter_defaults(_store(root).read()) if core.selected_task(root) is not None else None


def write(root: Path, record: dict) -> None:
    _store(root).write(record)


def _validate_contract(value: object) -> dict:
    from . import roles
    if isinstance(value, dict) and "execution_constraint" in value and roles.canonical_execution_constraint(value["execution_constraint"]) is None:
        raise ValueError("UNSUPPORTED_EXECUTION_CONSTRAINT")
    return authority.validate_contract(value)


def execution_constraint(record: dict) -> str | None:
    """The frozen constraint under its current name; an unknown one fails closed."""
    from . import roles
    frozen = record["contract"].get("execution_constraint")
    if frozen is None:
        return None
    canonical = roles.canonical_execution_constraint(frozen)
    if canonical is None:
        raise ExecutionConstraintUnsatisfied("UNSUPPORTED_EXECUTION_CONSTRAINT")
    return canonical


def contract(filename: str) -> dict:
    return _validate_contract(json.loads(Path(filename).read_text(encoding="utf-8")))


def establish(root: Path, state: dict, intent: dict, session_hash: str | None) -> dict:
    prior = _store(root, state["task_id"]).read()
    if prior is not None and prior["status"] == "ACTIVE":
        raise ValueError("TASK_AUTHORITY_ALREADY_ACTIVE")
    intent = _validate_contract(intent)
    fields = {}
    if intent.get("execution_constraint") is not None:
        from . import codex_adapter, roles
        # Provenance only: later checks re-evaluate the installed
        # configuration against the policy, never against this summary.
        fields["execution_profiles"] = codex_adapter.execution_profile_semantics(
            root, roles.canonical_execution_constraint(intent["execution_constraint"]))
    return _store(root).establish(state, intent, adapter_fields={
        **fields,
        "provenance": "CONTROLLER_ASSERTED_HUMAN_INSTRUCTION", "host_actor_assurance": "UNKNOWN",
        "origin_session_hash": session_hash, "lifecycle_sha256": "ABSENT",
        "fenced_sessions": prior.get("fenced_sessions", []) if prior else [],
        "fenced_agents": prior.get("fenced_agents", []) if prior else [],
    })


def _evidence(root: Path, record: dict) -> dict:
    from . import lifecycle
    if "lifecycle_sha256" not in record:
        # An anchor older than this field recorded no ledger: still require
        # its absence instead of accepting unanchored ledger bytes.
        if digest(lifecycle._lifecycle_path(root, record["task_id"])) != "ABSENT":
            raise ValueError("TASK_AUTHORITY_LIFECYCLE_CHANGED")
        return {}
    return {"lifecycle_sha256": (lifecycle._lifecycle_path(root, record["task_id"]), "TASK_AUTHORITY_LIFECYCLE_CHANGED")}


def check(root: Path, *, enforce_execution_constraint: bool = True) -> dict | None:
    """Check the anchor; with a constraint, also check the installation meets it.

    ``enforce_execution_constraint=False`` is only for close-out operations
    (task-abandon, task-close, status reads) that dispatch nothing; every
    integrity check (state, security bytes, ledger digest) still applies.
    """
    if core.selected_task(root) is None:
        return None
    with _lock(root):
        return _check_locked(root, enforce_execution_constraint)


def _check_locked(root: Path, enforce_execution_constraint: bool = True) -> dict | None:
    if core.selected_task(root) is None:
        return None
    store = _store(root)
    record = store.check()
    if record is None:
        return None
    constraint = None
    if record["contract"].get("execution_constraint") is not None and enforce_execution_constraint:
        from . import codex_adapter
        constraint = execution_constraint(record)
        try:
            codex_adapter.execution_profile_semantics(root, constraint)
        except ExecutionConstraintUnsatisfied:
            raise
        except ValueError as exc:
            raise ExecutionConstraintUnsatisfied(str(exc)) from None
    checked = _with_adapter_defaults(store.check(evidence=_evidence(root, record)))
    if constraint is not None and checked is not None:
        # Callers compare the current name; the stored contract is unchanged.
        checked["contract"] = {**checked["contract"], "execution_constraint": constraint}
    return checked


def checkpoint(root: Path) -> None:
    """Only trusted command closures call this after previously checked writes."""
    _store(root).checkpoint()


def capture(path_: Path, value: dict) -> None:
    """Update an external lifecycle/fence copy only for a checked adapter write."""
    if path_.parent.name == "lifecycle" and path_.parent.parent.name == "audit":
        root = path_.parents[3]
        record = read(root)
        if record is not None and record["status"] == "ACTIVE":
            from . import lifecycle
            if path_ != lifecycle._lifecycle_path(root, record["task_id"]):
                raise ValueError("TASK_AUTHORITY_LIFECYCLE_IDENTITY_CHANGED")
            record["lifecycle_sha256"] = digest(path_)
            record["lifecycle_snapshot"] = value
            write(root, record)
    elif path_.name in {"session-fence.json", "abandoned-child-fence.json"}:
        root = next(parent.parent for parent in path_.parents if parent.name == ".context")
        record = read(root)
        if record is not None:
            if path_.name == "session-fence.json":
                record["fenced_sessions"] = sorted(set(record["fenced_sessions"]) | set(value.get("session_id_hashes", [])))
            else:
                record["fenced_agents"] = sorted(set(record["fenced_agents"]) | set(value.get("agent_id_hashes", [])) |
                    {item["agent_id_hash"] for item in value.get("children", [])})
            write(root, record)


def recover(root: Path, expected: str, reason: str) -> dict:
    """Restore the recorded authority and fence old Codex children.

    This continues the recorded authority without a new human grant. Unknown
    native delegates remain indistinguishable; Hook checks known ones.
    """
    def archive_paths(record: dict) -> dict:
        from . import lifecycle
        return {"lifecycle.json": lifecycle._lifecycle_path(root, record["task_id"])}

    def restore_adapter(record: dict) -> None:
        from . import lifecycle
        ledger_path = lifecycle._lifecycle_path(root, record["task_id"])
        ledger = record.get("lifecycle_snapshot", {})
        # Every dropped reservation is reset like the singular slot, and an
        # agent already identified for one is fenced with the old children.
        reservations = lifecycle._pending_reservations(ledger) if isinstance(ledger, dict) else []
        _with_adapter_defaults(record)
        record["fenced_agents"] = sorted(set(record["fenced_agents"]) |
            {child["agent_id_hash"] for child in ledger.get("children", []) if child.get("agent_id_hash")} |
            {item["native_agent_id_hash"] for item in reservations if isinstance(item.get("native_agent_id_hash"), str)})
        if ledger:
            # Core archived the exact old provenance. A fresh handoff is
            # required; no old child is called Completed.
            ledger = {**ledger, "children": [], "pending_authorized_spawn": None}
            if "pending_authorized_spawns" in ledger:
                ledger["pending_authorized_spawns"] = []
            core._atomic_write(ledger_path, (json.dumps(ledger, sort_keys=True, indent=2) + "\n").encode())
            record["lifecycle_snapshot"] = ledger
            record["lifecycle_sha256"] = digest(ledger_path)
        elif ledger_path.is_file():
            ledger_path.unlink()
        if record["contract"].get("execution_constraint") is not None:
            # Re-derive the provenance summary from the installed
            # configuration. An unmet constraint stays visible and keeps
            # managed control refused until the installation satisfies it.
            from . import codex_adapter, roles
            constraint = roles.canonical_execution_constraint(record["contract"]["execution_constraint"])
            try:
                if constraint is None:
                    raise ValueError("UNSUPPORTED_EXECUTION_CONSTRAINT")
                record["execution_profiles"] = codex_adapter.execution_profile_semantics(root, constraint)
            except (OSError, ValueError) as exc:
                record["execution_profiles"] = {"format": codex_adapter.EXECUTION_SEMANTICS_FORMAT,
                                                "constraint": record["contract"]["execution_constraint"],
                                                "status": "UNSATISFIED", "reason": str(exc)[:256]}
        record["recoveries"][-1]["death_proof"] = "UNKNOWN"

    result = _store(root).recover(expected, reason, archive_paths=archive_paths,
                                  restore_adapter=restore_adapter, evidence=lambda record: _evidence(root, record))
    return {**result, "host_actor_assurance": "UNKNOWN", "child_death_proof": "UNKNOWN"}


def switch_mode(root: Path, expected: str, base_revision: int, mode: str, human_instruction: str) -> dict:
    from . import lifecycle
    check(root)
    if lifecycle.managed_dependency_pending(root):
        raise ValueError("TASK_MODE_SWITCH_DEPENDENCIES_PENDING: cancel or abandon selected dependencies before changing execution responsibility; native death remains UNKNOWN")
    return _store(root).switch_mode(expected, base_revision, mode, human_instruction)
