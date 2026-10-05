"""Host-scoped, explicitly selected maintenance intent and installation ownership.

These records are governance on a shared OS, not human authentication. Runtime
reproducibility is a consistency check and never supplies intent or ownership.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import runtime_identity

RECEIPT_NAME = "thaliris-ownership.json"
FORMAT = "thaliris-host-maintenance-v1"
RECEIPT_FORMAT = "thaliris-authorized-host-installation-v1"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError(f"unsafe Host maintenance path: {path}")
    if any(runtime_identity._is_link(p) for p in (path, *path.parents)):
        raise ValueError(f"unsafe Host maintenance path: {path}")
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"Host maintenance path parent is not a directory: {parent}")
    if path.exists() and not path.is_file():
        raise ValueError(f"Host maintenance file is not regular: {path}")


def selected_runtime(value: object) -> tuple[Path, bytes]:
    if not isinstance(value, dict) or set(value) != {"executable", "runtime_sha256", "source_pin"}:
        raise ValueError("maintenance requires an independently selected runtime identity and immutable source pin")
    source = value["source_pin"]
    if not isinstance(source, str) or re.search(r"(?:@|/commit/)[0-9a-f]{40}(?:$|[#/])|sha256:[0-9a-f]{64}$", source) is None:
        raise ValueError("maintenance source pin must name an immutable commit or artifact SHA-256")
    exe = Path(value["executable"])
    contents = runtime_identity.manifest_bytes(exe)
    runtime = runtime_identity.validate_manifest(contents, exe, value["runtime_sha256"])
    # pip's installed direct_url.json independently carries the fetched wheel
    # digest or resolved immutable VCS commit. A plausible label is not enough.
    metadata = list(Path(runtime["package_dir"]).parent.glob("thaliris_codex-*.dist-info/direct_url.json"))
    if len(metadata) != 1:
        raise ValueError("approved runtime lacks unambiguous immutable installation provenance")
    safe(metadata[0])
    direct = json.loads(metadata[0].read_bytes())
    if source.startswith("sha256:"):
        sha = direct.get("archive_info", {}).get("hashes", {}).get("sha256")
        if sha != source.removeprefix("sha256:"):
            raise ValueError("approved artifact pin differs from installed package provenance")
    else:
        match = re.search(r"@([0-9a-f]{40})(?:$|#)", source)
        vcs = direct.get("vcs_info", {})
        url = source.removeprefix("git+").split("@" + match.group(1), 1)[0] if match else None
        if match is None or vcs.get("vcs") != "git" or vcs.get("commit_id") != match.group(1) or direct.get("url") != url:
            raise ValueError("approved source pin differs from installed immutable VCS provenance")
    return exe.resolve(strict=True), contents


def contract(filename: str | Path | None, operation: str, home: Path, *, actor: dict | None = None) -> dict:
    if filename is None:
        raise ValueError("HOST_MAINTENANCE_INTENT_REQUIRED: use --maintenance-contract FILE")
    path = Path(filename)
    safe(path)
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or value.get("format") != FORMAT or value.get("operation") != operation:
        raise ValueError("Host maintenance operation does not match explicit intent")
    if Path(value.get("codex_home", "")).absolute() != home.absolute():
        raise ValueError("Host maintenance home does not match explicit intent")
    if not isinstance(value.get("human_instruction"), str) or not value["human_instruction"].strip():
        raise ValueError("Host maintenance requires the actual human maintenance instruction")
    if actor and (actor.get("agent_id") is not None or actor.get("agent_type") is not None or
                  actor.get("readonly") is True or actor.get("fenced") is True):
        raise ValueError("HOST_MAINTENANCE_ACTOR_DENIED")
    selected_runtime(value.get("executor"))
    if operation == "codex-install":
        selected_runtime(value.get("candidate"))
    legacy = value.get("legacy_owned_bytes", {})
    if not isinstance(legacy, dict):
        raise ValueError("legacy ownership approval must be an exact byte hash mapping")
    for name, sha in legacy.items():
        if not isinstance(name, str) or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("legacy ownership approval requires exact reviewed byte hashes")
    value["contract_sha256"] = digest(raw)
    return value


def ownership(home: Path, installed: bytes | None, intent: dict) -> dict:
    path = home / RECEIPT_NAME
    safe(path)
    if not path.exists():
        # A narrow explicit human approval can migrate a legacy installation.
        # Neither historical render hashes nor candidate equality supply it.
        return {"owned_bytes": intent.get("legacy_owned_bytes", {}), "hook_handlers": {}}
    record = json.loads(path.read_bytes())
    if not isinstance(record, dict) or record.get("format") != RECEIPT_FORMAT or (
            record.get("runtime_sha256") != (digest(installed) if installed is not None else "ABSENT")):
        raise ValueError("installed ownership record does not match trusted current installation")
    if not re.fullmatch(r"[0-9a-f]{64}", record.get("maintenance_contract_sha256", "")):
        raise ValueError("installed ownership record lacks authorized installation provenance")
    if not isinstance(record.get("human_instruction"), str) or not record["human_instruction"].strip():
        raise ValueError("installed ownership record lacks explicit installation intent")
    if not isinstance(record.get("owned_bytes"), dict) or not isinstance(record.get("hook_handlers"), dict):
        raise ValueError("invalid installed ownership record structure")
    for name, sha in record.get("owned_bytes", {}).items():
        if not isinstance(name, str) or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("invalid installed ownership byte identity")
    if any(not isinstance(event, str) or not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries)
           for event, entries in record["hook_handlers"].items()):
        raise ValueError("invalid installed hook ownership structure")
    return record


def owned(record: dict, name: str, contents: bytes) -> bool:
    return record.get("owned_bytes", {}).get(name) == digest(contents)


def remove_recorded_hooks(original: dict, record: dict) -> dict:
    result = json.loads(json.dumps(original))
    hooks = result.get("hooks", {})
    for event, handlers in record.get("hook_handlers", {}).items():
        if event in hooks:
            hooks[event] = [entry for entry in hooks[event] if entry not in handlers]
            if not hooks[event]:
                del hooks[event]
    return result


def _require_only_owned_host_hooks(original: dict, record: dict, hooks_bytes: bytes, home: Path) -> None:
    """Reject Thaliris control handlers that the receipt does not own exactly."""
    from collections import Counter
    from . import lifecycle

    recorded: dict[str, Counter[bytes]] = {}
    for event, entries in record.get("hook_handlers", {}).items():
        counts = recorded.setdefault(event, Counter())
        for entry in entries:
            handlers = entry.get("hooks", [])
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                command = handler.get("command") if isinstance(handler, dict) else None
                if isinstance(command, str) and lifecycle._looks_host_trampoline(command):
                    identity = json.dumps(handler, sort_keys=True, separators=(",", ":")).encode()
                    counts[identity] += 1

    whole_file_approved = owned(record, "hooks.json", hooks_bytes)
    hooks = original.get("hooks", {})
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            handlers = entry.get("hooks") if isinstance(entry, dict) else None
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                command = handler.get("command") if isinstance(handler, dict) else None
                if not isinstance(command, str) or not lifecycle._looks_host_trampoline(command):
                    continue
                identity = json.dumps(handler, sort_keys=True, separators=(",", ":")).encode()
                if recorded.get(event, Counter())[identity] > 0:
                    recorded[event][identity] -= 1
                    continue
                if whole_file_approved and lifecycle._host_hook_command_is_managed(handler, event, home):
                    continue
                raise ValueError("unowned Host hooks: preserve and review exact bytes")


def _installed(home: Path) -> bytes | None:
    path = home / runtime_identity.MANIFEST_NAME
    try:
        safe(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"installed_runtime_manifest_unavailable: {exc}") from exc
    if not path.exists():
        return None
    contents = path.read_bytes()
    record = runtime_identity.validate_manifest_record(contents)
    runtime_identity.validate_manifest(contents, Path(record["executable"]), digest(contents))
    return contents


def _global_owned_bytes(current: bytes) -> bytes | None:
    from . import codex_adapter as adapter
    span = adapter._global_agents_span(current)
    return current[span[0]:span[1]] if span else None


def _files(home: Path) -> dict[str, bytes]:
    from . import lifecycle, host_preflight, roles
    if any(character in str(home) for character in ('"', "%", "!", "\r", "\n")):
        raise ValueError("host_hook_script_path_not_safe_for_cmd_trampoline")
    names = [runtime_identity.MANIFEST_NAME, RECEIPT_NAME, "AGENTS.md", "hooks.json",
             lifecycle.HOST_HOOK_SCRIPT_NAME, lifecycle.HOST_RUN_SCRIPT_NAME, host_preflight.NAME]
    names += ["agents/" + name for name in roles.agent_profiles()]
    safe(home / "agents" / ".maintenance-path-check")
    result = {}
    for name in names:
        path = home / name
        safe(path)
        if path.exists():
            result[name] = path.read_bytes()
    return result


def _failure(home: Path, error: Exception) -> dict:
    return {"ok": False, "changed": False, "target": str(home), "files": [],
            "manual_action_required": [str(error)], "project_files_touched": [],
            "host_actor_assurance": "UNKNOWN", "host_session_load_status": "UNKNOWN"}


def install(home: Path, executable, executable_sha256, execution_constraint, filename) -> dict:
    from . import codex_adapter as adapter, lifecycle, host_preflight, roles, codex_app_server
    # No disk, audit, profile or trust mutation occurs before this complete plan.
    try:
        intent = contract(filename, "codex-install", home)
        prior = _installed(home)
        expected_prior = intent.get("installed_runtime_sha256")
        if expected_prior != (digest(prior) if prior is not None else "ABSENT"):
            raise ValueError("current installed runtime differs from approved maintenance identity")
        before = _files(home)
        safe(home / "config.toml")
        record = ownership(home, prior, intent)
        if record.get("execution_constraint") == "luna-only" and execution_constraint != "luna-only":
            raise ValueError("existing luna-only installation requires the same explicit constraint; omission cannot remove it")
        candidate, approved = selected_runtime(intent["candidate"])
        if executable is not None and Path(executable).resolve() != candidate:
            raise ValueError("candidate executable differs from approved maintenance identity")
        exe, sha, problem = adapter._host_install_executable(home, candidate, executable_sha256 or json.loads(approved)["executable_sha256"])
        if problem or exe != candidate:
            raise ValueError(problem or "candidate executable identity mismatch")
        runtime = runtime_identity.manifest_bytes(candidate)
        if runtime != approved:
            raise ValueError("candidate runtime changed during preflight")
        # Render from the approved candidate, not an older executor's sources.
        # A distinct trusted executor can invoke the approved candidate CLI;
        # the candidate remains independently selected by the intent file.
        executor, executor_bytes = selected_runtime(intent["executor"])
        if json.loads(executor_bytes)["package_dir"] != json.loads(runtime)["package_dir"]:
            raise ValueError("install executor must run the independently approved candidate renderer")
        if intent.get("execution_constraint") != execution_constraint:
            raise ValueError("execution constraint differs from explicit maintenance intent")
        current_global = before.get("AGENTS.md", b"")
        span = _global_owned_bytes(current_global)
        if span is not None and not owned(record, "AGENTS.md#global", span):
            raise ValueError("unowned global startup block: preserve and review exact bytes")
        writes = {
            runtime_identity.MANIFEST_NAME: runtime,
            lifecycle.HOST_HOOK_SCRIPT_NAME: adapter.host_hook_script_bytes(),
            lifecycle.HOST_RUN_SCRIPT_NAME: adapter.host_run_script_bytes(candidate, digest(runtime)),
            host_preflight.NAME: host_preflight.script_bytes(),
            "AGENTS.md": adapter._global_agents_update(current_global, executable=candidate,
                executable_sha256=sha, codex_home=home),
        }
        for name, (model, effort, role) in roles.agent_profiles(execution_constraint).items():
            writes["agents/" + name] = adapter._agent_profile(name.removesuffix(".toml"), role, model, effort)
        for name in writes:
            if name in {runtime_identity.MANIFEST_NAME, "AGENTS.md"}:
                continue
            if name in before and not owned(record, name, before[name]):
                raise ValueError(f"unowned Host control file: {home / name}; preserve and review exact bytes")
        original = json.loads(before.get("hooks.json", b"{}"))
        if not isinstance(original, dict) or not isinstance(original.get("hooks", {}), dict):
            raise ValueError("Host hooks.json must contain an object")
        _require_only_owned_host_hooks(original, record, before.get("hooks.json", b"{}"), home)
        cleaned = remove_recorded_hooks(original, record)
        for event, entries in record.get("hook_handlers", {}).items():
            if any(entry not in original.get("hooks", {}).get(event, []) for entry in entries):
                raise ValueError("installed Host hook ownership bytes changed")
        # Legacy approved hooks remain exact bytes; only the existing complete
        # handler recognizer removes their Thaliris entries, preserving others.
        if "hooks.json" in before and owned(record, "hooks.json", before["hooks.json"]):
            cleaned, _, manual = adapter.remove_host_hooks(cleaned, home)
            if manual:
                raise ValueError("legacy Host hooks require manual ownership resolution")
        merged, _, manual = adapter.merge_host_hooks(cleaned, home, candidate, sha, digest(runtime))
        if manual:
            raise ValueError("Host hook control conflict: " + ",".join(manual))
        # A pre-existing recognized candidate-shaped handler is still unowned.
        if "hooks.json" in before and not owned(record, "hooks.json", before["hooks.json"]):
            recognized = adapter._owned_host_hook_commands(cleaned, home)
            if any(recognized.values()):
                raise ValueError("candidate-shaped Host hooks have no prior authorized ownership")
        writes["hooks.json"] = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode()
        hook_handlers = {event: [entry for entry in merged.get("hooks", {}).get(event, [])
                        if entry not in cleaned.get("hooks", {}).get(event, [])]
                        for event in lifecycle.HOOK_EVENTS}
        # Idempotent planning records the exact installed generated handlers too.
        for event in lifecycle.HOOK_EVENTS:
            if not hook_handlers[event]:
                hook_handlers[event] = [entry for entry in merged.get("hooks", {}).get(event, [])
                    if entry in record.get("hook_handlers", {}).get(event, [])]
        installation_changed = prior is None or prior != runtime or RECEIPT_NAME not in before or any(
            before.get(name) != contents for name, contents in writes.items()
        )
        receipt = {"format": RECEIPT_FORMAT, "runtime_sha256": digest(runtime),
                   "execution_constraint": execution_constraint,
                   "maintenance_contract_sha256": intent["contract_sha256"] if installation_changed else record["maintenance_contract_sha256"],
                   "source_pin": intent["candidate"]["source_pin"] if installation_changed else record.get("source_pin", intent["candidate"]["source_pin"]),
                   "human_instruction": intent["human_instruction"] if installation_changed else record["human_instruction"],
                   "owned_bytes": {name: digest(value) for name, value in writes.items()
                                   if name not in {"AGENTS.md", "hooks.json", runtime_identity.MANIFEST_NAME}},
                   "hook_handlers": hook_handlers}
        receipt["owned_bytes"]["AGENTS.md#global"] = digest(_global_owned_bytes(writes["AGENTS.md"]))
        writes[RECEIPT_NAME] = (json.dumps(receipt, sort_keys=True, ensure_ascii=False) + "\n").encode()
        if _files(home) != before or runtime_identity.manifest_bytes(candidate) != runtime:
            raise ValueError("maintenance input changed during preflight")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return _failure(home, exc)

    changed_files = []
    if prior is not None and prior != runtime:
        adapter._write_runtime_audit(home, prior, Path(json.loads(prior)["executable"]))
    for name, contents in writes.items():
        if before.get(name) != contents:
            adapter._atomic_host_write(home / name, contents)
            changed_files.append(name)
    health = lifecycle.host_hooks_health(home)
    trust_status, trust_error = "NOT_REGISTERED", None
    trusted_count = enabled_count = 0
    expected_count = len(lifecycle.HOOK_EVENTS)
    try:
        trust = adapter._install_host_hook_trust(home, candidate, sha, digest(runtime))
        trust_status = str(trust.get("status", "FAILED"))
        trusted_count = int(trust.get("trusted_count", 0))
        enabled_count = int(trust.get("enabled_count", 0))
        if trust.get("changed"):
            changed_files.append("config.toml")
    except (codex_app_server.CodexAppServerError, OSError, ValueError, RuntimeError) as exc:
        trust_error = str(exc)
        trust_status = "HOST_HOOK_TRUST_INSTALL_FAILED"
    ready = health["hooks_configured"] == "YES" and trust_status == "TRUSTED" and trusted_count == enabled_count == expected_count and adapter._host_profile_definition_present(home) == "YES"
    if ready:
        manual = []
    elif trust_error:
        manual = ["HOST_HOOK_TRUST_INSTALL_FAILED"]
    elif trust_status == "TRUSTED" and (trusted_count != expected_count or enabled_count != expected_count):
        manual = ["one_or_more_Thaliris_Host_hooks_are_disabled_by_user_state"]
    else:
        manual = ["Host registration or trust incomplete"]
    return {"ok": ready, "changed": bool(changed_files), "target": str(home),
        "files": sorted(set(changed_files)), "manual_action_required": manual,
        "host_actor_assurance": "UNKNOWN", "maintenance_authority": "EXPLICIT_HUMAN_INTENT",
        "execution_constraint": execution_constraint, "host_profile_definition_present": adapter._host_profile_definition_present(home),
        "host_hook_registration_present": health["hooks_configured"], "host_hook_trust_status": trust_status,
        "host_hook_trusted_count": trusted_count, "host_hook_enabled_count": enabled_count,
        "host_hook_expected_count": expected_count, "host_hook_trust_error": trust_error,
        "host_integration_ready": "YES" if ready else "NO", "global_instruction_ready": "YES",
        "host_role_catalog_status": lifecycle.HOST_ROLE_CATALOG_UNKNOWN, "host_session_load_status": "UNKNOWN",
        "installed_runtime_identity": digest(runtime), "managed_hook_abi": lifecycle.MANAGED_HOOK_ABI,
        "native_profile_names": sorted(roles.native_profile_names()), "project_files_touched": [],
        "install_status": "RESTART_CODEX_ONCE" if ready and changed_files else "HOST_INTEGRATION_UNCHANGED" if ready else "INSTALL_INCOMPLETE",
        "session_restart_required": bool(ready and changed_files), "host_setup_requires_session_start": bool(changed_files)}


def uninstall(home: Path, filename) -> dict:
    from . import codex_adapter as adapter, lifecycle, codex_app_server
    import os
    try:
        intent = contract(filename, "codex-uninstall", home)
        executor, executor_bytes = selected_runtime(intent["executor"])
        prior = _installed(home)
        if intent.get("installed_runtime_sha256") != (digest(prior) if prior is not None else "ABSENT"):
            raise ValueError("current installed runtime differs from approved maintenance identity")
        before = _files(home)
        safe(home / "config.toml")
        probed, _, problem = adapter._host_install_executable(home, executor,
            json.loads(executor_bytes)["executable_sha256"])
        if problem or probed != executor:
            raise ValueError(problem or "maintenance executor probe identity mismatch")
        record = ownership(home, prior, intent)
        writes, deletes, preserved = {}, [], []
        current_global = before.get("AGENTS.md", b"")
        span = _global_owned_bytes(current_global)
        if span is not None:
            if not owned(record, "AGENTS.md#global", span):
                raise ValueError("unowned global startup block: preserve and review exact bytes")
            writes["AGENTS.md"] = adapter._global_agents_update(current_global, remove=True)
        original = json.loads(before.get("hooks.json", b"{}"))
        if not isinstance(original, dict) or not isinstance(original.get("hooks", {}), dict):
            raise ValueError("Host hooks.json must contain an object")
        _require_only_owned_host_hooks(original, record, before.get("hooks.json", b"{}"), home)
        cleaned = remove_recorded_hooks(original, record)
        for event, entries in record.get("hook_handlers", {}).items():
            if any(entry not in original.get("hooks", {}).get(event, []) for entry in entries):
                raise ValueError("installed Host hook ownership bytes changed")
        if "hooks.json" in before and owned(record, "hooks.json", before["hooks.json"]):
            cleaned, _, manual = adapter.remove_host_hooks(cleaned, home)
            if manual:
                raise ValueError("legacy hooks require manual ownership resolution")
        if cleaned != original:
            writes["hooks.json"] = (json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n").encode()
        # Prior authorized handler bytes can be from a generation unknown to
        # this renderer. Query their exact native keys directly from receipt
        # commands; current command recognition is not historical ownership.
        commands = {event: {handler["command"] for entry in entries
                    for handler in entry.get("hooks", [])
                    if isinstance(handler, dict) and handler.get("type") == "command"
                    and isinstance(handler.get("command"), str)}
                    for event, entries in record.get("hook_handlers", {}).items()}
        if not record.get("hook_handlers") and owned(record, "hooks.json", before.get("hooks.json", b"")):
            commands = adapter._owned_host_hook_commands(original, home)
        keys = codex_app_server.owned_hook_keys_from_host(home, commands) if any(commands.values()) else []
        inert = False
        for name, contents in before.items():
            if name in {"AGENTS.md", "hooks.json", runtime_identity.MANIFEST_NAME, RECEIPT_NAME}:
                continue
            if not owned(record, name, contents):
                preserved.append(name)
                # Native profiles may contain user edits and are preserved.
                # The runner/hook/preflight are control conflicts, fail closed.
                if not name.startswith("agents/"):
                    raise ValueError(f"unowned Host control file: {name}")
                continue
            if name == lifecycle.HOST_RUN_SCRIPT_NAME and os.environ.get("THALIRIS_RUN_SCRIPT") == str(home / name):
                inert = True
            else:
                deletes.append(name)
        if prior is not None:
            deletes.append(runtime_identity.MANIFEST_NAME)
        if RECEIPT_NAME in before and not inert:
            deletes.append(RECEIPT_NAME)
        if inert:
            retained = {"format": RECEIPT_FORMAT, "runtime_sha256": "ABSENT",
                "maintenance_contract_sha256": intent["contract_sha256"],
                "human_instruction": intent["human_instruction"],
                "owned_bytes": {lifecycle.HOST_RUN_SCRIPT_NAME: digest(before[lifecycle.HOST_RUN_SCRIPT_NAME])},
                "hook_handlers": {}}
            writes[RECEIPT_NAME] = (json.dumps(retained, sort_keys=True) + "\n").encode()
        if _files(home) != before:
            raise ValueError("maintenance input changed during preflight")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, codex_app_server.CodexAppServerError) as exc:
        return _failure(home, exc)
    # Preserve the provenance before removing the active installation record.
    audits = []
    if prior is not None:
        audit = adapter._write_runtime_audit(home, prior, Path(json.loads(prior)["executable"]))
        audit_value = json.loads(audit.read_bytes())
        audit_value["ownership_receipt"] = record
        audit_value["maintenance_contract_sha256"] = intent["contract_sha256"]
        adapter._atomic_host_write(audit, (json.dumps(audit_value, sort_keys=True) + "\n").encode())
        audits.append(audit.name)
    try:
        trust_removed = codex_app_server.remove_owned_hook_trust(home, keys) if keys else 0
    except (OSError, ValueError, RuntimeError) as exc:
        result = _failure(home, exc)
        result.update(status="UNINSTALL_INCOMPLETE", changed=bool(audits), runtime_audit_records=audits,
                      host_hook_trust_cleanup_status="FAILED", host_hook_trust_cleanup_error=str(exc))
        return result
    for name, contents in writes.items():
        if contents:
            adapter._atomic_host_write(home / name, contents)
        else:
            (home / name).unlink()
    for name in deletes:
        (home / name).unlink()
    return {"ok": True, "changed": bool(writes or deletes or trust_removed), "target": str(home),
        "status": "UNINSTALLED_INERT_RUNNER_RETAINED" if inert else "UNINSTALLED",
        "files": sorted(set(writes) | set(deletes)), "preserved_files": preserved,
        "manual_action_required": [], "retained_inert_runner": inert, "runtime_audit_records": audits,
        "host_hook_trust_cleanup_status": "CLEANED" if keys else "NOT_NEEDED",
        "host_hook_trusted_state_removed": trust_removed, "host_hook_trust_cleanup_error": None,
        "host_hook_registration_present": lifecycle.host_hooks_health(home)["hooks_configured"],
        "host_profile_definition_present": adapter._host_profile_definition_present(home),
        "host_actor_assurance": "UNKNOWN", "host_role_catalog_status": lifecycle.HOST_ROLE_CATALOG_UNKNOWN,
        "project_files_touched": []}
