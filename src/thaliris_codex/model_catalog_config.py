"""Exact catalog surgery and receipt-owned, Host-global catalog configuration.

Refresh is an explicit maintenance operation, never a runtime hook or service.
The exporter must exclude this override and establish freshness independently.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from . import wait_guidance_config as field

KEY = "model_catalog_json"
RECORD_KEY = "native_model_catalog"
NAME = "thaliris-model-catalog.json"
MARKER = "# thaliris:model-catalog\n"
TARGET = "- Avoid performing blocking sleep or wait calls longer than 60 seconds, as they may prevent you from communicating with the user for their duration."
_CLI_VERSION_PATTERN = re.compile(
    r"^codex-cli (0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_MULTILINE_PREVIOUS = (
    "- For multiline PR descriptions, issue bodies, and comments, prefer a structured tool argument. "
    "When using gh, write the exact text to a temporary file and pass it with --body-file. "
    "Preserve actual newlines and intentional literal escapes."
)
_ESCAPING_PREVIOUS = (
    "- Exercise caution when escaping text for exec_command calls - backticks and \x60$()\x60 "
    "passed to the \x60cmd\x60 argument will still execute. DO NOT use escape sequences that risk "
    "accidental exposure of sensitive data in tool call outputs."
)
_NEXT = (
    "- When declaring env vars or script variables, always avoid common system options. "
    "Never repurpose \x60$HOME\x60, \x60$home\x60, or \x60$CODEX_HOME\x60. "
    "Instead, use a task-specific variable name."
)
_MODEL_PROFILES = {
    "online": {
        "matched": frozenset({
            "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna",
            "gpt-reserve", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
            "codex-auto-review",
        }),
        "absent": frozenset({"gpt-5.5"}),
    },
    "bundled": {
        "matched": frozenset({
            "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna",
            "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
            "gpt-daybreak-blue-latest", "gpt-daybreak-red-latest",
            "codex-auto-review",
        }),
        "absent": frozenset({"gpt-5.5"}),
    },
}
_KNOWN_TARGET_CONTEXT = {
    "gpt-6-astra": (_MULTILINE_PREVIOUS, _NEXT),
    "gpt-6.1-sol": (_MULTILINE_PREVIOUS, _NEXT),
    "gpt-6-sol": (_MULTILINE_PREVIOUS, _NEXT),
    "gpt-6-luna": (_MULTILINE_PREVIOUS, _NEXT),
    "gpt-reserve": (_ESCAPING_PREVIOUS, _NEXT),
    "gpt-5.6-sol": (_ESCAPING_PREVIOUS, _NEXT),
    "gpt-5.6-terra": (_ESCAPING_PREVIOUS, _NEXT),
    "gpt-5.6-luna": (_ESCAPING_PREVIOUS, _NEXT),
    "gpt-daybreak-blue-latest": (_ESCAPING_PREVIOUS, _NEXT),
    "gpt-daybreak-red-latest": (_ESCAPING_PREVIOUS, _NEXT),
    "codex-auto-review": (_ESCAPING_PREVIOUS, _NEXT),
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def cache_client_version(cli_version: str) -> str | None:
    """Return the cache's whole CLI version, which omits prerelease labels."""
    match = _CLI_VERSION_PATTERN.fullmatch(cli_version.strip())
    return ".".join(match.group(index) for index in (1, 2, 3)) if match else None


def status(name: str, *, changed: bool = False, **facts) -> dict:
    return {"status": name, "changed": changed, "key_path": KEY,
            "scope": "Host-global model catalog", "effective_session_status": "UNKNOWN",
            "online_freshness": "UNKNOWN", **facts}


