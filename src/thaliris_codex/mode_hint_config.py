"""One user-config leaf, with durable ownership supplied by Host maintenance.

No file ownership or project config editing. The receipt and transition journal
must be published before applying a plan; an interrupted write can then be replayed.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

KEY = "features.multi_agent_v2.multi_agent_mode_hint_text"
RECORD_KEY = "native_mode_hint"
SUPPORTED_VERSION = "codex-cli 0.162.0-alpha.2"
MARKER = '# thaliris:multi-agent-mode-hint\nmulti_agent_mode_hint_text = ""\n'
BOOL_MARKER = '# thaliris:multi-agent-v2-bool '
BOOL_LINE = r'[ \t]*(?:features\.)?multi_agent_v2[ \t]*=[ \t]*(true|false)[ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)'


def capability() -> str:
    """Only the source-verified CLI version is admitted; newer is not evidence."""
    executable = shutil.which("codex")
    if executable is None:
        return "UNKNOWN"
    try:
        result = subprocess.run([executable, "--version"], capture_output=True,
                                text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return "SUPPORTED" if result.returncode == 0 and result.stdout.strip() == SUPPORTED_VERSION else "UNKNOWN"


def read(home: Path) -> tuple[bytes, dict]:
    from .host_maintenance import safe
    path = home / "config.toml"
    safe(path)
    contents = path.read_bytes() if path.exists() else b""
    return contents, tomllib.loads(contents.decode("utf-8"))


def leaf(config: dict) -> tuple[bool, object]:
    current = config
    for part in KEY.split(".")[:-1]:
        if part not in current:
            return False, None
        current = current[part]
        if part == "multi_agent_v2" and type(current) is bool:
            return False, None
        if not isinstance(current, dict):
            raise ValueError("native mode hint config has a non-table parent; preserve user config")
    return (True, current[KEY.split(".")[-1]]) if KEY.split(".")[-1] in current else (False, None)


def without_leaf(config: dict) -> dict:
    result = deepcopy(config)
    features = result.get("features")
    if isinstance(features, dict) and type(features.get("multi_agent_v2")) is bool:
        features["multi_agent_v2"] = {"enabled": features["multi_agent_v2"]}
    current = result
    parents = []
    for part in KEY.split(".")[:-1]:
        if part not in current:
            return result
        parents.append((current, part))
        current = current[part]
    current.pop(KEY.split(".")[-1], None)
    # Newly created empty tables are scaffolding, not user values.
    for parent, part in reversed(parents):
        if parent[part] == {}:
            del parent[part]
    return result


def validate(record: object, home: Path | None = None) -> None:
    if record is None:
        return
    required = {"path", "prior", "fragment", "leaf_fragment"}
    if not isinstance(record, dict) or set(record) not in (required, required | {"bool_migration"}):
        raise ValueError("invalid native mode hint ownership record")
    if record["prior"] != {"present": False} or not isinstance(record["path"], str):
        raise ValueError("invalid native mode hint prior state")
    if home is not None and record["path"] != str((home / "config.toml").absolute()):
        raise ValueError("native mode hint ownership path differs from CODEX_HOME")
    allowed_leaves = {MARKER, MARKER.replace("\n", "\r\n")}
    if record["leaf_fragment"] not in allowed_leaves:
        raise ValueError("invalid native mode hint owned leaf bytes")
    newline = "\r\n" if "\r\n" in record["leaf_fragment"] else "\n"
    migration = record.get("bool_migration")
    enabled = ""
    if migration is not None:
        if not isinstance(migration, dict) or set(migration) != {"value", "original_line", "placeholder"} or type(migration["value"]) is not bool:
            raise ValueError("invalid native mode hint bool migration")
        original = migration["original_line"]
        if not isinstance(original, str) or re.fullmatch(BOOL_LINE, original) is None:
            raise ValueError("invalid native mode hint original bool bytes")
        document = original if original.lstrip().startswith("features.") else "[features]\n" + original
        if tomllib.loads(document)["features"]["multi_agent_v2"] != migration["value"]:
            raise ValueError("invalid native mode hint original bool bytes")
        if migration["placeholder"] != BOOL_MARKER + original:
            raise ValueError("invalid native mode hint bool placeholder")
        enabled = "enabled = " + str(migration["value"]).lower() + newline
    allowed = (set() if migration else {record["leaf_fragment"], newline + record["leaf_fragment"]}) | {
        prefix + "[features.multi_agent_v2]" + newline + enabled + record["leaf_fragment"]
        for prefix in ("", newline)
    }
    if record["fragment"] not in allowed:
        raise ValueError("invalid native mode hint owned fragment bytes")


def status(name: str, *, changed: bool = False) -> dict:
    return {"status": name, "changed": changed, "key_path": KEY,
            "effective_session_status": "UNKNOWN", "scope": "user config only"}


def matches(raw: bytes, config: dict, record: dict) -> bool:
    """Prove the exact marker/leaf still describes this table's target key."""
    fragment = record["leaf_fragment"].encode()
    try:
        if leaf(config) != (True, "") or raw.count(fragment) != 1:
            return False
        removed = tomllib.loads(raw.replace(fragment, b"", 1).decode("utf-8"))
        return not leaf(removed)[0] and without_leaf(removed) == without_leaf(config)
    except (ValueError, TypeError):
        return False


