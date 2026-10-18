"""Release-first lifecycle; exact maintenance plans remain durable internally."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from . import host_maintenance, host_preflight, host_transition, release_acquire
from . import release_identity as identity, runtime_identity, runtime_setup

CANDIDATE_FORMAT = "thaliris-release-candidate-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _safe(path: Path) -> Path:
    path = path.absolute()
    if any(runtime_identity._is_link(p) for p in (path, *path.parents)):
        raise ValueError("release state path contains a link")
    return path


def _write_new(path: Path, value: dict) -> None:
    _safe(path)
    with path.open("xb") as stream:
        stream.write(identity.canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def _run(executable: str, arguments: list[str], *, home: Path, project: Path) -> dict:
    environment = runtime_identity.child_environment()
    environment["CODEX_HOME"] = str(home)
    result = subprocess.run([executable, "--root", str(project), *arguments],
                            env=environment, capture_output=True, text=True, timeout=180)
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("selected release console returned no JSON result: " + result.stderr[-2000:]) from exc
    if not isinstance(value, dict):
        raise ValueError("selected release console returned an invalid result")
    if result.returncode and value.get("ok"):
        raise ValueError("selected release console failed despite success response")
    return value


def _sha256_fact(value: object) -> str | None:
    return value if isinstance(value, str) and _SHA256.fullmatch(value) else None


def _project_host_relation(project: object, installed_expected: str | None) -> tuple[str, str, dict[str, str]]:
    if not isinstance(project, dict):
        return "UNKNOWN", "current_project_diagnostics_unavailable", {}
    actual = _sha256_fact(project.get("managed_instruction_sha256"))
    current_expected = _sha256_fact(project.get("expected_managed_instruction_sha256"))
    evidence = {
        "project_managed_instruction_sha256": actual or "UNKNOWN",
        "current_reader_expected_managed_instruction_sha256": current_expected or "UNKNOWN",
        "installed_reader_expected_managed_instruction_sha256": installed_expected or "UNKNOWN",
    }
    if actual is None or current_expected is None:
        return "UNKNOWN", "project_managed_instruction_hash_unavailable", evidence
    if installed_expected is None:
        return "UNKNOWN", "validated_installed_reader_definition_unavailable", evidence
    if actual == current_expected and current_expected != installed_expected:
        return "HOST_UPDATE_REQUIRED", "project_matches_current_reader_but_not_installed_reader", evidence
    if actual == current_expected:
        return "MATCH", "project_matches_current_and_installed_readers", evidence
    return "DIFFERENT", "project_differs_from_current_reader", evidence


def validate_candidate(record: dict, binding: dict) -> dict:
    identity.validate_binding(binding)
    if (not isinstance(record, dict) or set(record) != {"format", "selected"} or
            record["format"] != CANDIDATE_FORMAT or not isinstance(record["selected"], dict)):
        raise ValueError("invalid saved release candidate structure")
    selected_record = record["selected"]
    if (set(selected_record) != {"executable", "runtime_sha256", "source_pin", "release_binding"} or
            not isinstance(selected_record.get("executable"), str) or not selected_record["executable"] or
            not isinstance(selected_record.get("runtime_sha256"), str) or
            not isinstance(selected_record.get("source_pin"), str) or
            selected_record.get("release_binding") != binding):
        raise ValueError("saved candidate release binding differs")
    selected = selected_record
    executable, contents = host_maintenance.selected_runtime(selected)
    # selected_runtime verifies the final location, exact runtime bytes and
    # console origin. Host compatibility is probed anew on EVERY reuse.
    host_preflight.verify_runtime(executable, contents)
    return selected


def prepare(cache: Path, binding: dict, wheels: dict[str, Path]) -> dict:
    identity.validate_binding(binding)
    cache = _safe(cache)
    cache.mkdir(parents=True, exist_ok=True)
    for record_path in sorted(cache.glob("candidate-*.json")):
        try:
            runtime_identity._safe_file(record_path)
            return validate_candidate(json.loads(record_path.read_bytes()), binding)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError):
            # Drift is a cache miss. Preserve the original runtime and record.
            continue
    leaf = "runtime-" + uuid.uuid4().hex
    artifacts = binding["manifest"]["artifacts"]
    result = runtime_setup.create(cache / leaf,
        str(wheels["core"]) + "#sha256=" + artifacts["core"]["sha256"],
        str(wheels["adapter"]) + "#sha256=" + artifacts["adapter"]["sha256"])
    selected = {"executable": result["executable"], "runtime_sha256": result["runtime_sha256"],
                "source_pin": "sha256:" + artifacts["adapter"]["sha256"], "release_binding": binding}
    record = {"format": CANDIDATE_FORMAT, "selected": selected}
    validate_candidate(record, binding)
    _write_new(cache / ("candidate-" + uuid.uuid4().hex + ".json"), record)
    return selected


def status(home: Path, cache: Path, binding: dict | None, project: Path) -> dict:
    """Diagnostics do not mint ownership, future-reader trust or live loading."""
    result = {"ok": True, "available_release": binding, "prepared_candidates": [],
              "installed_disk": "ABSENT", "loaded_host": "UNKNOWN", "restart_required": "UNKNOWN",
              "project_definition": "UNKNOWN", "project_host_relation": "UNKNOWN",
              "project_host_relation_reason": "insufficient_verified_reader_facts",
              "project_host_relation_evidence": {},
              "manual_action_required": [], "user_data_policy": "PRESERVE",
              "saved_maintenance_plans": [], "release_relation": "UNKNOWN",
              "preserved_user_modifications": [],
              "host_surfaces": {"status": "UNKNOWN", "owned_files": {},
                                "preserved_user_modifications": [], "manual_action_required": []}}
    validated_installed_executable: str | None = None
    installed_reader_expected: str | None = None
    for path in sorted(_safe(cache).glob("candidate-*.json")):
        try:
            runtime_identity._safe_file(path)
            record = json.loads(path.read_bytes())
            selected = validate_candidate(record, record["selected"]["release_binding"])
            result["prepared_candidates"].append({"record": str(path), "status": "VALID", "selected": selected})
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            result["prepared_candidates"].append({"record": str(path), "status": "DRIFT", "error": str(exc)})
    try:
        result["transition_pending"] = host_transition.pending(home)
        if result["transition_pending"]:
            result["recovery_action"] = "Resume using the saved original maintenance contract"
            transition = json.loads((home / host_transition.NAME).read_bytes())
            if not isinstance(transition, dict) or transition.get("format") != host_transition.FORMAT:
                raise ValueError("invalid Host transition journal; preserve for review")
            result["pending_transition"] = {key: transition.get(key, "UNKNOWN")
                for key in ("phase", "operation", "contract_sha256")}
        for path in sorted(cache.glob("maintenance-*.json")):
            runtime_identity._safe_file(path)
            raw = path.read_bytes()
            intent = json.loads(raw)
            if isinstance(intent, dict) and intent.get("codex_home") == str(home):
                sha = identity.sha256(raw)
                result["saved_maintenance_plans"].append({"path": str(path), "sha256": sha,
                    "operation": intent.get("operation"), "matches_pending": result["transition_pending"] and
                    result["pending_transition"]["contract_sha256"] == sha})
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        result["ok"] = False
        result["manual_action_required"].append(str(exc))
    try:
        if (home / runtime_identity.MANIFEST_NAME).exists():
            result["installed_disk"] = "UNVERIFIED"
        installed = host_maintenance._installed(home)
        if installed:
            record = host_maintenance.ownership(home, installed, {})
            manifest = json.loads(installed)
            runtime_identity.validate_existing_manifest(installed, Path(manifest["executable"]), identity.sha256(installed))
            release_binding = record.get("release_binding") if record.get("format") == host_maintenance.RELEASE_RECEIPT_FORMAT else None
            if release_binding is not None:
                identity.validate_selected({"release_binding": release_binding, "source_pin": record["source_pin"]}, manifest)
            result["installed_disk"] = {"runtime_sha256": identity.sha256(installed),
                                        "release_binding": release_binding or "UNKNOWN", "runtime_status": "MATCH"}
            validated_installed_executable = str(manifest["executable"])
            if release_binding is not None:
                result["release_relation"] = ("UNKNOWN" if binding is None else
                                              "MATCH" if release_binding == binding else "DIFFERENT")
            result["host_surfaces"] = host_maintenance.surface_status(home, record)
            result["manual_action_required"].extend(result["host_surfaces"]["manual_action_required"])
            result["preserved_user_modifications"] = result["host_surfaces"]["preserved_user_modifications"]
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        result["ok"] = False
        result["manual_action_required"].append(str(exc))
    if validated_installed_executable is not None:
        try:
            installed_facts = _run(validated_installed_executable, ["bootstrap-check"], home=home, project=project)
            if installed_facts.get("ok") is True:
                installed_reader_expected = _sha256_fact(installed_facts.get("expected_managed_instruction_sha256"))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
            # A verified executable can still lack a usable diagnostic protocol.
            # Keep the relation unknown; status never predicts Host activation.
            installed_reader_expected = None
    try:
        # The current release reader is read-only. Pass the selected home
        # explicitly so project facts cannot fall back to the caller's default.
        from . import codex_adapter
        selected_reader_verified = False
        if binding is not None:
            try:
                current_manifest = identity.validate_binding(binding)
                identity.validate_selected(
                    {"release_binding": binding,
                     "source_pin": "sha256:" + current_manifest["artifacts"]["adapter"]["sha256"]},
                    {"package_dir": str(Path(codex_adapter.__file__).parent)},
                )
                selected_reader_verified = True
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                pass
        result["project_definition"] = codex_adapter.bootstrap_check(project, codex_home=home)
        relation, reason, evidence = _project_host_relation(result["project_definition"], installed_reader_expected)
        result["project_host_relation"] = relation if selected_reader_verified else "UNKNOWN"
        result["project_host_relation_reason"] = reason if selected_reader_verified else "selected_reader_provenance_unavailable"
        result["project_host_relation_evidence"] = evidence
        if selected_reader_verified and relation == "HOST_UPDATE_REQUIRED":
            result["manual_action_required"].append(
                "HOST_UPDATE_REQUIRED: update the Thaliris runtime to the selected release before initializing this project."
            )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        result["ok"] = False
        result["manual_action_required"].append(str(exc))
    return result


def maintain(action: str, selected: dict, home: Path, project: Path, cache: Path,
             instruction: str, *, resume: Path | None = None, actor: dict | None = None,
             refresh_model_catalog: bool = False) -> dict:
    """No broad legacy adoption or repair permission is inferred from action."""
    if action not in {"install", "update", "repair", "uninstall"}:
        raise ValueError("unknown Host maintenance action")
    if not instruction.strip():
        raise ValueError("maintenance requires the actual human instruction")
    if actor and (actor.get("agent_id") is not None or actor.get("agent_type") is not None or
                  actor.get("readonly") is True or actor.get("fenced") is True or actor.get("abandoned") is True):
        raise ValueError("HOST_MAINTENANCE_ACTOR_DENIED")
    operation = "codex-uninstall" if action == "uninstall" else "codex-install"
    if resume:
        # The original durable bytes, including instruction and prior identity,
        # are replayed. No replacement plan may approve a partial generation.
        host_maintenance.safe(resume)
        intent = json.loads(resume.read_bytes())
        if intent.get("operation") != operation or Path(intent.get("codex_home", "")) != home:
            raise ValueError("saved maintenance plan differs from requested operation/home")
        selected = intent["executor"]
        contract = resume
    else:
        if host_transition.pending(home):
            raise ValueError("HOST_TRANSITION_PENDING: use --resume with original saved contract")
        planned = _run(selected["executable"], ["codex-maintenance-plan", operation,
            "--executable", selected["executable"], "--source-pin", selected["source_pin"],
            "--human-instruction", instruction], home=home, project=project)
        if not planned.get("ok"):
            return planned
        intent = planned["maintenance_contract"]
        intent["executor"] = selected
        if operation == "codex-install":
            intent["candidate"] = selected
            intent["refresh_model_catalog"] = refresh_model_catalog
        _safe(cache).mkdir(parents=True, exist_ok=True)
        contract = cache / ("maintenance-" + uuid.uuid4().hex + ".json")
        _write_new(contract, intent)
    try:
        host_maintenance.contract(contract, operation, home, actor=actor)
        outcome = _run(selected["executable"], [operation, "--maintenance-contract", str(contract)], home=home, project=project)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        outcome = {"ok": False, "error": str(exc), "manual_action_required": [str(exc)],
                   "recovery_action": "Preserve this exact saved contract; inspect status and retry with --resume"}
    return {**outcome, "saved_contract": str(contract), "release_binding": selected.get("release_binding"),
            "loaded_host": "UNKNOWN"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "install", "update", "repair", "uninstall", "status"])
    parser.add_argument("--manifest", required=True, help="manifest file or HTTPS URL")
    parser.add_argument("--manifest-sha256", required=True, help="externally trusted manifest digest")
    parser.add_argument("--artifacts", type=Path, help="already verified/staged wheel directory")
    parser.add_argument("--cache", type=Path, help="final physical runtime/state directory")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--human-instruction", default="")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--refresh-model-catalog", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.resume and args.action not in {"install", "update", "repair", "uninstall"}:
            raise ValueError("--resume applies only to Host maintenance")
        home, project = args.home.absolute(), args.project.absolute()
        # Observe selected manifest without building a runtime for status.
        raw = (release_acquire.download(args.manifest, limit=1024 * 1024) if args.manifest.startswith("https://")
               else Path(args.manifest).read_bytes())
        binding = identity.binding(raw, args.manifest_sha256)
        cache = _safe(args.cache) if args.cache else runtime_setup.default_runtime_directory(
            "git+https://github.com/" + identity.REPOSITORY + "@" + binding["manifest"]["adapter_commit"]).parent
        if args.action == "status":
            out = status(home, cache, binding, project)
        elif args.resume:
            out = maintain(args.action, {}, home, project, cache, args.human_instruction, resume=args.resume.absolute())
        else:
            if args.action != "prepare" and not args.human_instruction.strip():
                raise ValueError("maintenance requires --human-instruction with the actual human request")
            if args.artifacts:
                wheels = {name: args.artifacts.absolute() / artifact["filename"]
                          for name, artifact in binding["manifest"]["artifacts"].items()}
            else:
                _, wheels = release_acquire.acquire(args.manifest, args.manifest_sha256,
                    cache / ("download-" + uuid.uuid4().hex))
            selected = prepare(cache, binding, wheels)
            out = ({"ok": True, "selected": selected, "host_installed": False} if args.action == "prepare" else
                   maintain(args.action, selected, home, project, cache, args.human_instruction,
                            refresh_model_catalog=args.refresh_model_catalog))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        out = {"ok": False, "error": str(exc), "loaded_host": "UNKNOWN", "manual_action_required": [str(exc)]}
    print(json.dumps(out))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