def patch_catalog(raw: bytes, *, cli_version: str | None = None,
                  source: str | None = None) -> tuple[bytes | None, dict]:
    """Remove the target only from compatible model templates.

    The source-specific model roster and adjacent target lines form the
    compatibility contract. CLI version strings are recorded as provenance,
    but the catalog itself determines whether the capability is present. New
    models are accepted only with one exact full-line target; present known
    models must retain their observed target context.
    """
    try:
        catalog = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, status("CATALOG_JSON_UNSUPPORTED", error=str(exc))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("models"), list) or not catalog["models"]:
        return None, status("CATALOG_SCHEMA_UNSUPPORTED")
    patched = deepcopy(catalog)
    count = 0
    profile = None
    if source is not None:
        profile = _MODEL_PROFILES.get(source)
        if profile is None:
            return None, status("CATALOG_PROFILE_UNKNOWN", cli_version=cli_version, source=source)
    elif cli_version is not None:
        return None, status("CATALOG_PROFILE_UNKNOWN", cli_version=cli_version, source=source)
    known_absent = profile["absent"] if profile else frozenset()
    known_matched = profile["matched"] if profile else frozenset()
    seen_slugs: set[str] = set()
    template_statuses = {"EXACT_MATCH": 0, "KNOWN_ABSENT": 0}
    for model in patched["models"]:
        if not isinstance(model, dict):
            return None, status("MODEL_SCHEMA_UNSUPPORTED")
        slug = model.get("slug")
        if not isinstance(slug, str) or not slug:
            return None, status("MODEL_IDENTITY_UNSUPPORTED")
        if slug in seen_slugs:
            return None, status("DUPLICATE_MODEL_IDENTITY", model_slug=slug)
        seen_slugs.add(slug)
        messages = model.get("model_messages")
        if not isinstance(messages, dict) or "instructions_template" not in messages:
            return None, status("MODEL_TEMPLATE_UNSUPPORTED", model_slug=slug)
        template = messages["instructions_template"]
        if not isinstance(template, str):
            return None, status("MODEL_TEMPLATE_UNSUPPORTED", model_slug=slug)
        occurrences = template.count(TARGET)
        if slug in known_absent:
            if occurrences:
                return None, status("KNOWN_ABSENT_MODEL_CHANGED", model_slug=slug)
            template_statuses["KNOWN_ABSENT"] += 1
            continue
        if occurrences > 1:
            return None, status("TARGET_MULTIPLE_MATCHES", model_slug=slug)
        if occurrences == 1:
            lines = template.splitlines(keepends=True)
            match_indexes = [index for index, line in enumerate(lines)
                             if line.rstrip("\r\n") == TARGET]
            if len(match_indexes) != 1:
                return None, status("TARGET_CHANGED_OR_EMBEDDED", model_slug=slug)
            target_index = match_indexes[0]
            if slug in known_matched:
                neighbors = (
                    lines[target_index - 1].rstrip("\r\n") if target_index else None,
                    lines[target_index + 1].rstrip("\r\n") if target_index + 1 < len(lines) else None,
                )
                if neighbors != _KNOWN_TARGET_CONTEXT[slug]:
                    return None, status("TARGET_LOCATION_CHANGED", model_slug=slug)
            messages["instructions_template"] = "".join(
                line for index, line in enumerate(lines) if index != target_index
            )
            count += 1
            template_statuses["EXACT_MATCH"] += 1
        else:
            return None, status("TARGET_ABSENT_UNEXPECTED", model_slug=slug)
    if not count:
        return None, status("NO_COMPATIBLE_TARGETS")
    return (json.dumps(patched, ensure_ascii=False, indent=2) + "\n").encode(), status("COMPATIBLE", patched_templates=count, template_statuses=template_statuses)


def fragment(home: Path, newline: str) -> str:
    return newline + MARKER.replace("\n", newline) + KEY + " = " + json.dumps(str((home / NAME).absolute())) + newline


