"""Codex delivery of the Core Project Identity plane.

Core owns identity records, versions, challenges and relations. This adapter
only surfaces Core's one-line summary to the Controller. It never injects
identity text into delegated children and never adds enforcement state.
"""
from __future__ import annotations

from pathlib import Path

from thaliris import identity

# Controller-only mutations; read-only commands carry no role and no task.
MUTATIONS = ("identity-amend", "identity-challenge", "identity-relate")
READS = ("identity-status", "identity-get", "identity-trace")
# Controller-only, but they need neither the selected ACTIVE task nor a base
# revision: basis notes and suggestion preferences live outside the repository.
FORMATION = ("identity-note", "identity-suggest")
SUMMARY_FIELD = "project_identity_summary"


def summary(root: Path) -> str | None:
    """Return Core's one-line summary, or None when absent or unreadable.

    Delivery must never break admission or routing: an unreadable namespace is
    reported by the explicit ``identity-status`` command, not by this hint.
    """
    try:
        return identity.identity_summary(root)
    except (ValueError, OSError, RuntimeError):
        return None


def offer(root: Path, session_key: str | None = None) -> str | None:
    """Return Core's one-line identity offer after a successful close, or None.

    Core records that the offer was shown. Any failure leaves the field absent.
    """
    try:
        from thaliris import identity_basis
        return identity_basis.identity_offer(root, session_key)
    except Exception:  # noqa: BLE001 - an offer must never change a close result
        return None
