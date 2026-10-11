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
    "Continue necessary independent work before waiting. Prefer meaningful native notifications "
    "over repeated status polling; do not wake models merely to observe unchanged state. "
    "Messages, timeouts and exceptions do not prove completion; preserve UNKNOWN when "
    "native completion evidence is unavailable. Use an available completed result without "
    "confirming the same completion again. Observe your own tests or external processes "
    "with their corresponding tools. Follow applicable role instructions and the selected handoff "
    "for authorized delegation and waiting; this guidance grants no role or authority."
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


def _fragments(record: dict) -> tuple[str, ...]:
    return (record["fragment"], *record.get("history", []))


def _matching_fragment(raw: bytes, config: dict, record: dict) -> bytes | None:
    try:
        for text in _fragments(record):
            fragment = text.encode("utf-8")
            if config.get(KEY) != _recorded_guidance(text) or raw.count(fragment) != 1:
                continue
            removed = tomllib.loads(raw.replace(fragment, b"", 1).decode("utf-8"))
            if KEY not in removed:
                return fragment
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError, TypeError):
        return None
    return None


def _matches_current(raw: bytes, config: dict, record: dict) -> bool:
    """Match only the current receipt fragment, for install/recovery success."""
    try:
        fragment = record["fragment"].encode("utf-8")
        if config.get(KEY) != _recorded_guidance(record["fragment"]) or raw.count(fragment) != 1:
            return False
        removed = tomllib.loads(raw.replace(fragment, b"", 1).decode("utf-8"))
        return KEY not in removed
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError, TypeError):
        return False


def validate(record: object, home: Path | None = None) -> None:
    if record is None:
        return
    if not isinstance(record, dict) or set(record) not in (
            {"path", "prior", "fragment"}, {"path", "prior", "fragment", "history"}):
        raise ValueError("invalid Controller wait guidance ownership record")
    if not isinstance(record["path"], str) or record["prior"] != {"present": False}:
        raise ValueError("invalid Controller wait guidance prior state")
    if home is not None and record["path"] != str((home / "config.toml").absolute()):
        raise ValueError("Controller wait guidance path differs from CODEX_HOME")
    _recorded_guidance(record["fragment"])
    history = record.get("history", [])
    if (not isinstance(history, list) or any(not isinstance(item, str) for item in history)
            or len(set(history)) != len(history) or record["fragment"] in history):
        raise ValueError("invalid Controller wait guidance history")
    for item in history:
        _recorded_guidance(item)


