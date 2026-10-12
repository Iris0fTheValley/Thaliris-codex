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
SUPPORTED_VERSIONS = frozenset({"codex-cli 0.162.0-alpha.17.2"})


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def status(name: str, *, changed: bool = False, **facts) -> dict:
    return {"status": name, "changed": changed, "key_path": KEY,
            "scope": "Host-global model catalog", "effective_session_status": "UNKNOWN",
            "online_freshness": "UNKNOWN", **facts}


def patch_catalog(raw: bytes) -> tuple[bytes | None, dict]:
    """Preserve every other JSON value, including models unknown to this adapter."""
    catalog = json.loads(raw)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("models"), list) or not catalog["models"]:
        raise ValueError("unsupported model catalog shape")
    patched = deepcopy(catalog)
    count = 0
    template_statuses = {"EXACT_MATCH": 0, "TARGET_ABSENT": 0, "TEMPLATE_ABSENT": 0}
    for model in patched["models"]:
        if not isinstance(model, dict):
            raise ValueError("unsupported model catalog model")
        messages = model.get("model_messages")
        if not isinstance(messages, dict) or messages.get("instructions_template") is None:
            template_statuses["TEMPLATE_ABSENT"] += 1
            continue
        template = messages["instructions_template"]
        if not isinstance(template, str):
            raise ValueError("unsupported model instructions template")
        occurrences = template.count(TARGET)
        if occurrences > 1:
            return None, status("TARGET_MULTIPLE_MATCHES")
        if occurrences == 1:
            lines = template.splitlines(keepends=True)
            matches = [line for line in lines if line.rstrip("\r\n") == TARGET]
            if len(matches) != 1:
                return None, status("TARGET_CHANGED_OR_EMBEDDED")
            messages["instructions_template"] = "".join(line for line in lines if line != matches[0])
            count += 1
            template_statuses["EXACT_MATCH"] += 1
        else:
            template_statuses["TARGET_ABSENT"] += 1
    if not count:
        return None, status("TARGET_ABSENT")
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
    """Export from the admitted CLI, never this installation's patched catalog.

    0.162.0-alpha.17.2 normal exports swallow refresh errors. A newly created
    isolated cache, consistent with stdout, is required as network evidence.
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
    cli_version = version.stdout.decode("utf-8").strip()
    if version.returncode != 0 or cli_version not in SUPPORTED_VERSIONS:
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
                    or cache.get("client_version") != "0.162.0" or not isinstance(cache.get("identity"), str)
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
    record = ownership.get(RECORD_KEY)
    validate(record, home)
    if source not in {"online", "bundled"}:
        raise ValueError("model catalog source must be online or explicitly bundled")
    if record and record["source"]["kind"] == "online" and source == "bundled":
        return record, status("SOURCE_DOWNGRADE_PRESERVED"), None
    try:
        raw, config = read(home)
        current = read_catalog(home)
    except (OSError, ValueError):
        return record, status("OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED"), None
    if record:
        if not matches(raw, config, record) or current is None or digest(current) != record["catalog_sha256"]:
            return record, status("USER_CHANGED_PRESERVED"), None
    elif KEY in config:
        return None, status("USER_CONFIG_PRESERVED"), None
    elif current is not None:
        return None, status("USER_CATALOG_PRESERVED"), None
    try:
        upstream, evidence = export_upstream(home, source=source)
        if evidence.get("kind") != source:
            raise ValueError("model catalog export source differs from selected maintenance source")
        patched, compatibility = patch_catalog(upstream)
    except (OSError, ValueError, RuntimeError) as exc:
        result_status = "VERSION_SUPPORT_UNKNOWN" if str(exc) == "VERSION_SUPPORT_UNKNOWN" else "UPSTREAM_REFRESH_FAILED_PRESERVED"
        return record, status(result_status, error=str(exc)), None
    if patched is None:
        if record is not None and compatibility["status"] == "TARGET_ABSENT":
            # Fresh upstream already removed the sentence. Keep the managed
            # catalog current byte-for-byte, without inventing replacement text.
            patched = upstream
        else:
            return record, compatibility, None
    newline = "\r\n" if b"\r\n" in raw else "\n"
    updated = {"path": str((home / "config.toml").absolute()), "catalog_path": str((home / NAME).absolute()),
               "prior": {"present": False}, "fragment": record["fragment"] if record else fragment(home, newline),
               "catalog_sha256": digest(patched), "source": evidence | {"upstream_sha256": digest(upstream)}}
    validate(updated, home)
    return updated, status("MANAGED" if record and patched == current else "UPDATE_PLANNED" if record else "PLANNED", source=updated["source"], template_compatibility=compatibility), patched


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
            if result["status"] == "MANAGED" and selected["template_compatibility"]["status"] == "TARGET_ABSENT":
                result["status"] = "TARGET_ABSENT_MANAGED"
        return result
    if selected["status"] != "PLANNED":
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
    allowed = {"PLANNED", "UPDATE_PLANNED", "MANAGED", "USER_CHANGED_PRESERVED", "USER_CONFIG_PRESERVED", "USER_CATALOG_PRESERVED", "OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED", "UPSTREAM_REFRESH_FAILED_PRESERVED", "TARGET_MULTIPLE_MATCHES", "TARGET_CHANGED_OR_EMBEDDED", "TARGET_ABSENT", "SOURCE_DOWNGRADE_PRESERVED", "VERSION_SUPPORT_UNKNOWN"}
    if selected not in allowed:
        raise ValueError("invalid model catalog planning status")
    if selected in {"PLANNED", "UPDATE_PLANNED", "MANAGED"}:
        if new is None or after.get(NAME) is None or digest(after[NAME]) != new["catalog_sha256"]:
            raise ValueError("model catalog transition lacks exact planned catalog")
        if selected == "PLANNED" and (old is not None or before.get(NAME) is not None):
            raise ValueError("model catalog transition cannot reacquire ownership")
        if selected == "UPDATE_PLANNED" and (old is None or before.get(NAME) is None or digest(before[NAME]) != old["catalog_sha256"] or new["fragment"] != old["fragment"]):
            raise ValueError("model catalog update lacks prior owned bytes")
        if selected == "MANAGED" and (old is None or before.get(NAME) != after.get(NAME) or new["fragment"] != old["fragment"]):
            raise ValueError("managed model catalog lacks unchanged owned generation")
        if finish.get("model_catalog_status", {}).get("template_compatibility", {}).get("status") == "TARGET_ABSENT" and new["catalog_sha256"] != new["source"]["upstream_sha256"]:
            raise ValueError("absent-target model catalog must equal fresh upstream bytes")
    elif before.get(NAME) != after.get(NAME):
        raise ValueError("preserved model catalog transition changes bytes")
    elif new != old:
        raise ValueError("preserved model catalog transition changes ownership")
    if "model_catalog_phase" in finish and (selected != "PLANNED" or finish["model_catalog_phase"] not in {"ATTEMPTING", "APPLIED"}):
        raise ValueError("invalid model catalog field write phase")
    if finish.get("model_catalog_phase") == "APPLIED" and (not isinstance(finish.get("model_catalog_result"), dict) or type(finish["model_catalog_result"].get("changed")) is not bool or finish["model_catalog_result"].get("status") not in {"MANAGED", "USER_CHANGED_PRESERVED", "CATALOG_CHANGED_PRESERVED", "STRUCTURE_UNSUPPORTED_PRESERVED"}):
        raise ValueError("invalid model catalog field write result")