def validate(record: object, home: Path | None = None) -> None:
    if record is None:
        return
    if not isinstance(record, dict) or set(record) != {"path", "catalog_path", "prior", "fragment", "catalog_sha256", "source"}:
        raise ValueError("invalid model catalog ownership record")
    if record["prior"] != {"present": False} or not all(isinstance(record[k], str) for k in ("path", "catalog_path", "fragment", "catalog_sha256")):
        raise ValueError("invalid model catalog ownership fields")
    if not re.fullmatch(r"[0-9a-f]{64}", record["catalog_sha256"]):
        raise ValueError("invalid model catalog byte identity")
    catalog_path = Path(record["catalog_path"])
    expected_home = catalog_path.parent
    if catalog_path.name != NAME or not catalog_path.is_absolute() or record["path"] != str(expected_home / "config.toml"):
        raise ValueError("invalid model catalog ownership paths")
    if home is not None and expected_home != home.absolute():
        raise ValueError("model catalog ownership differs from CODEX_HOME")
    if record["fragment"] not in (fragment(expected_home, "\n"), fragment(expected_home, "\r\n")):
        raise ValueError("invalid model catalog owned fragment")
    source = record["source"]
    if not isinstance(source, dict) or source.get("kind") not in {"bundled", "online"} or not isinstance(source.get("cli_version"), str) or not re.fullmatch(r"[0-9a-f]{64}", source.get("upstream_sha256", "")):
        raise ValueError("invalid model catalog upstream provenance")


def matches(raw: bytes, config: dict, record: dict) -> bool:
    frag = record["fragment"].encode()
    if config.get(KEY) != record["catalog_path"] or raw.count(frag) != 1:
        return False
    import tomllib
    return KEY not in tomllib.loads(raw.replace(frag, b"", 1).decode())


def read_catalog(home: Path) -> bytes | None:
    from .host_maintenance import safe
    path = home / NAME
    safe(path)
    return path.read_bytes() if path.exists() else None


def read(home: Path) -> tuple[bytes, dict]:
    from .host_maintenance import safe
    import tomllib
    path = home / "config.toml"
    safe(path)
    raw = path.read_bytes() if path.exists() else b""
    return raw, tomllib.loads(raw.decode("utf-8"))


