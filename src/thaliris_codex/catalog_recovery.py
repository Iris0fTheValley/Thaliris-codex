"""Receipt-authorized field restoration from the verified installed runtime.

Only an actual SessionStart invokes the automatic path. It restores the
original absent catalog field when the explicitly selected project/source is
gone. Backing bytes stay available to non-cooperating concurrent config writers.
It neither reconstructs projects nor touches Controller/task authority.
"""
from __future__ import annotations

import json
from pathlib import Path

POLICY_KEY = "model_catalog_project_loss_recovery"
POLICY_FORMAT = "thaliris-model-catalog-project-loss-v1"


def validate_native_session_start(payload):
    """Fail closed unless the recovery receiver got a native-shaped actor.

    ``session_id`` is required by the observed Hook input schema. The optional
    actor identity fields are strings when present, while Thaliris' optional
    readonly/fence observations are exact booleans. These values only select
    deny-only checks; they do not authenticate a Controller or grant recovery
    authority.
    """
    if not isinstance(payload, dict):
        raise ValueError("native SessionStart payload is unavailable")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("native SessionStart session_id is missing or malformed")
    for key in ("agent_id", "agent_type", "turn_id"):
        if key in payload and not isinstance(payload[key], str):
            raise ValueError(f"native SessionStart {key} is malformed")
    for key in ("readonly", "fenced"):
        if key in payload and not isinstance(payload[key], bool):
            raise ValueError(f"native SessionStart {key} is malformed")


def validate_policy(policy):
    if policy is None:
        return
    if (not isinstance(policy, dict) or
            set(policy) - {"format", "project_root", "source_root", "restored"} or
            policy.get("format") != POLICY_FORMAT or
            not isinstance(policy.get("project_root"), str) or
            not Path(policy["project_root"]).is_absolute() or
            ("source_root" in policy and (not isinstance(policy["source_root"], str) or
                                         not Path(policy["source_root"]).is_absolute())) or
            ("restored" in policy and policy["restored"] is not True)):
        raise ValueError("invalid explicit model catalog project-loss recovery policy")


def policy_from_intent(intent):
    """An absent policy supplies no automatic maintenance authorization."""
    root = intent.get("catalog_recovery_project_root")
    source = intent.get("catalog_recovery_source_root")
    if root is None:
        if source is not None:
            raise ValueError("catalog recovery source requires explicit project selection")
        return None
    policy = {"format": POLICY_FORMAT, "project_root": root}
    if source is not None:
        policy["source_root"] = source
    validate_policy(policy)
    return policy


def _available(policy):
    from . import host_maintenance as maintenance, codex_adapter
    root = Path(policy["project_root"])
    marker = root / ".codex" / "thaliris.json"
    maintenance.safe(marker)
    if not marker.exists() or marker.read_bytes() != codex_adapter._PROJECT_ACTIVATION_BYTES:
        return False
    if "source_root" in policy:
        source = Path(policy["source_root"])
        maintenance.safe(source / ".thaliris-source-path-check")
        if not source.is_dir():
            return False
    return True