def plan_install(home: Path, ownership: dict) -> tuple[dict | None, dict, dict | None]:
    record = ownership.get(RECORD_KEY)
    validate(record, home)
    try:
        raw, config = read(home)
    except OSError:
        # This field is optional to Host installation. Keep an existing valid
        # ownership record so later uninstall can still restore its bytes;
        # never turn a config read failure into permission to claim the field.
        return record, status("OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED"), None
    if record is not None:
        matched = _matching_fragment(raw, config, record)
        if matched is None:
            if KEY in config and config[KEY] == "":
                return record, status("USER_EMPTY_PRESERVED"), None
            return record, status("USER_CHANGED_PRESERVED"), None
        old_fragment = matched.decode("utf-8")
        if _recorded_guidance(old_fragment) == GUIDANCE:
            if record["fragment"] == old_fragment:
                return record, status("MANAGED"), None
            # The source text has returned to an already owned exact historical
            # generation. Promote it as the current fragment without editing
            # the user's bytes.
            history = [item for item in _fragments(record) if item != old_fragment]
            promoted = {"path": record["path"], "prior": record["prior"],
                        "fragment": old_fragment}
            if history:
                promoted["history"] = list(dict.fromkeys(history))
            return promoted, status("MANAGED"), None
        if capability() != "SUPPORTED":
            return record, status("VERSION_SUPPORT_UNKNOWN"), None
        newline = "\r\n" if "\r\n" in old_fragment else "\n"
        current_fragment = _fragment(newline)
        history = [item for item in _fragments(record) if item != current_fragment]
        updated = {"path": record["path"], "prior": record["prior"],
                   "fragment": current_fragment, "history": list(dict.fromkeys(history))}
        validate(updated, home)
        if _recorded_guidance(old_fragment) == GUIDANCE:
            return updated, status("MANAGED"), None
        return updated, status("MIGRATION_PLANNED"), record
    if KEY in config:
        if config[KEY] == "":
            return None, status("USER_EMPTY_PRESERVED"), None
        return None, status("USER_CONFIG_PRESERVED"), None
    if capability() != "SUPPORTED":
        return None, status("VERSION_SUPPORT_UNKNOWN"), None
    newline = "\r\n" if b"\r\n" in raw else "\n"
    fragment = _fragment(newline)
    record = {"path": str((home / "config.toml").absolute()),
              "prior": {"present": False}, "fragment": fragment}
    return record, status("PLANNED"), None


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
    matched = _matching_fragment(raw, config, record)
    fragment = record["fragment"].encode("utf-8")
    if remove:
        if KEY not in config:
            return status("ALREADY_ABSENT")
        if not matched:
            return status("USER_CHANGED_PRESERVED")
        after = raw.replace(matched, b"", 1)
        try:
            if KEY in tomllib.loads(after.decode("utf-8")):
                return status("USER_CHANGED_PRESERVED")
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            return status("USER_CHANGED_PRESERVED")
    else:
        if _matches_current(raw, config, record):
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


def apply_migration(home: Path, previous: dict, record: dict) -> dict:
    """Replace only a value proven by the previous exact ownership receipt."""
    from .codex_adapter import _atomic_host_write
    validate_migration(previous, record, home)
    raw, config = read(home)
    if _matches_current(raw, config, record):
        return status("MANAGED")
    old_fragment = _matching_fragment(raw, config, previous)
    if old_fragment is None:
        return status("USER_CHANGED_PRESERVED")
    if old_fragment == record["fragment"].encode("utf-8"):
        return status("MANAGED")
    after = raw.replace(old_fragment, record["fragment"].encode("utf-8"), 1)
    try:
        parsed = tomllib.loads(after.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return status("STRUCTURE_UNSUPPORTED_PRESERVED")
    if not _matches_current(after, parsed, record):
        return status("STRUCTURE_UNSUPPORTED_PRESERVED")
    if read(home)[0] != raw:
        raise ValueError("Codex user config changed before Controller wait guidance migration")
    _atomic_host_write(home / "config.toml", after)
    if read(home)[0] != after:
        raise ValueError("Controller wait guidance migration could not be verified")
    return status("MANAGED", changed=True)


def validate_migration(previous: dict, record: dict, home: Path | None = None) -> None:
    """Require the new receipt to retain every exact prior managed fragment."""
    validate(previous, home)
    validate(record, home)
    if (previous is None or record is None or previous["path"] != record["path"]
            or previous["prior"] != record["prior"]
            or not set(_fragments(previous)).issubset(set(_fragments(record)))):
        raise ValueError("Controller wait guidance migration lacks historical receipt evidence")


def finish_install(home: Path, transition: dict) -> dict:
    """Journal the field write before applying it; never reacquire after a crash."""
    from . import host_transition
    finish = transition["finish"]
    selected = finish.get("wait_guidance_status", status("LEGACY_UNMANAGED"))
    if selected["status"] not in {"PLANNED", "MIGRATION_PLANNED", "MANAGED"}:
        return selected
    record = finish["wait_guidance_record"]
    previous = finish.get("wait_guidance_previous_record")
    migrate = selected["status"] == "MIGRATION_PLANNED"
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
        if not _matches_current(raw, config, record):
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
            result = (apply_migration(home, previous, record) if migrate
                      else apply(home, record, allow_insert=True))
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
            if not _matches_current(after, config, record):
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
