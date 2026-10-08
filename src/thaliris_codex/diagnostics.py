"""Bounded failure-boundary observations, separate from Hook stdout decisions."""
from __future__ import annotations

import json
import sys

STAGES = frozenset({"receive", "decode", "json", "json-shape", "dispatch",
                    "maintenance-contract", "runtime-identity"})


def failure(stage: str) -> None:
    """Emit only an allowlisted boundary; never serialize inputs or exceptions.

    This does not establish a root cause or change an admission decision. A broken
    diagnostic sink cannot interfere with the existing refusal/return path.
    """
    if stage not in STAGES:
        return
    try:
        sys.stderr.write(json.dumps({"diagnostic": "thaliris-failure-v1", "stage": stage},
                                    separators=(",", ":")) + "\n")
    except Exception:
        # This catch surrounds only diagnostic output, never the guarded
        # operation. A detached/custom stderr must not change admission.
        pass