def export_upstream(home: Path, *, source: str = "online") -> tuple[bytes, dict]:
    """Export from the CLI, never this installation's patched catalog.

    Some CLI releases swallow refresh errors. A newly created isolated cache,
    consistent with stdout and the CLI's whole-version cache key, is required
    as network evidence.
    No cache and no original managed catalog enters the disposable CODEX_HOME.
    Provider/auth config is preserved; unsupported credential stores stay unknown.
    """
    from .host_maintenance import safe
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError("VERSION_SUPPORT_UNKNOWN")
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("VERSION_SUPPORT_UNKNOWN") from exc
    cli_version = version.stdout.decode("utf-8", "replace").strip()
    cache_version = cache_client_version(cli_version)
    if version.returncode != 0 or cache_version is None:
        raise ValueError("VERSION_SUPPORT_UNKNOWN")
    if source not in {"online", "bundled"}:
        raise ValueError("unsupported model catalog source")
    raw, config = read(home)
    if source == "online":
        # This entrypoint can also be called independently. Strip a root leaf
        # only with its durable exact receipt, never erase an arbitrary override.
        if KEY in config:
            receipt_path = home / "thaliris-ownership.json"
            safe(receipt_path)
            receipt = json.loads(receipt_path.read_bytes()) if receipt_path.exists() else {}
            owned = receipt.get(RECORD_KEY)
            validate(owned, home)
            if owned is None or not matches(raw, config, owned):
                raise ValueError("CUSTOM_CATALOG_SOURCE_UNSUPPORTED")
            raw = raw.replace(owned["fragment"].encode(), b"", 1)
        import tomllib
        sanitized = tomllib.loads(raw.decode())
        def has_override(value):
            return isinstance(value, dict) and (KEY in value or any(has_override(item) for item in value.values()))
        if has_override(sanitized):
            raise ValueError("PROFILE_CATALOG_SOURCE_UNSUPPORTED")
        # External auth/remote cache paths cannot be isolated by copying config.
        # They require separate provider support rather than silent substitution.
        if sanitized.get("cli_auth_credentials_store", "file") != "file":
            raise ValueError("AUTH_STORE_SOURCE_UNSUPPORTED")
    cli_hash = digest(Path(executable).read_bytes())
    with tempfile.TemporaryDirectory(prefix="thaliris-catalog-export-") as directory:
        isolated = Path(directory).absolute()
        env = os.environ.copy()
        env["CODEX_HOME"] = str(isolated)
        if source == "online":
            (isolated / "config.toml").write_bytes(raw)
            auth = home / "auth.json"
            safe(auth)
            if auth.exists():
                # Disposable private state, never a repository or logged payload.
                shutil.copyfile(auth, isolated / "auth.json")
        started = datetime.now(timezone.utc)
        args = [executable, "debug", "models"] + (["--bundled"] if source == "bundled" else [])
        try:
            result = subprocess.run(args, cwd=isolated, env=env, capture_output=True, timeout=90, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("UPSTREAM_EXPORT_FAILED") from exc
        if result.returncode != 0:
            raise ValueError("UPSTREAM_EXPORT_FAILED")
        exported = json.loads(result.stdout)
        if not isinstance(exported, dict) or not isinstance(exported.get("models"), list) or not exported["models"]:
            raise ValueError("UPSTREAM_EXPORT_SHAPE_UNSUPPORTED")
        if source == "online":
            cache_path = isolated / "models_cache.json"
            if not cache_path.exists():
                raise ValueError("ONLINE_FRESHNESS_UNVERIFIED")
            cache = json.loads(cache_path.read_bytes())
            if not isinstance(cache, dict) or not isinstance(cache.get("fetched_at"), str):
                raise ValueError("ONLINE_FRESHNESS_UNVERIFIED")
            fetched = datetime.fromisoformat(cache.get("fetched_at", "").replace("Z", "+00:00"))
            if (fetched.tzinfo is None or fetched < started or fetched > datetime.now(timezone.utc)
                    or cache.get("client_version") != cache_version or not isinstance(cache.get("identity"), str)
                    or not cache["identity"] or not isinstance(cache.get("models"), list) or not cache["models"]):
                raise ValueError("ONLINE_FRESHNESS_UNVERIFIED")
            # Models manager fills omitted instruction fields from the binary;
            # cache must still identify models present in the exported catalog.
            output_models = {model.get("slug"): model for model in exported["models"] if isinstance(model, dict)}
            for model in cache["models"]:
                if not isinstance(model, dict) or model.get("slug") not in output_models:
                    raise ValueError("ONLINE_CACHE_EXPORT_MISMATCH")
                cached_messages = model.get("model_messages")
                cached_template = cached_messages.get("instructions_template") if isinstance(cached_messages, dict) else None
                output_messages = output_models[model["slug"]].get("model_messages")
                output_template = output_messages.get("instructions_template") if isinstance(output_messages, dict) else None
                if cached_template is not None and cached_template != output_template:
                    raise ValueError("ONLINE_CACHE_EXPORT_MISMATCH")
        if digest(Path(executable).read_bytes()) != cli_hash:
            raise ValueError("CLI_CHANGED_DURING_EXPORT")
        return result.stdout, {"kind": source, "cli_version": cli_version, "cli_sha256": cli_hash,
                               "online_freshness": "VERIFIED" if source == "online" else "UNKNOWN"}


def plan_install(home: Path, ownership: dict, *, source: str = "online") -> tuple[dict | None, dict, bytes | None]:
    original_record = ownership.get(RECORD_KEY)
    validate(original_record, home)
    record = original_record
    retained_backing_reclaimed = False
    restored_field_reacquired = False
    if source not in {"online", "bundled"}:
        raise ValueError("model catalog source must be online or explicitly bundled")
    if original_record and original_record["source"]["kind"] == "online" and source == "bundled":
        return original_record, status("SOURCE_DOWNGRADE_PRESERVED"), None
    try:
        raw, config = read(home)
        current = read_catalog(home)
    except (OSError, ValueError):
        return original_record, status("OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED"), None
    if original_record:
        if matches(raw, config, original_record) and current is not None and digest(current) == original_record["catalog_sha256"]:
            record = original_record
        elif KEY not in config and current is not None:
            from . import catalog_recovery
            policy = ownership.get(catalog_recovery.POLICY_KEY)
            try:
                catalog_recovery.validate_policy(policy)
                retained = catalog_recovery.retained_record(home)
            except (OSError, ValueError, RuntimeError, TypeError, KeyError):
                retained = None
            if (isinstance(policy, dict) and policy.get("restored") is True and
                    retained == original_record and digest(current) == original_record["catalog_sha256"]):
                record = original_record
                restored_field_reacquired = True
            else:
                return original_record, status("USER_CHANGED_PRESERVED"), None
        else:
            return original_record, status("USER_CHANGED_PRESERVED"), None
    elif KEY in config:
        return None, status("USER_CONFIG_PRESERVED"), None
    elif current is not None:
        from . import catalog_recovery
        try:
            retained = catalog_recovery.retained_record(home)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError):
            retained = None
        if retained is None:
            return None, status("USER_CATALOG_PRESERVED"), None
        try:
            validate(retained, home)
        except (ValueError, TypeError, KeyError):
            return None, status("USER_CATALOG_PRESERVED"), None
        if digest(current) != retained["catalog_sha256"]:
            return None, status("USER_CATALOG_PRESERVED"), None
        record = retained
        retained_backing_reclaimed = True
    try:
        upstream, evidence = export_upstream(home, source=source)
        if evidence.get("kind") != source:
            raise ValueError("model catalog export source differs from selected maintenance source")
        cli_version = evidence.get("cli_version")
        patched, compatibility = patch_catalog(upstream, cli_version=cli_version, source=source)
    except (OSError, ValueError, RuntimeError) as exc:
        result_status = "VERSION_SUPPORT_UNKNOWN" if str(exc) == "VERSION_SUPPORT_UNKNOWN" else "UPSTREAM_REFRESH_FAILED_PRESERVED"
        return original_record, status(result_status, error=str(exc)), None
    if patched is None:
        return original_record, status("TEMPLATE_INCOMPATIBILITY_PRESERVED", template_compatibility=compatibility), None
    newline = "\r\n" if b"\r\n" in raw else "\n"
    updated = {"path": str((home / "config.toml").absolute()), "catalog_path": str((home / NAME).absolute()),
               "prior": {"present": False}, "fragment": record["fragment"] if record else fragment(home, newline),
               "catalog_sha256": digest(patched), "source": evidence | {"upstream_sha256": digest(upstream)}}
    validate(updated, home)
    if retained_backing_reclaimed:
        planned_status = "PLANNED"
    elif restored_field_reacquired:
        planned_status = "UPDATE_PLANNED"
    else:
        planned_status = "MANAGED" if record and patched == current else "UPDATE_PLANNED" if record else "PLANNED"
    facts = {"source": updated["source"], "template_compatibility": compatibility}
    if retained_backing_reclaimed:
        facts["retained_backing_reclaimed"] = True
    if restored_field_reacquired:
        facts["restored_field_reacquired"] = True
    return updated, status(planned_status, **facts), patched


