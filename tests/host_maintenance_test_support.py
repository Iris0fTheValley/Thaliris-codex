"""Approved external Host caller used by installer regression fixtures."""
from __future__ import annotations

import json
import os
from pathlib import Path

from thaliris_codex import runtime_identity


def _home(tmp_path: Path, args: tuple, kwargs: dict) -> Path:
    if "codex_home" in kwargs and kwargs["codex_home"] is not None:
        return Path(kwargs["codex_home"])
    if args and args[0] is not None:
        return Path(args[0])
    configured = os.environ.get("CODEX_HOME")
    return Path(configured) if configured else tmp_path / "codex-home"


def _contract(tmp_path: Path, pinned_test_thaliris, operation: str, home: Path,
              execution_constraint: str | None, legacy_owned_bytes: dict | None) -> Path:
    from thaliris_codex import host_maintenance

    selection = json.loads((tmp_path / ".test-host-runtime-selection.json").read_bytes())
    prior = home / runtime_identity.MANIFEST_NAME
    value = {
        "format": host_maintenance.FORMAT,
        "operation": operation,
        "codex_home": str(home),
        "human_instruction": f"Test caller explicitly approves this exact {operation} operation.",
        "executor": selection,
        "installed_runtime_sha256": host_maintenance.digest(prior.read_bytes())
        if prior.is_file() and not prior.is_symlink() else "ABSENT",
        "legacy_owned_bytes": legacy_owned_bytes or {},
    }
    if operation == "codex-install":
        value["candidate"] = selection
        value["execution_constraint"] = execution_constraint
    directory = tmp_path / ".test-maintenance-contracts"
    directory.mkdir(exist_ok=True)
    path = directory / f"{operation}-{len(list(directory.glob('*.json'))):03d}.json"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def legacy_file_hashes(home: Path, names) -> dict[str, str]:
    """Return exact bytes a test caller explicitly approves as prior legacy ownership."""
    from thaliris_codex import host_maintenance
    return {name: host_maintenance.digest((home / name).read_bytes()) for name in names}


def attest_prior_authorized_bytes(home: Path, owned_bytes: dict[str, bytes]) -> None:
    """Model a prior valid ownership receipt for exact historical file bytes."""
    from thaliris_codex import host_maintenance
    path = home / host_maintenance.RECEIPT_NAME
    receipt = json.loads(path.read_bytes())
    receipt.setdefault("owned_bytes", {}).update({
        name: host_maintenance.digest(contents) for name, contents in owned_bytes.items()
    })
    path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")


def authorized_host_install(tmp_path: Path, pinned_test_thaliris, *args, **kwargs):
    """Invoke the public API as a test operator with explicit intent and pins."""
    legacy = kwargs.pop("_legacy_owned_bytes", None)
    home = _home(tmp_path, args, kwargs)
    path = _contract(tmp_path, pinned_test_thaliris, "codex-install", home,
                     kwargs.get("execution_constraint"), legacy)
    kwargs["maintenance_contract"] = path
    if not args and "codex_home" not in kwargs and "CODEX_HOME" not in os.environ:
        kwargs["codex_home"] = home
    from thaliris_codex import codex_adapter
    return codex_adapter.codex_install(*args, **kwargs)


def authorized_host_uninstall(tmp_path: Path, pinned_test_thaliris, *args, **kwargs):
    """Invoke uninstall as a test operator with explicit intent and pins."""
    legacy = kwargs.pop("_legacy_owned_bytes", None)
    home = _home(tmp_path, args, kwargs)
    path = _contract(tmp_path, pinned_test_thaliris, "codex-uninstall", home, None, legacy)
    kwargs["maintenance_contract"] = path
    if not args and "codex_home" not in kwargs and "CODEX_HOME" not in os.environ:
        kwargs["codex_home"] = home
    from thaliris_codex import codex_adapter
    return codex_adapter.codex_uninstall(*args, **kwargs)
