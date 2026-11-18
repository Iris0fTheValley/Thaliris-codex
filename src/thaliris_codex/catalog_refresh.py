"""Receipt-authorized refresh of the managed model catalog after a Codex CLI change.

The managed catalog replaces the CLI's bundled catalog, so it is a snapshot of
the CLI that exported it. When the Codex CLI changes, new upstream models would
stay invisible until someone reran Host maintenance. This module keeps that one
receipt-owned surface current, and nothing else:

* Who: only the owning Controller's SessionStart path (non-child, not readonly,
  not fenced; the same deny-only actor gate as catalog recovery) or the explicit
  ``codex-model-catalog-refresh`` command, which children are refused by the
  PreToolUse guard. Neither establishes new authority; both act under the
  recorded human install instruction that made the catalog receipt-owned.
* What: only ``thaliris-model-catalog.json`` and the receipt's
  ``native_model_catalog`` entry. ``config.toml``, profiles, hooks, the runtime
  manifest and every other receipt field stay byte-identical, so the runtime
  identity is unaffected and ``status`` keeps reporting MATCH.
* Source: the kind the install recorded. A bundled install refreshes offline
  from the current CLI's own bundled catalog; an online install refreshes
  online (never a silent downgrade). Patching is exactly ``patch_catalog``.
* How: plan without writing, then under the shared Host maintenance lock with
  no pending transition, compare-and-swap every input and write the catalog
  before the receipt. An interruption between those two atomic writes leaves
  exactly the planned bytes, which the next explicit refresh recognizes (after
  re-exporting) and completes; SessionStart only reports it.
* Failure: any unsafe or impossible case writes nothing and returns
  ``MODEL_CATALOG_STALE`` with the exact command. It never blocks ordinary work.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

COMMAND = "codex-model-catalog-refresh"
STALE = "MODEL_CATALOG_STALE"
CURRENT = "MODEL_CATALOG_CURRENT"
REFRESHED = "MODEL_CATALOG_REFRESHED"
NOT_MANAGED = "MODEL_CATALOG_NOT_MANAGED"
# SessionStart shares the 60-second native hook budget with the ordinary
# SessionStart callback; an explicit command may wait longer.
AUTOMATIC_EXPORT_TIMEOUT = 20
EXPLICIT_EXPORT_TIMEOUT = 90


def command_text(home: Path) -> str:
    """The exact explicit command, through the installed runtime when it is known."""
    from . import controller_instructions, runtime_identity
    try:
        manifest = runtime_identity.validate_manifest_record((home / runtime_identity.MANIFEST_NAME).read_bytes())
        return f'{controller_instructions.runner_command(Path(manifest["executable"]))} {COMMAND}'
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        return f"thaliris {COMMAND}"


def _stale(home: Path, reason: str, **facts) -> dict:
    return {"ok": False, "changed": False, "status": STALE, "reason": reason,
            "command": command_text(home), "ordinary_work_blocked": False,
            "recovery_action": f"Run {command_text(home)} as the Controller (not a child), "
                               "or rerun Host maintenance with --refresh-model-catalog.",
            **facts}


def _owned_state(home: Path, identity: str | None):
    """Return the validated installed manifest, receipt bytes/record and catalog record."""
    from . import host_maintenance as maintenance, runtime_identity, model_catalog_config as catalog
    path = home / runtime_identity.MANIFEST_NAME
    maintenance.safe(path)
    if not path.exists():
        return None
    installed = path.read_bytes()
    manifest = runtime_identity.validate_manifest_record(installed)
    if identity is None:
        runtime_identity.validate_existing_manifest(
            installed, Path(manifest["executable"]), maintenance.digest(installed))
    elif maintenance.digest(installed) != identity:
        # The caller verified the installed files against this exact identity.
        raise ValueError("installed runtime manifest identity mismatch")
    receipt_path = home / maintenance.RECEIPT_NAME
    maintenance.safe(receipt_path)
    if not receipt_path.exists():
        return None
    original = receipt_path.read_bytes()
    receipt = maintenance.validate_ownership(original, installed, {})
    record = receipt.get(catalog.RECORD_KEY)
    if record is None:
        return None
    catalog.validate(record, home)
    return installed, original, receipt, record


def _reported_current(record: dict) -> tuple[bool, str]:
    """Cheap freshness: same reported CLI version and same transformation contract.

    It skips work only; it never certifies reuse. Install reuse and the
    explicit refresh still require the CLI binary's SHA-256 (hashing a
    several-hundred-megabyte binary at every SessionStart would not be cheap).
    """
    from . import model_catalog_config as catalog
    executable = catalog._executable()
    if executable is None:
        return False, "CLI_IDENTITY_UNOBSERVABLE"
    try:
        version = catalog._version_provenance(executable)
    except (OSError, subprocess.SubprocessError):
        return False, "CLI_IDENTITY_UNOBSERVABLE"
    if version == "UNKNOWN":
        return False, "CLI_IDENTITY_UNOBSERVABLE"
    if version != record["source"]["cli_version"]:
        return False, "CLI_CHANGED"
    proof = record.get("reuse_contract")
    if proof is None or proof != catalog.reuse_contract(record["source"]["kind"], record["source"]):
        return False, "CATALOG_CONTRACT_CHANGED"
    return True, "CURRENT"


def state(home: Path) -> dict:
    """Read-only freshness of the managed catalog for the current Codex CLI."""
    from . import host_transition, model_catalog_config as catalog
    try:
        if host_transition.pending(home):
            return {"ok": False, "changed": False, "status": "HOST_TRANSITION_PENDING"}
        owned = _owned_state(home, None)
        if owned is None:
            return {"ok": True, "changed": False, "status": NOT_MANAGED}
        _, _, _, record = owned
        current = catalog.read_catalog(home)
        if current is None or catalog.digest(current) != record["catalog_sha256"]:
            return _stale(home, "CATALOG_CHANGED_PRESERVED")
        current_enough, reason = _reported_current(record)
        if not current_enough:
            return _stale(home, reason, recorded_cli_version=record["source"]["cli_version"])
        return {"ok": True, "changed": False, "status": CURRENT,
                "source": record["source"]["kind"], "cli_version": record["source"]["cli_version"]}
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        return _stale(home, "STATE_UNKNOWN", diagnostic=str(exc)[:300])


def refresh(home: Path, identity: str | None = None, *, automatic: bool = False) -> dict:
    """Refresh the receipt-owned catalog from the current CLI, or explain why not.

    ``identity`` is the installed runtime manifest SHA-256 the caller verified
    (SessionStart); ``None`` validates the manifest against its own digest.
    """
    from . import host_maintenance as maintenance, host_transition, runtime_identity, model_catalog_config as catalog
    from .codex_adapter import _atomic_host_write
    try:
        if host_transition.pending(home):
            return {"ok": False, "changed": False, "status": "HOST_TRANSITION_PENDING",
                    "ordinary_work_blocked": False,
                    "recovery_action": "Replay the original maintenance contract"}
        owned = _owned_state(home, identity)
        if owned is None:
            return {"ok": True, "changed": False, "status": NOT_MANAGED}
        installed, original, receipt, record = owned
        source = record["source"]["kind"]
        raw, config = catalog.read(home)
        if not catalog.matches(raw, config, record):
            # A removed, edited or recovery-restored field is the user's or a
            # recovery's decision; a refresh never writes config.toml.
            return _stale(home, "CATALOG_FIELD_NOT_MANAGED")
        current = catalog.read_catalog(home)
        if current is None:
            return _stale(home, "CATALOG_MISSING_PRESERVED")
        prior = catalog.digest(current)
        if prior != record["catalog_sha256"] and automatic:
            # Only the explicit command exports to check for an interrupted
            # refresh; a user change must not cost an export every session.
            return _stale(home, "CATALOG_CHANGED_PRESERVED")
        if prior == record["catalog_sha256"]:
            if automatic:
                current_enough, reason = _reported_current(record)
                if current_enough:
                    return {"ok": True, "changed": False, "status": CURRENT, "source": source,
                            "cli_version": record["source"]["cli_version"], "cli_check": "REPORTED_VERSION"}
                if reason == "CLI_IDENTITY_UNOBSERVABLE":
                    # Without an observable CLI every session would re-export.
                    return _stale(home, reason)
            elif catalog.compatible_owned_source(record, source):
                return {"ok": True, "changed": False, "status": CURRENT, "source": source,
                        "cli_version": record["source"]["cli_version"], "cli_check": "BINARY_SHA256"}
        updated, failure, patched, compatibility, _ = catalog._exported_record(
            home, record, source, raw,
            timeout=AUTOMATIC_EXPORT_TIMEOUT if automatic else EXPLICIT_EXPORT_TIMEOUT)
        if failure is not None:
            return _stale(home, failure["status"], upstream=failure)
        if prior != record["catalog_sha256"] and prior != updated["catalog_sha256"]:
            # Not the owned generation and not the exact planned bytes either.
            return _stale(home, "CATALOG_CHANGED_PRESERVED")
        if updated == record:
            return {"ok": True, "changed": False, "status": CURRENT, "source": source,
                    "cli_version": record["source"]["cli_version"]}
        receipt = dict(receipt)
        receipt[catalog.RECORD_KEY] = updated
        receipt_bytes = (json.dumps(receipt, sort_keys=True, ensure_ascii=False) + "\n").encode()
        maintenance.validate_ownership(receipt_bytes, installed, {})
        receipt_path = home / maintenance.RECEIPT_NAME
        with host_transition.locked(home):
            if host_transition.pending(home):
                return _stale(home, "HOST_TRANSITION_PENDING")
            manifest_path = home / runtime_identity.MANIFEST_NAME
            maintenance.safe(manifest_path)
            if (manifest_path.read_bytes() != installed or receipt_path.read_bytes() != original
                    or catalog.read(home)[0] != raw or catalog.read_catalog(home) != current):
                return _stale(home, "HOST_CHANGED_DURING_REFRESH")
            if current != patched:
                _atomic_host_write(home / catalog.NAME, patched)
                if catalog.read_catalog(home) != patched:
                    raise ValueError("model catalog refresh write verification failed")
            _atomic_host_write(receipt_path, receipt_bytes)
            if receipt_path.read_bytes() != receipt_bytes:
                raise ValueError("model catalog receipt write verification failed")
        return {"ok": True, "changed": True, "status": REFRESHED, "source": updated["source"],
                "previous_cli_version": record["source"]["cli_version"],
                "completed_interrupted_refresh": prior != record["catalog_sha256"],
                "template_compatibility": compatibility,
                "effective_session_status": "UNKNOWN",
                "note": "New Codex sessions read the refreshed catalog; a running session may keep its loaded catalog."}
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        return _stale(home, "REFRESH_FAILED", diagnostic=str(exc)[:300])


def explicit(home: Path) -> dict:
    """The explicit command, run only by the installed pinned runtime."""
    import sys
    from . import host_maintenance as maintenance, runtime_identity
    try:
        installed = maintenance._installed(home)
        if installed is None:
            return {"ok": True, "changed": False, "status": NOT_MANAGED}
        manifest = runtime_identity.validate_manifest_record(installed)
        executable = Path(manifest["executable"])
        interpreter = executable.parent / ("python.exe" if sys.platform == "win32" else "python")
        if (Path(manifest["package_dir"]).resolve() != Path(__file__).resolve().parent
                or Path(sys.executable).resolve() != interpreter.resolve()):
            return _stale(home, "NOT_INSTALLED_RUNTIME",
                          diagnostic="the refresh must run the pinned installed Thaliris runtime")
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        return _stale(home, "REFRESH_FAILED", diagnostic=str(exc)[:300])
    return refresh(home, maintenance.digest(installed))