def apply(home: Path, record: dict | None, *, remove=False, allow_insert=False) -> dict:
    from .codex_adapter import _atomic_host_write
    import tomllib
    validate(record, home)
    if record is None:
        return status("LEGACY_UNMANAGED")
    raw, config = read(home)
    matched = matches(raw, config, record)
    if remove:
        if KEY not in config:
            return status("ALREADY_ABSENT")
        if not matched:
            return status("USER_CHANGED_PRESERVED")
        after = raw.replace(record["fragment"].encode(), b"", 1)
    else:
        current = read_catalog(home)
        if current is None or digest(current) != record["catalog_sha256"]:
            return status("CATALOG_CHANGED_PRESERVED")
        if matched:
            return status("MANAGED", source=record["source"], online_freshness="VERIFIED" if record["source"]["kind"] == "online" else "UNKNOWN")
        if KEY in config or not allow_insert:
            return status("USER_CHANGED_PRESERVED")
        after = field._insert(raw, record["fragment"].encode())
        if not matches(after, tomllib.loads(after.decode()), record):
            return status("STRUCTURE_UNSUPPORTED_PRESERVED")
    if read(home)[0] != raw:
        raise ValueError("model catalog config changed before field write")
    _atomic_host_write(home / "config.toml", after)
    if read(home)[0] != after:
        raise ValueError("model catalog config write verification failed")
    return status("RESTORED_ABSENT" if remove else "MANAGED", changed=True, source=record["source"], online_freshness="VERIFIED" if record["source"]["kind"] == "online" else "UNKNOWN")