def plan_install(home: Path, ownership: dict) -> tuple[dict | None, dict]:
    raw, config = read(home)
    record = ownership.get(RECORD_KEY)
    validate(record, home)
    if record is not None:
        return record, status("MANAGED" if matches(raw, config, record) else "USER_CHANGED_PRESERVED")
    present, value = leaf(config)
    if present:
        return None, status("USER_EMPTY_PRESERVED" if value == "" else "USER_CUSTOM_PRESERVED")
    if capability() != "SUPPORTED":
        return None, status("VERSION_SUPPORT_UNKNOWN")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    owned_leaf = MARKER.replace("\n", newline)
    text = raw.decode("utf-8")
    migration = None
    features = config.get("features")
    boolean = features.get("multi_agent_v2") if isinstance(features, dict) else None
    if type(boolean) is bool:
        table = re.search(r"(?m)^\[features\][ \t]*(?:#[^\r\n]*)?\r?\n", text)
        section = text[table.end():] if table else text
        end = re.search(r"(?m)^\s*\[", section)
        section = section[:end.start()] if end else section
        line = re.search("(?m)^" + BOOL_LINE, section)
        if line is None or (not table and not line.group().lstrip().startswith("features.")):
            return None, status("STRUCTURE_UNSUPPORTED_PRESERVED")
        original = line.group()
        migration = {"value": boolean, "original_line": original, "placeholder": BOOL_MARKER + original}
        at = (table.end() if table else 0) + line.start()
        text = text[:at] + migration["placeholder"] + text[at + len(original):]
    # Support ordinary table syntax. Candidate parsing below rejects inline,
    # quoted/dotted and other structures that cannot safely accept this edit.
    header = re.search(r"(?m)^\[features\.multi_agent_v2\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)", text)
    if header:
        fragment = ("" if header.group().endswith("\n") else newline) + owned_leaf
        after = text[:header.end()] + fragment + text[header.end():]
    else:
        enabled = "enabled = " + str(boolean).lower() + newline if migration else ""
        fragment = (newline if raw and not raw.endswith(b"\n") else "") + "[features.multi_agent_v2]" + newline + enabled + owned_leaf
        after = text + fragment
    try:
        parsed = tomllib.loads(after)
    except tomllib.TOMLDecodeError:
        return None, status("STRUCTURE_UNSUPPORTED_PRESERVED")
    if leaf(parsed) != (True, "") or without_leaf(parsed) != without_leaf(config):
        raise ValueError("native mode hint edit would change unrelated config")
    record = {"path": str((home / "config.toml").absolute()), "prior": {"present": False},
              "fragment": fragment, "leaf_fragment": owned_leaf}
    if migration:
        record["bool_migration"] = migration
    return record, status("PLANNED")


