"""Run explicitly approved Host maintenance without the installed Hook/runner.

Use a separate Python and reviewed repository sources. This grants no project
authority, disconnects no integration, and reuses normal maintenance ownership,
exact runtime/provenance checks and the existing recoverable generation journal.
Human authorization is required; the contract records intent, not authentication.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-source-root", type=Path, required=True)
    parser.add_argument("--maintenance-contract", type=Path, required=True)
    args = parser.parse_args()
    try:
        # Reuse the offline route's reviewed-source import boundary. Importing
        # this helper performs no recovery and touches no project control state.
        helper = Path(__file__).with_name("thaliris_offline_recovery.py")
        spec = importlib.util.spec_from_file_location("reviewed_source_loader", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.meta_path.insert(0, module.ReviewedSource(args.core_source_root))
        from thaliris_codex import host_maintenance, runtime_identity, host_preflight
        host_maintenance.safe(args.maintenance_contract)
        selected = json.loads(args.maintenance_contract.read_bytes())
        operation = selected.get("operation")
        if operation not in {"codex-install", "codex-uninstall"}:
            raise ValueError("only explicitly contracted Host maintenance is supported")
        home = Path(selected.get("codex_home", ""))
        intent = host_maintenance.contract(args.maintenance_contract, operation, home)
        executable, contents = host_maintenance.selected_runtime(intent["executor"])
        # The independently reviewed verifier and the approved executor must be
        # the same source, not just similarly named installations.
        package = Path(json.loads(contents)["package_dir"])
        source = Path(__file__).resolve().parents[1] / "src" / "thaliris_codex"
        reviewed = {p.relative_to(source): p.read_bytes() for p in source.rglob("*.py")}
        installed = {p.relative_to(package): p.read_bytes() for p in package.rglob("*.py")}
        if reviewed != installed:
            raise ValueError("reviewed adapter source differs from selected executor")
        host_preflight.verify_runtime(executable, contents)
        environment = runtime_identity.child_environment()
        environment["CODEX_HOME"] = str(home)
        command = [str(executable), operation, "--maintenance-contract", str(args.maintenance_contract)]
        if operation == "codex-install" and intent.get("execution_constraint"):
            command += ["--execution-constraint", intent["execution_constraint"]]
        # Only this exact, already validated immutable executor may dispatch.
        return subprocess.run(command, env=environment, check=False).returncode
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "changed": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