def retained_record(home, catalog_bytes=None):
    """Return only exact retained backing provenance, never a field takeover.

    Reinstall additionally requires the config field to be absent. Archives
    supply historical ownership after full Host uninstall deleted the receipt;
    a completed project-loss restoration retains its evidence in the receipt.
    """
    from . import host_maintenance as maintenance, host_transition, model_catalog_config as catalog
    contents = catalog.read_catalog(home) if catalog_bytes is None else catalog_bytes
    if contents is None:
        return None
    candidates = []
    receipt_path = home / maintenance.RECEIPT_NAME
    maintenance.safe(receipt_path)
    if receipt_path.exists():
        installed = maintenance._installed(home)
        receipt = maintenance.validate_ownership(receipt_path.read_bytes(), installed, {})
        if receipt.get(POLICY_KEY, {}).get("restored") is True:
            candidates.append(receipt.get(catalog.RECORD_KEY))
    directory = home / "thaliris-host-generations"
    maintenance.safe(directory / ".catalog-retention-path-check")
    if directory.is_dir():
        for path in directory.glob("*.json"):
            maintenance.safe(path)
            try:
                raw = path.read_bytes()
                generation = json.loads(raw)
                if (generation.get("format") != host_transition.FORMAT or
                        generation.get("phase") != "COMMITTED" or
                        generation.get("operation") != "codex-uninstall" or
                        path != home / host_transition.archive_name(generation) or
                        raw != (json.dumps(generation, sort_keys=True) + "\n").encode()):
                    continue
                before = host_transition._decode(generation["before"])
                after = host_transition._decode(generation["after"])
                record = maintenance.validate_ownership(before.get(maintenance.RECEIPT_NAME),
                                                       before.get("thaliris-install.json"), {})
                catalog_record = record.get(catalog.RECORD_KEY)
                if (catalog_record is not None and
                        generation["finish"].get("model_catalog_record") == catalog_record and
                        before.get(catalog.NAME) == after.get(catalog.NAME) == contents):
                    candidates.append(catalog_record)
            except (ValueError, TypeError, KeyError):
                continue  # Unknown archives never establish ownership.
    for record in candidates:
        catalog.validate(record, home)
        if record is not None and maintenance.digest(contents) == record["catalog_sha256"]:
            return record
    return None


def recover(home: Path, identity: str):
    from . import host_maintenance as maintenance, host_transition, runtime_identity, model_catalog_config as catalog
    from .codex_adapter import _atomic_host_write
    try:
        maintenance.safe(home / runtime_identity.MANIFEST_NAME)
        installed = (home / runtime_identity.MANIFEST_NAME).read_bytes()
        manifest = runtime_identity.validate_manifest_record(installed)
        runtime_identity.validate_manifest(installed, Path(manifest["executable"]), identity)
        # This is the existing shared Host transaction lock, not a new service
        # or global state machine. A pending maintenance contract wins.
        with host_transition.locked(home):
            if host_transition.pending(home):
                return {"ok": False, "changed": False, "status": "HOST_TRANSITION_PENDING",
                        "recovery_action": "Replay the original maintenance contract"}
            path = home / maintenance.RECEIPT_NAME
            maintenance.safe(path)
            original = path.read_bytes()
            receipt = maintenance.validate_ownership(original, installed, {})
            policy = receipt.get(POLICY_KEY)
            if policy is None:
                return {"ok": True, "changed": False, "status": "RECOVERY_POLICY_UNKNOWN"}
            record = receipt.get(catalog.RECORD_KEY)
            catalog.validate(record, home)
            if record is None:
                return {"ok": False, "changed": False, "status": "CATALOG_OWNERSHIP_UNKNOWN"}
            if _available(policy):
                return {"ok": True, "changed": False, "status": "PROJECT_AVAILABLE"}
            contents = catalog.read_catalog(home)
            if contents is None or maintenance.digest(contents) != record["catalog_sha256"]:
                return {"ok": True, "changed": False, "status": "CATALOG_CHANGED_PRESERVED"}
            result = catalog.apply(home, record, remove=True)
            if result["status"] == "RESTORED_ABSENT":
                # Only an exact owned-field removal establishes restoration
                # provenance. An already-absent field could be a user deletion.
                receipt[POLICY_KEY] = policy | {"restored": True}
                updated = (json.dumps(receipt, sort_keys=True, ensure_ascii=False) + "\n").encode()
                if path.read_bytes() != original:
                    raise ValueError("catalog recovery receipt changed; preserve for review")
                if updated != original:
                    _atomic_host_write(path, updated)
            elif result["status"] == "ALREADY_ABSENT" and policy.get("restored") is not True:
                return {"ok": True, "changed": False, "status": "RECOVERY_PROVENANCE_UNKNOWN",
                        "assurance": "UNKNOWN", "backing_artifact_status": "RETAINED_REFERENCE_SAFE"}
            return {"ok": True, **result, "backing_artifact_status": "RETAINED_REFERENCE_SAFE"}
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        return {"ok": False, "changed": False, "status": "CATALOG_RECOVERY_FAILED",
                "assurance": "UNKNOWN", "diagnostic": str(exc)}


