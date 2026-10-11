"""Manage the optional Controller wait guidance in Codex user config.

This owns only one inserted TOML field, never config.toml as a whole. Host
maintenance receipts and transition journals provide the durable ownership and
recovery boundary, just as they do for the native mode-hint field.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
import shutil
import subprocess
import tomllib

RECORD_KEY = "controller_wait_guidance"
KEY = "developer_instructions"
GUIDANCE = (
    "When awaiting a necessary native subagent, the general 60-second blocking-wait "
    "recommendation is not a fixed timeout limit. Choose an event-aware wait duration "
    "informed by the expected task, which may take several minutes or longer. Prefer "
    "native completion events over short polling loops. A timeout alone is not progress. "
    "Avoid unnecessary model wakeups and preserve responsiveness to interruptions and "
    "substantive events."
)
MARKER = "# thaliris:controller-wait-guidance\n"
_SUPPORTED_VERSION = re.compile(r"^codex-cli 0\.162\.\d+(?:-[A-Za-z0-9.-]+)?$")


def capability() -> str:
    """Use only the explicitly supported Codex 0.162 version family."""
    executable = shutil.which("codex")
    if executable is None:
        return "UNKNOWN"
    try:
        result = subprocess.run([executable, "--version"], capture_output=True,
                                text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return "SUPPORTED" if result.returncode == 0 and _SUPPORTED_VERSION.fullmatch(result.stdout.strip()) else "UNKNOWN"


def read(home: Path) -> tuple[bytes, dict]:
    from .host_maintenance import safe
    path = home / "config.toml"
    safe(path)
    raw = path.read_bytes() if path.exists() else b""
    return raw, tomllib.loads(raw.decode("utf-8"))


def status(name: str, *, changed: bool = False) -> dict:
    return {"status": name, "changed": changed, "key_path": KEY,
            "effective_session_status": "UNKNOWN", "scope": "user config only"}


def _fragment(newline: str, guidance: str | None = None) -> str:
    if guidance is None:
        guidance = GUIDANCE
    return newline + MARKER.replace("\n", newline) + f"{KEY} = {json.dumps(guidance)}{newline}"


def _recorded_guidance(fragment: str) -> str:
    """Read a canonical recorded fragment without comparing it to today's text.

    The receipt records the exact bytes installed by its generation. Historical
    ownership therefore follows those bytes and the marker/key structure, even
    after the current guidance wording changes.
    """
    if not isinstance(fragment, str):
        raise ValueError("invalid Controller wait guidance owned bytes")
    newline = "\r\n" if "\r\n" in fragment else "\n"
    prefix = newline + MARKER.replace("\n", newline) + f"{KEY} = "
    suffix = newline
    if not fragment.startswith(prefix) or not fragment.endswith(suffix):
        raise ValueError("invalid Controller wait guidance owned bytes")
    encoded = fragment[len(prefix):-len(suffix)]
    try:
        value = json.loads(encoded)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid Controller wait guidance owned bytes") from exc
    if not isinstance(value, str) or _fragment(newline, value) != fragment:
        raise ValueError("invalid Controller wait guidance owned bytes")
    return value


def _matches(raw: bytes, config: dict, record: dict) -> bool:
    fragment = record["fragment"].encode("utf-8")
    try:
        if config.get(KEY) != _recorded_guidance(record["fragment"]) or raw.count(fragment) != 1:
            return False
        removed = tomllib.loads(raw.replace(fragment, b"", 1).decode("utf-8"))
        return KEY not in removed
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError, TypeError):
        return False


def validate(record: object, home: Path | None = None) -> None:
    if record is None:
        return
    if not isinstance(record, dict) or set(record) != {"path", "prior", "fragment"}:
        raise ValueError("invalid Controller wait guidance ownership record")
    if not isinstance(record["path"], str) or record["prior"] != {"present": False}:
        raise ValueError("invalid Controller wait guidance prior state")
    if home is not None and record["path"] != str((home / "config.toml").absolute()):
        raise ValueError("Controller wait guidance path differs from CODEX_HOME")
    _recorded_guidance(record["fragment"])


def plan_install(home: Path, ownership: dict) -> tuple[dict | None, dict]:
    record = ownership.get(RECORD_KEY)
    validate(record, home)
    try:
        raw, config = read(home)
    except OSError:
        # This field is optional to Host installation. Keep an existing valid
        # ownership record so later uninstall can still restore its bytes;
        # never turn a config read failure into permission to claim the field.
        return record, status("OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED")
    if record is not None:
        return record, status("MANAGED" if _matches(raw, config, record) else "USER_CHANGED_PRESERVED")
    if KEY in config:
        return None, status("USER_CONFIG_PRESERVED")
    if capability() != "SUPPORTED":
        return None, status("VERSION_SUPPORT_UNKNOWN")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    fragment = _fragment(newline)
    record = {"path": str((home / "config.toml").absolute()),
              "prior": {"present": False}, "fragment": fragment}
    return record, status("PLANNED")


def _insert(raw: bytes, fragment: bytes) -> bytes:
    text = raw.decode("utf-8")
    # Root keys must precede the first table. TOML assigns appended keys to the
    # last table, so insertion is anchored at that exact syntactic boundary.
    first_table = re.search(r"(?m)^[ \t]*\[", text)
    at = len(text[:first_table.start()].encode("utf-8")) if first_table else len(raw)
    return raw[:at] + fragment + raw[at:]


def apply(home: Path, record: dict | None, *, remove: bool = False, allow_insert: bool = False) -> dict:
    from .codex_adapter import _atomic_host_write
    validate(record, home)
    if record is None:
        return status("UNMANAGED_PRESERVED")
    raw, config = read(home)
    fragment = record["fragment"].encode("utf-8")
    matched = _matches(raw, config, record)
    if remove:
        if KEY not in config:
            return status("ALREADY_ABSENT")
        if not matched:
            return status("USER_CHANGED_PRESERVED")
        after = raw.replace(fragment, b"", 1)
        try:
            if KEY in tomllib.loads(after.decode("utf-8")):
                return status("USER_CHANGED_PRESERVED")
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            return status("USER_CHANGED_PRESERVED")
    else:
        if matched:
            return status("MANAGED")
        if KEY in config or not allow_insert:
            return status("USER_CHANGED_PRESERVED")
        after = _insert(raw, fragment)
        try:
            parsed = tomllib.loads(after.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            return status("STRUCTURE_UNSUPPORTED_PRESERVED")
        if parsed.get(KEY) != GUIDANCE:
            return status("STRUCTURE_UNSUPPORTED_PRESERVED")
    if read(home)[0] != raw:
        raise ValueError("Codex user config changed before Controller wait guidance write")
    _atomic_host_write(home / "config.toml", after)
    if read(home)[0] != after:
        raise ValueError("Controller wait guidance write could not be verified")
    return status("RESTORED_ABSENT" if remove else "MANAGED", changed=True)


def finish_install(home: Path, transition: dict) -> dict:
    """Journal the field write before applying it; never reacquire after a crash."""
    from . import host_transition
    finish = transition["finish"]
    selected = finish.get("wait_guidance_status", status("LEGACY_UNMANAGED"))
    if selected["status"] not in {"PLANNED", "MANAGED"}:
        return selected
    record = finish["wait_guidance_record"]
    if selected["status"] == "MANAGED":
        try:
            return apply(home, record)
        except (OSError, ValueError, RuntimeError):
            return status("OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED")
    phase = finish.get("wait_guidance_phase")
    if phase == "APPLIED":
        try:
            current = apply(home, record)
        except (OSError, ValueError, RuntimeError):
            return status("APPLY_OUTCOME_UNKNOWN_PRESERVED")
        current["changed"] = finish["wait_guidance_result"]["changed"]
        return current
    if phase == "ATTEMPTING":
        try:
            raw, config = read(home)
        except (OSError, ValueError, RuntimeError):
            return status("APPLY_OUTCOME_UNKNOWN_PRESERVED")
        if not _matches(raw, config, record):
            return status("APPLY_OUTCOME_UNKNOWN_PRESERVED")
        result = status("MANAGED", changed=True)
    else:
        try:
            before, _ = read(home)
        except (OSError, ValueError, RuntimeError):
            return status("OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED")
        finish["wait_guidance_phase"] = "ATTEMPTING"
        # This journal write is required before mutating config.toml. Let it
        # escape: without durable ATTEMPTING state, the optional write cannot
        # safely proceed as part of the Host transaction.
        host_transition._write(home, transition)
        try:
            result = apply(home, record, allow_insert=True)
        except (OSError, ValueError, RuntimeError):
            try:
                after, config = read(home)
            except (OSError, ValueError, RuntimeError):
                # The journal already records ATTEMPTING. Keep that evidence
                # and let Host installation finish with the optional result
                # explicitly unknown.
                return status("APPLY_OUTCOME_UNKNOWN_PRESERVED")
            if after == before:
                finish.pop("wait_guidance_phase", None)
                host_transition._write(home, transition)
                return status("OPTIONAL_WRITE_FAILED_PRESERVED")
            if not _matches(after, config, record):
                # Do not roll back bytes whose ownership cannot be proved.
                # The Host transaction can still complete because this field
                # is optional; the persisted ATTEMPTING phase prevents replay
                # from silently reacquiring it.
                return status("APPLY_OUTCOME_UNKNOWN_PRESERVED")
            result = status("MANAGED", changed=True)
    finish["wait_guidance_phase"] = "APPLIED"
    finish["wait_guidance_result"] = result
    host_transition._write(home, transition)
    return result
