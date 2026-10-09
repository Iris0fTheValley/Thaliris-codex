"""Host-scoped, explicitly selected maintenance intent and installation ownership.

These records are governance on a shared OS, not human authentication. Runtime
reproducibility is a consistency check and never supplies intent or ownership.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import runtime_identity, diagnostics

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
    try:
        return _selected_runtime(value)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        diagnostics.failure("runtime-identity")
        raise


def _selected_runtime(value: object) -> tuple[Path, bytes]:
    if not isinstance(value, dict) or set(value) != {"executable", "runtime_sha256", "source_pin"}:
        raise ValueError("maintenance requires an independently selected runtime identity and immutable source pin")
    source = value["source_pin"]
    if not isinstance(source, str) or re.search(r"(?:@|/commit/)[0-9a-f]{40}(?:$|[#/])|sha256:[0-9a-f]{64}$", source) is None:
        raise ValueError("maintenance source pin must name an immutable commit or artifact SHA-256")
    exe = Path(value["executable"])
    contents = runtime_identity.manifest_bytes(exe)
    runtime_identity._assert_location(exe.resolve(strict=True), required=True)
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
    # Execute only after isolation, exact bytes and independent installed
    # provenance are checked. Rehashing a relocated venv supplies no admission.
    runtime_identity.console_smoke(exe.resolve(strict=True), contents)
    return exe.resolve(strict=True), contents


def contract(filename: str | Path | None, operation: str, home: Path, *, actor: dict | None = None) -> dict:
    try:
        value, raw = _contract_document(filename, operation, home, actor=actor)
        instruction_targets(value, home)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        diagnostics.failure("maintenance-contract")
        raise
    selected_runtime(value.get("executor"))
    if operation == "codex-install":
        selected_runtime(value.get("candidate"))
    legacy = value.get("legacy_owned_bytes", {})
    if not isinstance(legacy, dict):
        diagnostics.failure("maintenance-contract")
        raise ValueError("legacy ownership approval must be an exact byte hash mapping")
    if any(
            not isinstance(name, str) or not isinstance(sha, str) or
            not re.fullmatch(r"[0-9a-f]{64}", sha) for name, sha in legacy.items()):
        diagnostics.failure("maintenance-contract")
        raise ValueError("legacy ownership approval requires exact reviewed byte hashes")
    value["contract_sha256"] = digest(raw)
    return value


def _contract_document(filename: str | Path | None, operation: str, home: Path, *, actor: dict | None = None) -> tuple[dict, bytes]:
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
    return value, raw


def ownership(home: Path, installed: bytes | None, intent: dict) -> dict:
    path = home / RECEIPT_NAME
    safe(path)
    return validate_ownership(path.read_bytes() if path.exists() else None, installed, intent)


def validate_ownership(contents: bytes | None, installed: bytes | None, intent: dict) -> dict:
    if contents is None:
        # A narrow explicit human approval can migrate a legacy installation.
        # Neither historical render hashes nor candidate equality supply it.
        return {"owned_bytes": intent.get("legacy_owned_bytes", {}), "hook_handlers": {}}
    record = json.loads(contents)
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
        if name.startswith("agents/"):
            from .host_transition import _profile_name
            if not _profile_name(name):
                raise ValueError("invalid installed ownership profile path")
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
    runtime_identity.validate_existing_manifest(contents, Path(record["executable"]), digest(contents))
    return contents


def _global_owned_bytes(current: bytes) -> bytes | None:
    from . import codex_adapter as adapter
    span = adapter._global_agents_span(current)
    return current[span[0]:span[1]] if span else None


def instruction_targets(intent: dict, home: Path) -> dict[str, str]:
    """Resolve only explicitly selected existing global instruction files.

    An exact fragment approval is separate from installation ownership and
    never approves the rest of a user's file. No migration is inferred.
    """
    migrations = intent.get("instruction_migrations", [])
    if not isinstance(migrations, list) or migrations and intent.get("operation") != "codex-install":
        raise ValueError("instruction migrations require explicit codex-install intent")
    targets, seen = {}, set()
    for index, item in enumerate(migrations):
        if not isinstance(item, dict) or set(item) != {"path", "before_sha256", "after_sha256", "remove_spans"}:
            raise ValueError("instruction migration requires exact before/after identities and selected spans")
        if not isinstance(item["path"], str):
            raise ValueError("invalid instruction migration path")
        path = Path(item["path"])
        safe(path)
        if path.name != "AGENTS.md" or not path.is_file():
            raise ValueError("instruction migration requires an existing AGENTS.md")
        identity = path.resolve()
        if identity not in {(home / "AGENTS.md").resolve(), (Path.home() / "AGENTS.md").resolve()}:
            raise ValueError("instruction migration must select a Codex-home or user-home global AGENTS.md")
        if identity in seen:
            raise ValueError("duplicate instruction migration target")
        seen.add(identity)
        if any(not isinstance(item[key], str) or re.fullmatch(r"[0-9a-f]{64}", item[key]) is None
               for key in ("before_sha256", "after_sha256")):
            raise ValueError("instruction migration requires exact reviewed byte hashes")
        spans = item["remove_spans"]
        if not isinstance(spans, list) or not spans:
            raise ValueError("instruction migration requires explicitly selected Thaliris spans")
        for span in spans:
            if not isinstance(span, dict) or set(span) != {"offset", "length", "sha256", "kind"} or (
                    type(span["offset"]) is not int or span["offset"] < 0 or
                    type(span["length"]) is not int or span["length"] <= 0 or
                    not isinstance(span["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", span["sha256"]) is None or
                    span["kind"] not in {"global-block", "durable-section"}):
                raise ValueError("invalid selected Thaliris instruction span")
        name = "AGENTS.md" if path.resolve() == (home / "AGENTS.md").resolve() else f"instruction_migrations/{index}"
        targets[name] = str(path)
    return targets


def migrated_instructions(intent: dict, home: Path, before: dict[str, bytes | None],
                          executable: Path, sha: str) -> dict[str, bytes]:
    """Remove exact approved obsolete spans and render the single home entry."""
    from . import codex_adapter as adapter
    targets = instruction_targets(intent, home)
    writes = {}
    for item in intent.get("instruction_migrations", []):
        name = next(name for name, target in targets.items() if Path(target) == Path(item["path"]))
        current = before.get(name)
        if current is None or digest(current) != item["before_sha256"]:
            raise ValueError("instruction migration before bytes changed; preserve for review")
        last_end = 0
        pieces = []
        for selected in sorted(item["remove_spans"], key=lambda selected: selected["offset"]):
            start, end = selected["offset"], selected["offset"] + selected["length"]
            if start < last_end or end > len(current) or digest(current[start:end]) != selected["sha256"]:
                raise ValueError("instruction migration selected span changed or overlaps")
            if selected["kind"] == "global-block":
                if name == "AGENTS.md" or adapter._global_agents_span(current) != (start, end):
                    raise ValueError("only a redundant external global Thaliris block can be removed")
            else:
                # The exact complete Markdown section is required. A heading
                # recognizer does not itself authorize any bytes.
                heading = b"## Durable Thaliris synchronization"
                if name != "AGENTS.md" or current[start:end].splitlines()[0] != heading or (start and current[start-1:start] != b"\n"):
                    raise ValueError("only the selected home Durable Thaliris section can be removed")
                following = re.search(rb"(?m)^## ", current[start + len(heading):])
                section_end = start + len(heading) + following.start() if following else len(current)
                if end != section_end:
                    raise ValueError("instruction migration must select the complete Durable Thaliris section")
            pieces.append(current[last_end:start])
            last_end = end
        pieces.append(current[last_end:])
        result = b"".join(pieces)
        if name == "AGENTS.md":
            result = adapter._global_agents_update(result, executable=executable, executable_sha256=sha, codex_home=home)
        elif adapter._global_agents_span(result) is not None:
            raise ValueError("redundant global Thaliris entry remains")
        if digest(result) != item["after_sha256"]:
            raise ValueError("instruction migration after candidate differs from explicit intent")
        writes[name] = result
    return writes


def _files(home: Path) -> dict[str, bytes]:
    from . import lifecycle, host_preflight, roles, host_transition
    if any(character in str(home) for character in ('"', "%", "!", "\r", "\n")):
        raise ValueError("host_hook_script_path_not_safe_for_cmd_trampoline")
    names = [runtime_identity.MANIFEST_NAME, RECEIPT_NAME, "AGENTS.md", "hooks.json",
             lifecycle.HOST_HOOK_SCRIPT_NAME, lifecycle.HOST_RUN_SCRIPT_NAME, host_preflight.NAME]
    names += ["agents/" + name for name in roles.agent_profiles()]
    safe(home / host_transition.NAME)
    safe(home / "thaliris-host-generations" / ".maintenance-path-check")
    lock = home / host_transition.LOCK_NAME
    safe(lock)
    if lock.exists() and lock.read_bytes() != host_transition.LOCK_BYTES:
        raise ValueError("unowned Host maintenance lock file; preserve for review")
    receipt = home / RECEIPT_NAME
    safe(receipt)
    if receipt.exists():
        from .host_transition import _profile_name
        value = json.loads(receipt.read_bytes())
        if not isinstance(value, dict) or not isinstance(value.get("owned_bytes"), dict):
            raise ValueError("invalid installed ownership record structure")
        for name in value["owned_bytes"]:
            if isinstance(name, str) and name.startswith("agents/"):
                if not _profile_name(name):
                    raise ValueError("invalid installed ownership profile path")
                names.append(name)
    safe(home / "agents" / ".maintenance-path-check")
    result = {}
    for name in names:
        path = home / name
        safe(path)
        if path.exists():
            result[name] = path.read_bytes()
    return result


def _failure(home: Path, error: Exception) -> dict:
    result = {"ok": False, "changed": False, "target": str(home), "files": [],
            "manual_action_required": [str(error)], "project_files_touched": [],
            "host_actor_assurance": "UNKNOWN", "host_session_load_status": "UNKNOWN"}
    from . import host_transition
    # Preserve a pending state even when a resumed preflight detects input drift.
    if (home / host_transition.NAME).exists():
        result.update(status="HOST_TRANSITION_PENDING", transition_pending=True,
                      recovery_action="Replay the original maintenance contract; resolve reported drift first")
    return result


def install(home: Path, executable, executable_sha256, execution_constraint, filename) -> dict:
    from . import codex_adapter as adapter, lifecycle, host_preflight, roles, host_transition
    # No disk, audit, profile or trust mutation occurs before this complete plan.
    try:
        intent = contract(filename, "codex-install", home)
        candidate, approved = selected_runtime(intent["candidate"])
        if executable is not None and Path(executable).resolve() != candidate:
            raise ValueError("candidate executable differs from approved maintenance identity")
        if executable_sha256 is not None and executable_sha256 != json.loads(approved)["executable_sha256"]:
            raise ValueError("candidate executable hash differs from approved maintenance identity")
        if intent.get("execution_constraint") != execution_constraint:
            raise ValueError("execution constraint differs from explicit maintenance intent")
        resumed = host_transition.resume(home, intent, _finish_install)
        if resumed is not None:
            return resumed
        prior = _installed(home)
        expected_prior = intent.get("installed_runtime_sha256")
        if expected_prior != (digest(prior) if prior is not None else "ABSENT"):
            raise ValueError("current installed runtime differs from approved maintenance identity")
        before = _files(home)
        targets = instruction_targets(intent, home)
        before.update(host_transition._observe(home, targets, targets=targets))
        safe(home / "config.toml")
        record = ownership(home, prior, intent)
        if record.get("execution_constraint") == "luna-only" and execution_constraint != "luna-only":
            raise ValueError("existing luna-only installation requires the same explicit constraint; omission cannot remove it")
        exe, sha, problem = adapter._host_install_executable(home, candidate, executable_sha256 or json.loads(approved)["executable_sha256"])
        if problem or exe != candidate:
            raise ValueError(problem or "candidate executable identity mismatch")
        runtime = runtime_identity.manifest_bytes(candidate)
        if runtime != approved:
            raise ValueError("candidate runtime changed during preflight")
        host_preflight.verify_runtime(candidate, runtime)
        # Render from the approved candidate itself, not an older executor's
        # sources. The selected executor must identify that same approved package.
        executor, executor_bytes = selected_runtime(intent["executor"])
        if json.loads(executor_bytes)["package_dir"] != json.loads(runtime)["package_dir"]:
            raise ValueError("install executor must run the independently approved candidate renderer")
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
        writes.update(migrated_instructions(intent, home, before, candidate, sha))
        for name, (model, effort, role) in roles.agent_profiles(execution_constraint).items():
            writes["agents/" + name] = adapter._agent_profile(name.removesuffix(".toml"), role, model, effort)
        deletes = []
        for name, contents in before.items():
            if name.startswith("agents/") and name not in writes and name in record.get("owned_bytes", {}):
                if not owned(record, name, contents):
                    raise ValueError(f"edited retired Host profile: {name}; preserve and review exact bytes")
                deletes.append(name)
        for name in writes:
            if name in {runtime_identity.MANIFEST_NAME, "AGENTS.md"} or name.startswith("instruction_migrations/"):
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
        installation_changed = bool(deletes) or prior is None or prior != runtime or RECEIPT_NAME not in before or any(
            before.get(name) != contents for name, contents in writes.items()
        )
        receipt = {"format": RECEIPT_FORMAT, "runtime_sha256": digest(runtime),
                   "execution_constraint": execution_constraint,
                   "maintenance_contract_sha256": intent["contract_sha256"] if installation_changed else record["maintenance_contract_sha256"],
                   "source_pin": intent["candidate"]["source_pin"] if installation_changed else record.get("source_pin", intent["candidate"]["source_pin"]),
                   "human_instruction": intent["human_instruction"] if installation_changed else record["human_instruction"],
                   "owned_bytes": {name: digest(value) for name, value in writes.items()
                                   if name not in {"AGENTS.md", "hooks.json", runtime_identity.MANIFEST_NAME}
                                   and not name.startswith("instruction_migrations/")},
                   "hook_handlers": hook_handlers}
        receipt["owned_bytes"]["AGENTS.md#global"] = digest(_global_owned_bytes(writes["AGENTS.md"]))
        writes[RECEIPT_NAME] = (json.dumps(receipt, sort_keys=True, ensure_ascii=False) + "\n").encode()
        observed = _files(home)
        observed.update(host_transition._observe(home, targets, targets=targets))
        if observed != before or runtime_identity.manifest_bytes(candidate) != runtime:
            raise ValueError("maintenance input changed during preflight")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return _failure(home, exc)

    changed_files = sorted(set(deletes) | {name for name, contents in writes.items() if before.get(name) != contents})
    finish = {"candidate": str(candidate), "sha": sha, "runtime": runtime.decode(),
              "execution_constraint": execution_constraint, "changed_files": changed_files}
    try:
        with host_transition.locked(home):
            transition = host_transition.begin(home, intent, before, writes, deletes, finish)
            return _finish_install(home, transition)
    except (OSError, ValueError, RuntimeError) as exc:
        return _transition_failure(home, exc)


def _transition_failure(home, error):
    from . import host_transition
    result = _failure(home, error)
    is_pending = host_transition.pending(home)
    result.update(status="HOST_TRANSITION_PENDING" if is_pending else "HOST_MAINTENANCE_PREPARE_FAILED", changed=is_pending,
                  recovery_action="Replay the original codex-install/codex-uninstall --maintenance-contract FILE",
                  host_integration_ready="NO", transition_pending=is_pending)
    return result


def _finish_install(home, transition):
    from . import codex_adapter as adapter, lifecycle, codex_app_server, roles, host_transition
    finish = transition["finish"]
    candidate, sha, runtime = Path(finish["candidate"]), finish["sha"], finish["runtime"].encode()
    execution_constraint, changed_files = finish["execution_constraint"], list(finish["changed_files"])
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
        host_transition.complete(home, transition)
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
        "instruction_files_touched": [path for name, path in transition.get("instruction_targets", {}).items()
                                      if name in changed_files],
        "transition_pending": not ready,
        "recovery_action": None if ready else "Replay the original codex-install --maintenance-contract FILE",
        "install_status": "RESTART_CODEX_ONCE" if ready and changed_files else "HOST_INTEGRATION_UNCHANGED" if ready else "INSTALL_INCOMPLETE",
        "session_restart_required": bool(ready and changed_files), "host_setup_requires_session_start": bool(changed_files)}


def uninstall(home: Path, filename) -> dict:
    from . import codex_adapter as adapter, lifecycle, codex_app_server, host_transition
    import os
    try:
        intent = contract(filename, "codex-uninstall", home)
        resumed = host_transition.resume(home, intent, _finish_uninstall)
        if resumed is not None:
            return resumed
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
    deletes += [name for name, contents in writes.items() if not contents]
    writes = {name: contents for name, contents in writes.items() if contents}
    finish = {"keys": keys, "inert": inert, "preserved": preserved,
              "changed_files": sorted(set(writes) | set(deletes))}
    try:
        with host_transition.locked(home):
            transition = host_transition.begin(home, intent, before, writes, deletes, finish)
            return _finish_uninstall(home, transition)
    except (OSError, ValueError, RuntimeError) as exc:
        return _transition_failure(home, exc)


def _finish_uninstall(home, transition):
    from . import codex_app_server, lifecycle, codex_adapter as adapter, host_transition
    finish = transition["finish"]
    keys, inert, preserved = finish["keys"], finish["inert"], finish["preserved"]
    audits = [host_transition.archive_name(transition)]
    try:
        trust_removed = codex_app_server.remove_owned_hook_trust(home, keys) if keys else 0
    except (OSError, ValueError, RuntimeError) as exc:
        result = _failure(home, exc)
        result.update(status="HOST_TRANSITION_PENDING", changed=True, runtime_audit_records=audits,
                      transition_pending=True, recovery_action="Replay the original codex-uninstall --maintenance-contract FILE",
                      host_hook_trust_cleanup_status="FAILED", host_hook_trust_cleanup_error=str(exc))
        return result
    host_transition.complete(home, transition)
    return {"ok": True, "changed": bool(finish["changed_files"] or trust_removed), "target": str(home),
        "status": "UNINSTALLED_INERT_RUNNER_RETAINED" if inert else "UNINSTALLED",
        "files": finish["changed_files"], "preserved_files": preserved,
        "manual_action_required": [], "retained_inert_runner": inert, "runtime_audit_records": audits,
        "host_hook_trust_cleanup_status": "CLEANED" if keys else "NOT_NEEDED",
        "host_hook_trusted_state_removed": trust_removed, "host_hook_trust_cleanup_error": None,
        "host_hook_registration_present": lifecycle.host_hooks_health(home)["hooks_configured"],
        "host_profile_definition_present": adapter._host_profile_definition_present(home),
        "host_actor_assurance": "UNKNOWN", "host_role_catalog_status": lifecycle.HOST_ROLE_CATALOG_UNKNOWN,
        "project_files_touched": []}