def _session_start_recovery(home, identity, payload):
    """Deny uncertain restoration without blocking the native receiver.

    These checks select recovery only. Their failure must not skip ordinary
    project discovery or replace the original SessionStart result.
    """
    from . import lifecycle, task_authority
    from thaliris import core
    try:
        denied = (lifecycle._controller_actor_assurance(payload) == "CHILD" or
                  payload.get("readonly") is True or payload.get("fenced") is True)
        actor_root = lifecycle._hook_repository_root(Path.cwd(), payload)
        core.select_task(actor_root, lifecycle._associated_task(actor_root, payload))
        anchor = task_authority.read(actor_root)
        session_hash = lifecycle._session_id_hash(payload)
        if (anchor is not None and session_hash in anchor["fenced_sessions"] or
                lifecycle._session_fenced(actor_root, session_hash) or
                lifecycle._abandoned_child_fenced(actor_root, payload)):
            denied = True
        return ({"ok": True, "changed": False, "status": "ACTOR_RECOVERY_DENIED"}
                if denied else recover(home, identity))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        return {"ok": False, "changed": False, "status": "CATALOG_RECOVERY_FAILED",
                "assurance": "UNKNOWN", "diagnostic": str(exc)}


def main():
    import argparse
    import sys
    from . import runtime_identity
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--session-start", action="store_true", required=True)
    parser.add_argument("--managed-hook-abi", required=True)
    args = parser.parse_args()
    raw = sys.stdin.buffer.read()
    native_exit = 0
    startup_exit = 0
    try:
        installed = (args.home / runtime_identity.MANIFEST_NAME).read_bytes()
        manifest = runtime_identity.validate_manifest_record(installed)
        executable = Path(manifest["executable"])
        runtime_identity.validate_manifest(installed, executable, args.runtime_sha256)
        if (Path(manifest["package_dir"]).resolve() != Path(__file__).resolve().parent or
                Path(sys.executable).resolve() != (executable.parent / "python.exe").resolve()):
            raise ValueError("independent recovery must run the pinned installed package/interpreter")
        from . import lifecycle
        payload = json.loads(raw.decode("utf-8-sig"))
        if args.managed_hook_abi != lifecycle.MANAGED_HOOK_ABI:
            raise ValueError("native SessionStart hook ABI differs from pinned installation")
        payload_error = None
        try:
            validate_native_session_start(payload)
        except ValueError as exc:
            payload_error = exc
        if payload_error is not None:
            # Malformed actor data cannot authorize recovery, but the native
            # Hook still receives the original bytes below when project
            # dispatch is available.
            result = {"ok": False, "status": "CATALOG_RECOVERY_FAILED",
                      "assurance": "UNKNOWN", "diagnostic": str(payload_error)}
            startup_exit = 1
        else:
            result = _session_start_recovery(args.home, args.runtime_sha256, payload)
        # Keep the original receiver and native bytes, including actor fields,
        # BOM and transport whitespace. Project discovery controls dispatch
        # only; it never establishes the persistent restoration authority.
        dispatch = any((directory / ".codex" / "thaliris.json").exists()
                       for directory in (Path.cwd(), *Path.cwd().parents))
        if dispatch:
            import subprocess
            callback = subprocess.run([str(executable), "audit-hook", "SessionStart", "--managed-hook-abi", args.managed_hook_abi],
                                      input=raw, capture_output=True, env=runtime_identity.child_environment())
            sys.stdout.buffer.write(callback.stdout)
            sys.stderr.buffer.write(callback.stderr)
            native_exit = callback.returncode
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        result = {"ok": False, "status": "CATALOG_RECOVERY_FAILED", "assurance": "UNKNOWN", "diagnostic": str(exc)}
        startup_exit = 1
    print(json.dumps(result, sort_keys=True), file=sys.stderr)
    return native_exit if native_exit else startup_exit


if __name__ == "__main__":
    raise SystemExit(main())