def finish_install(home: Path, transition: dict) -> dict:
    from . import host_transition
    finish = transition["finish"]
    selected = finish.get("model_catalog_status", status("LEGACY_UNMANAGED"))
    if selected["status"] not in {"PLANNED", "UPDATE_PLANNED", "MANAGED"}:
        return selected
    record = finish["model_catalog_record"]
    def report(result):
        if "template_compatibility" in selected:
            result["template_compatibility"] = selected["template_compatibility"]
        return result
    needs_insert = (
        selected["status"] == "PLANNED" or
        selected.get("retained_backing_reclaimed") is True or
        selected.get("restored_field_reacquired") is True
    )
    if not needs_insert:
        return report(apply(home, record))
    phase = finish.get("model_catalog_phase")
    if phase in {"ATTEMPTING", "APPLIED"}:
        result = apply(home, record)
        if result["status"] != "MANAGED":
            return status("APPLY_OUTCOME_UNKNOWN_PRESERVED")
        result["changed"] = True
        return report(result)
    finish["model_catalog_phase"] = "ATTEMPTING"
    host_transition._write(home, transition)
    result = apply(home, record, allow_insert=True)
    finish["model_catalog_phase"] = "APPLIED"
    finish["model_catalog_result"] = result
    host_transition._write(home, transition)
    return report(result)