def apply(home: Path, record: dict | None, *, remove: bool = False, allow_insert: bool = False) -> dict:
    from .codex_adapter import _atomic_host_write
    validate(record, home)
    if record is None:
        return status("UNMANAGED_PRESERVED")
    raw, config = read(home)
    try:
        present, _ = leaf(config)
    except ValueError:
        return status("USER_CHANGED_PRESERVED")
    owned_leaf = record["leaf_fragment"].encode()
    fragment = record["fragment"].encode()
    migration = record.get("bool_migration")
    matched = matches(raw, config, record)
    if remove:
        if not present:
            return status("ALREADY_ABSENT")
        if not matched:
            return status("USER_CHANGED_PRESERVED")
        candidates = []
        if raw.count(fragment) == 1:
            removed = raw.replace(fragment, b"", 1)
            if migration:
                placeholder = migration["placeholder"].encode()
                if removed.count(placeholder) == 1:
                    candidates.append(removed.replace(placeholder, migration["original_line"].encode(), 1))
            else:
                candidates.append(removed)
        candidates.append(raw.replace(owned_leaf, b"", 1))
        after = None
        for candidate in candidates:
            try:
                parsed = tomllib.loads(candidate.decode("utf-8"))
                if leaf(parsed)[0] is False and without_leaf(parsed) == without_leaf(config):
                    after = candidate
                    break
            except (ValueError, TypeError):
                continue
        if after is None:
            return status("USER_CHANGED_PRESERVED")
    else:
        if matched:
            return status("MANAGED")
        if present or not allow_insert:
            return status("USER_CHANGED_PRESERVED")
        # A record of a previously managed leaf must never reacquire a deleted
        # user value. Only a new PLANNED transition calls this insertion path.
        text = raw.decode("utf-8")
        if migration:
            original = migration["original_line"].encode()
            if raw.count(original) != 1:
                return status("USER_CHANGED_PRESERVED")
            raw_for_insert = raw.replace(original, migration["placeholder"].encode(), 1)
        else:
            raw_for_insert = raw
        if fragment in {owned_leaf, b"\n" + owned_leaf, b"\r\n" + owned_leaf}:
            header = re.search(r"(?m)^\[features\.multi_agent_v2\][ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)", text)
            if header is None:
                return status("USER_CHANGED_PRESERVED")
            after = raw[:len(text[:header.end()].encode())] + fragment + raw[len(text[:header.end()].encode()):]
        else:
            after = raw_for_insert + fragment
        try:
            parsed = tomllib.loads(after.decode("utf-8"))
        except ValueError:
            return status("USER_CHANGED_PRESERVED")
        if leaf(parsed) != (True, "") or without_leaf(parsed) != without_leaf(config):
            return status("USER_CHANGED_PRESERVED")
    # Optimistic recheck immediately before atomic replacement. We own only the
    # fragment; no config snapshot is used by generation rollback.
    if read(home)[0] != raw:
        raise ValueError("native mode hint config changed before field write")
    _atomic_host_write(home / "config.toml", after)
    if read(home)[0] != after:
        raise ValueError("native mode hint field write could not be verified")
    preserved_structure = remove and migration and isinstance(parsed.get("features", {}).get("multi_agent_v2"), dict)
    restored = "RESTORED_ABSENT_STRUCTURE_PRESERVED" if preserved_structure else "RESTORED_ABSENT"
    return status(restored if remove else "MANAGED", changed=True)


def finish_install(home: Path, transition: dict) -> dict:
    """Checkpoint write intent before the leaf, never reacquire after a crash.

    An interrupted attempt with no owned fragment has an unknown outcome. Do
    not mistake a user deletion for a failed write and silently insert again.
    Ordinary observed write failures can safely reset for a retry.
    """
    from . import host_transition
    finish = transition["finish"]
    selected = finish.get("mode_hint_status", status("LEGACY_UNMANAGED"))
    if selected["status"] not in {"PLANNED", "MANAGED"}:
        return selected
    record = finish["mode_hint_record"]
    if selected["status"] == "MANAGED":
        return apply(home, record)
    phase = finish.get("mode_hint_phase")
    if phase == "APPLIED":
        current = apply(home, record)
        # Report the already observed write while preserving later edits.
        current["changed"] = finish["mode_hint_result"]["changed"]
        return current
    if phase == "ATTEMPTING":
        raw, config = read(home)
        if not matches(raw, config, record):
            return status("APPLY_OUTCOME_UNKNOWN_PRESERVED")
        result = status("MANAGED", changed=True)
    else:
        before, _ = read(home)
        finish["mode_hint_phase"] = "ATTEMPTING"
        host_transition._write(home, transition)
        try:
            result = apply(home, record, allow_insert=True)
        except (OSError, ValueError, RuntimeError):
            # A caught error and exact unchanged bytes prove no edit took place;
            # a process interruption provides no such observation.
            if read(home)[0] == before:
                finish.pop("mode_hint_phase", None)
                host_transition._write(home, transition)
            raise
    finish["mode_hint_phase"] = "APPLIED"
    finish["mode_hint_result"] = result
    host_transition._write(home, transition)
    return result
