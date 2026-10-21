"""Exact actor navigation across worktrees; never an authority grant.

Entries are published only beside an existing repository-local association.
Readers validate both records. No workspace descendants are searched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from thaliris import core
from . import task_authority


def directory() -> Path:
    return task_authority.directory() / "navigation"


def _directory(kind: str, identity: str) -> Path:
    if kind not in {"session", "agent"} or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
        raise ValueError("REPOSITORY_ASSOCIATION_INVALID")
    base = directory()
    target = base / kind / identity
    if any(path.is_symlink() or getattr(path, "is_junction", lambda: False)()
           for path in (target, *target.parents)):
        raise ValueError("REPOSITORY_ASSOCIATION_UNSAFE")
    return target


def publish(root: Path, task_id: str, identity: str, kind: str) -> None:
    root = root.resolve()
    key = hashlib.sha256((str(root).casefold() if os.name == 'nt' else str(root)).encode()).hexdigest()
    directory = _directory(kind, identity)
    directory.mkdir(parents=True, exist_ok=True)
    target = core._safe_without_final_symlink(directory, key + ".json")
    core._atomic_write(target, (json.dumps({"version": 1, "repository": str(root),
        "task_id": task_id, "kind": kind, "identity_hash": identity}, sort_keys=True) + "\n").encode())


def resolve(payload: dict, cwd_root: Path, *, requested_root: Path | None = None) -> Path | None:
    cwd_root = cwd_root.resolve()
    requested_root = requested_root.resolve() if requested_root is not None else None
    # An exact child retains its repository even when its Controller changes task.
    for field, kind in (("agent_id", "agent"), ("session_id", "session")):
        actor = payload.get(field)
        if not isinstance(actor, str) or not actor:
            continue
        identity = hashlib.sha256(actor.encode()).hexdigest()
        directory = _directory(kind, identity)
        matches = set()
        for path in directory.glob("*.json"):
            path = core._safe_without_final_symlink(directory, path.name)
            value = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or value.get("version") != 1
                    or value.get("identity_hash") != identity or value.get("kind") != kind):
                raise ValueError("REPOSITORY_ASSOCIATION_INVALID")
            repository = Path(value["repository"])
            if not repository.is_absolute():
                raise ValueError("REPOSITORY_ASSOCIATION_INVALID")
            local = core._safe_without_final_symlink(repository,
                f".context/audit/{kind}-tasks/{identity}.json")
            current = json.loads(local.read_text(encoding="utf-8"))
            if (current.get("task_id") != value.get("task_id")
                    or current.get(f"{kind}_id_hash") != identity):
                raise ValueError("REPOSITORY_ASSOCIATION_STALE")
            # This is navigation. The selected Hook path performs the original
            # authority, owner, fence, lifecycle and role checks before granting.
            matches.add(repository.resolve())
        if matches:
            if kind == "agent" and len(matches) != 1:
                raise ValueError("REPOSITORY_ASSOCIATION_AMBIGUOUS")
            if requested_root is not None:
                if requested_root not in matches:
                    raise ValueError("REPOSITORY_ASSOCIATION_CONFLICT")
                # A CLI root only selects an already validated association.
                # In particular it cannot replace an exact child's root with
                # one of the Controller session's other repositories.
                return requested_root
            if cwd_root in matches:
                return cwd_root
            if len(matches) == 1:
                return matches.pop()
            raise ValueError("REPOSITORY_ASSOCIATION_AMBIGUOUS")
    if requested_root is not None and requested_root != cwd_root:
        raise ValueError("REPOSITORY_ASSOCIATION_UNKNOWN")
    return None