def validate_transition(finish: dict, previous: dict, next_record: dict | None, before: dict, after: dict, home: Path, *, install: bool) -> None:
    old = previous.get(RECORD_KEY)
    validate(old, home)
    if "model_catalog_record" not in finish:
        if NAME in before:
            raise ValueError("unrecorded model catalog transition")
        return
    new = finish["model_catalog_record"]
    validate(new, home)
    if new != (next_record if install else old):
        raise ValueError("model catalog journal differs from ownership receipt")
    if not install:
        if after.get(NAME) is None and before.get(NAME) is not None and (old is None or digest(before[NAME]) != old["catalog_sha256"]):
            raise ValueError("uninstall catalog lacks exact ownership")
        return
    selected = finish.get("model_catalog_status", {}).get("status")
    allowed = {"PLANNED", "UPDATE_PLANNED", "MANAGED", "USER_CHANGED_PRESERVED", "USER_CONFIG_PRESERVED", "USER_CATALOG_PRESERVED", "OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED", "UPSTREAM_REFRESH_FAILED_PRESERVED", "TARGET_MULTIPLE_MATCHES", "TARGET_CHANGED_OR_EMBEDDED", "TARGET_ABSENT", "TEMPLATE_INCOMPATIBILITY_PRESERVED", "SOURCE_DOWNGRADE_PRESERVED", "VERSION_SUPPORT_UNKNOWN"}
    if selected not in allowed:
        raise ValueError("invalid model catalog planning status")
    status_record = finish.get("model_catalog_status", {})
    reclaimed = status_record.get("retained_backing_reclaimed") is True
    restored = status_record.get("restored_field_reacquired") is True
    if selected in {"PLANNED", "UPDATE_PLANNED", "MANAGED"}:
        if finish.get("model_catalog_status", {}).get("template_compatibility", {}).get("status") in {
                "TARGET_ABSENT", "TARGET_ABSENT_UNEXPECTED", "KNOWN_ABSENT_MODEL_CHANGED",
                "TARGET_MULTIPLE_MATCHES", "TARGET_CHANGED_OR_EMBEDDED", "MODEL_IDENTITY_UNSUPPORTED",
                "MODEL_TEMPLATE_UNSUPPORTED", "DUPLICATE_MODEL_IDENTITY", "NO_COMPATIBLE_TARGETS",
                "TARGET_LOCATION_CHANGED", "CATALOG_PROFILE_UNKNOWN",
                "CATALOG_JSON_UNSUPPORTED", "CATALOG_SCHEMA_UNSUPPORTED", "MODEL_SCHEMA_UNSUPPORTED"}:
            raise ValueError("incompatible model catalog template cannot be managed")
        if new is None or after.get(NAME) is None or digest(after[NAME]) != new["catalog_sha256"]:
            raise ValueError("model catalog transition lacks exact planned catalog")
        if reclaimed:
            if (selected != "PLANNED" or restored or old is not None or before.get(NAME) is None or
                    not _config_field_absent(before.get("config.toml", b""))):
                raise ValueError("invalid retained model catalog reclaim")
            from . import catalog_recovery
            retained = catalog_recovery.retained_record(home, before[NAME])
            if (retained is None or
                    any(new[key] != retained[key] for key in ("path", "catalog_path", "prior", "fragment"))):
                raise ValueError("retained model catalog archive does not prove the prior artifact")
        elif selected == "PLANNED" and (old is not None or before.get(NAME) is not None):
            raise ValueError("model catalog transition cannot reacquire ownership")
        if restored:
            from . import catalog_recovery
            policy = previous.get(catalog_recovery.POLICY_KEY)
            if (selected != "UPDATE_PLANNED" or old is None or not isinstance(policy, dict) or
                    policy.get("restored") is not True or
                    before.get(NAME) is None or digest(before[NAME]) != old["catalog_sha256"] or
                    any(new[key] != old[key] for key in ("path", "catalog_path", "prior", "fragment")) or
                    not _config_field_absent(before.get("config.toml", b""))):
                raise ValueError("restored model catalog field lacks exact recovery provenance")
        if reclaimed and restored:
            raise ValueError("conflicting retained catalog recovery markers")
        if selected == "UPDATE_PLANNED" and (old is None or before.get(NAME) is None or digest(before[NAME]) != old["catalog_sha256"] or new["fragment"] != old["fragment"]):
            raise ValueError("model catalog update lacks prior owned bytes")
        if selected == "MANAGED" and (old is None or before.get(NAME) != after.get(NAME) or new["fragment"] != old["fragment"]):
            raise ValueError("managed model catalog lacks unchanged owned generation")
    elif before.get(NAME) != after.get(NAME):
        raise ValueError("preserved model catalog transition changes bytes")
    elif new != old:
        raise ValueError("preserved model catalog transition changes ownership")
    insert_planned = selected == "PLANNED" or reclaimed or restored
    if "model_catalog_phase" in finish and (not insert_planned or finish["model_catalog_phase"] not in {"ATTEMPTING", "APPLIED"}):
        raise ValueError("invalid model catalog field write phase")
    if finish.get("model_catalog_phase") == "APPLIED" and (not isinstance(finish.get("model_catalog_result"), dict) or type(finish["model_catalog_result"].get("changed")) is not bool or finish["model_catalog_result"].get("status") not in {"MANAGED", "USER_CHANGED_PRESERVED", "CATALOG_CHANGED_PRESERVED", "STRUCTURE_UNSUPPORTED_PRESERVED"}):
        raise ValueError("invalid model catalog field write result")


def _config_field_absent(raw: bytes) -> bool:
    import tomllib
    return KEY not in tomllib.loads(raw.decode("utf-8"))
