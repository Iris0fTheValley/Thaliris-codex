"""Console interface: every normal stdout response is exactly one JSON value."""
from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from . import __version__
from . import codex_adapter, codex_bootstrap, lifecycle, task_authority, roles, host_maintenance, runtime_identity, diagnostics, observation_transport, project_identity
from thaliris import core, identity
from thaliris.errors import TASK_REVISION_CONFLICT, ThalirisError, error_envelope
from thaliris.core import TaskStateSchemaIncompatible, artifact_get, catalog, document_get, milestone_check, rollback, stale, task_artifact, task_get, task_promote, task_show, task_status, task_update


class _Parser(argparse.ArgumentParser):
    """Normal errors are machine-readable too; help remains argparse-native."""
    def error(self, message: str) -> None:
        raise ValueError(message)


def _task_status(root: Path, *, suppress_protocol_notice: bool, evidence_offset: int = 0,
                 view: str = "compact", since_revision: int | None = None) -> dict[str, object]:
    """Attach the one-shot lifecycle notice at the Codex CLI boundary."""
    anchor = task_authority.read(root)
    if anchor is not None:
        try:
            task_authority.check(root)
            conflict = False
        except (ValueError, OSError):
            conflict = True
        if conflict:
            return {"ok": False, "status": "TASK_AUTHORITY_CONFLICT", "task_id": anchor["task_id"],
                    "authority_sha256": task_authority.digest(task_authority.path(root)),
                    "recovery_action": "task-recover-authority --expected-authority-sha256 <authority_sha256> --reason <reason>"}
    out = task_status(root, evidence_offset=evidence_offset, view=view, since_revision=since_revision)
    identity_summary = project_identity.summary(root)
    if identity_summary is not None:
        out["Project Identity"] = identity_summary
    if anchor is not None:
        out["Task Authority"] = {"status": anchor["status"], "provenance": anchor["provenance"],
                                 "execution_mode": anchor["contract"]["execution_mode"],
                                 "host_actor_assurance": "UNKNOWN", "authority_sha256": task_authority.digest(task_authority.path(root))}
    if not suppress_protocol_notice:
        notice = lifecycle.consume_protocol_deviation_notice(root, str(out["Task"]["id"]))
        if notice is not None:
            out["Protocol deviation"] = notice
    return out


def _controller_evidence_output(root: Path, args: argparse.Namespace, out: dict) -> dict:
    """Retain decision evidence beside Controller operation results.

    The evidence is the Core compact summary: totals plus a bounded list of
    open items (paged by ``next_offset``), not the full Evidence Continuity
    page. A write response that already carries it, and a revision conflict
    whose ``changes_since`` embeds it, are not given a second copy.
    """
    if args.command not in {
        "task-update", "task-artifact", "task-promote", "task-evidence-register",
        "task-judge", "task-close", "task-mode", "task-dispose-dependency",
        "task-observe", "document-maintain", *project_identity.MUTATIONS,
    } or getattr(args, "role", "controller") != "controller":
        return out
    if "evidence" in out or out.get("code") == TASK_REVISION_CONFLICT:
        return out
    try:
        state = core._load_state(root)
        if state.get("evidence_continuity"):
            return {**out, "evidence": core.evidence_summary(state)}
    except (ValueError, OSError, RuntimeError):
        return {**out, "evidence": {"status": "UNKNOWN"}}
    return out


@contextlib.contextmanager
def _inline_input(value: str | None, input_path: str | None):
    """Yield the one input path for a Controller operation.

    ``--input`` is a file path (``-`` reads stdin). ``--json`` carries one inline
    JSON object, optionally in the ``utf8-base64:`` transport that the PreToolUse
    hook applies to a single-quoted literal so shell quoting cannot alter it.
    The decoded object is handed to Core through a private temporary file, so
    Core's decoding, validation and error contract stay the single path.
    """
    if (value is None) == (input_path is None):
        raise ThalirisError("INPUT_SOURCE_INVALID", "exactly one of --input or --json is required",
                            recovery="pass --input <file|-> or --json '<one JSON object>'")
    if input_path is not None:
        yield input_path
        return
    try:
        body = observation_transport.decode(value)
    except ValueError as exc:
        raise ThalirisError(
            "INPUT_JSON_INVALID", "invalid --json: " + str(exc),
            recovery="supply one JSON object, or use --input <file|->",
        ) from exc
    if not isinstance(body, dict):
        raise ThalirisError("INPUT_NOT_OBJECT", "task input must be a JSON object",
                            recovery="wrap the payload in a JSON object")
    with tempfile.TemporaryDirectory(prefix="thaliris-json-") as directory:
        path = Path(directory) / "input.json"
        path.write_bytes(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        yield str(path)


def _write_utf8(text: str, *, newline: bool = True) -> None:
    """Write text as UTF-8 bytes, independent of the process console code page.

    Output that keeps non-ASCII characters (bootstrap, controller guidance and
    hook context) must not be re-encoded by a locale code page such as cp1252
    or cp936. Other commands stay ASCII-escaped JSON.
    """
    text = text + "\n" if newline else text
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _write_utf8_line(text: str) -> None:
    _write_utf8(text)


def _add_global_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options accepted before a command.

    The command probe below intentionally uses this same grammar.  Keeping
    these declarations in one place prevents schema routing from drifting
    away from the real CLI parser when a global option is added or its
    argparse behaviour changes.
    """
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", dest="selected_task_id", help="explicit task selection; not an authority grant")
    parser.add_argument("--session-id", help="Controller-selected session association; Host assurance remains UNKNOWN")


_INPUT_HELP = {
    "task-update": "append mechanical ledger records with strict revision CAS",
    "task-evidence-register": "register requirements and handoffs with strict revision CAS",
    "task-judge": 'record one judgment object, or an atomic ordered batch {"judgments":[...]} in one revision',
}


def _parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="thaliris",
        description=(
            "Thaliris: durable records, identities, provenance, explicit retrieval, "
            "and lifecycle binding for Codex workflows"
        ),
    )
    _add_global_arguments(p)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("runtime-check", help="report this public console's interpreter and package origin without mutation")
    q = sub.add_parser("execution-wait", help="retrieve packaged helper or run an owned foreground observation")
    q.add_argument("--tool-source", action="store_true", help="include packaged JS source in the read-only guide")
    q.add_argument("arguments", nargs=argparse.REMAINDER)
    controller_help = sub.add_parser("controller-instructions", help="list or retrieve Controller procedures without admission or mutation")
    from . import controller_instructions
    controller_selection = controller_help.add_mutually_exclusive_group()
    controller_selection.add_argument("--section", choices=controller_instructions.SECTIONS)
    controller_selection.add_argument("--resident", action="store_true", help="retrieve complete normal Controller guidance")
    q = sub.add_parser("init")
    q.add_argument(
        "--accept-managed-instruction-sha256",
        help="explicitly authorize replacement of exactly this current managed instruction block",
    )
    for name in ("bootstrap-check", "doctor", "stale", "milestone-check", "memory-status", "uninstall"):
        sub.add_parser(name)
    install = sub.add_parser("codex-install", help="install stable Thaliris Host identities and hook ABI")
    install.add_argument("--executable", help="absolute Thaliris executable for Host hooks")
    install.add_argument("--sha256", help="exact SHA-256 pin for --executable")
    install.add_argument("--execution-constraint", choices=roles.EXECUTION_CONSTRAINTS, help="install constrained execution bindings for the same semantic roles; tasks must explicitly select the matching constraint")
    install.add_argument("--maintenance-contract", required=True, metavar="FILE", help="UTF-8 JSON selecting actual human Host maintenance intent and immutable candidate")
    remove = sub.add_parser("codex-uninstall", help="remove only Thaliris-owned Host integration")
    remove.add_argument("--maintenance-contract", required=True, metavar="FILE")
    plan = sub.add_parser("codex-maintenance-plan", help="inspect identities and propose a Host maintenance contract without approving ownership")
    plan.add_argument("operation", choices=("codex-install", "codex-uninstall"))
    plan.add_argument("--executable", required=True)
    plan.add_argument("--source-pin", required=True)
    plan.add_argument("--human-instruction", required=True)
    plan.add_argument("--refresh-model-catalog", action="store_true", help="explicitly request an upstream catalog refresh")
    plan.add_argument("--execution-constraint", choices=roles.EXECUTION_CONSTRAINTS)
    plan.add_argument("--catalog-recovery-project-root", type=Path, help="propose SessionStart catalog restoration after loss of this project's activation marker; defaults to --root")
    plan.add_argument("--catalog-recovery-source-root", type=Path, help="also propose restoration when this explicitly selected source directory disappears")
    q = sub.add_parser("codex-bootstrap", help="perform one-shot project-external Codex bootstrap")
    q.add_argument("--hook-attestation", help=argparse.SUPPRESS)
    q.add_argument("--controller-guidance-sha256", help="omit exact guidance already present in the current context")
    q = sub.add_parser("catalog", help="discover bounded durable document metadata")
    q.add_argument("path", nargs="?")
    q = sub.add_parser("document-get", help="retrieve 1 to 8 explicitly selected durable documents")
    q.add_argument("path", nargs="+")
    sub.add_parser("identity-status", help="read-only Project Identity state and one-line summary")
    q = sub.add_parser("identity-get", help="read the recorded identity, selected items, or one amendment or challenge")
    q.add_argument("--version", type=int)
    q.add_argument("--item", action="append")
    q.add_argument("--amendment")
    q.add_argument("--challenge")
    q = sub.add_parser("identity-trace", help="trace registered relations around one reference; registered relations only")
    q.add_argument("ref")
    q.add_argument("--direction", choices=("up", "down", "both"), default="both")
    q.add_argument("--depth", type=int, default=1)
    for name in project_identity.MUTATIONS:
        q = sub.add_parser(name, help="Controller-only Project Identity record (needs the selected ACTIVE task)")
        q.add_argument("--role", required=True, choices=codex_adapter.role_choices())
        q.add_argument("--base-revision", required=True, type=int)
        q.add_argument("--input", required=True)
    q = sub.add_parser("identity-note", help="Controller-only: record, retract or list the user's verbatim long-term project statements (no task needed)")
    q.add_argument("--role", required=True, choices=codex_adapter.role_choices())
    source = q.add_mutually_exclusive_group()
    source.add_argument("--input", help="JSON object file path, or - for stdin: {quote,kind?,context?,refs?} or {retract,reason}")
    source.add_argument("--json", help="one inline JSON object (single-quoted literal or utf8-base64:...)")
    source.add_argument("--list", action="store_true", help="list noted statements")
    q.add_argument("--include-retracted", action="store_true", help="with --list, include retracted notes")
    q = sub.add_parser("identity-suggest", help="Controller-only: set or clear the identity-offer preference at a scope, only on the user's words (no task needed)")
    q.add_argument("--role", required=True, choices=codex_adapter.role_choices())
    q.add_argument("--scope", required=True, choices=("session", "workspace", "project", "global"))
    setting = q.add_mutually_exclusive_group(required=True)
    setting.add_argument("--on", action="store_true")
    setting.add_argument("--off", action="store_true")
    setting.add_argument("--clear", action="store_true")
    q = sub.add_parser("task-start")
    q.add_argument("goal")
    q.add_argument("--milestone")
    q.add_argument("--input")
    q.add_argument("--authority-contract", metavar="FILE_PATH", help="path to a UTF-8 JSON file with the Controller-selected task contract; inline JSON is not accepted")
    q.add_argument("--hook-attestation", help=argparse.SUPPRESS)
    q.add_argument("--bootstrap-receipt", dest="bootstrap_receipt")
    q.add_argument("--controller-bridge-sha256", help=argparse.SUPPRESS)
    q = sub.add_parser("task-abandon", help="explicitly archive and release an incomplete ACTIVE task")
    q.add_argument("--task-id", required=True)
    q.add_argument("--revision", required=True, type=int)
    q.add_argument("--state-sha256", required=True)
    q.add_argument("--lifecycle-sha256", required=True)
    q.add_argument("--reason", required=True)
    q.add_argument("--hook-attestation", help=argparse.SUPPRESS)
    q = sub.add_parser("task-recover-authority", help="continue existing authority: preserve conflicts, restore recorded intent and baseline, fence known old children")
    q.add_argument("--expected-authority-sha256", required=True)
    q.add_argument("--reason", required=True)
    q = sub.add_parser("task-recover-state", help="archive an incompatible task state before starting a new task")
    q.add_argument("--expected-sha256", required=True)
    q.add_argument("--abandon-active", action="store_true", help="confirm abandonment of the archived ACTIVE task")
    q.add_argument("--hook-attestation", help=argparse.SUPPRESS)
    q.add_argument("--controller-bridge-sha256", help=argparse.SUPPRESS)
    q = sub.add_parser("task-dispose-dependency", help="abandon a selected dependency; native execution and writing risk remain UNKNOWN")
    selector = q.add_mutually_exclusive_group(required=True)
    selector.add_argument("--handoff-id")
    selector.add_argument("--conflict-id", help="exact identity-conflict id named by a THALIRIS_NATIVE_IDENTITY_COLLISION refusal")
    q.add_argument("--base-revision", type=int, required=True)
    q.add_argument("--expected-lifecycle-sha256", required=True)
    q.add_argument("--reason", required=True)
    q = sub.add_parser("task-associate", help="explicitly associate this session with the selected task")
    q.add_argument("--expected-authority-sha256", required=True)
    q = sub.add_parser("task-mode", help="Controller-selected execution mode transition with authority and revision CAS")
    q.add_argument("--mode", choices=task_authority.MODES, required=True)
    q.add_argument("--human-instruction", required=True)
    q.add_argument("--base-revision", type=int, required=True)
    q.add_argument("--expected-authority-sha256", required=True)
    for name in ("task-update", "task-evidence-register", "task-judge", "document-maintain"):
        q = sub.add_parser(name, help=_INPUT_HELP.get(name))
        q.add_argument("--role", required=True, choices=codex_adapter.role_choices())
        q.add_argument("--base-revision", required=True, type=int)
        if name == "document-maintain":
            q.add_argument("--input", required=True)
        else:
            source = q.add_mutually_exclusive_group(required=True)
            source.add_argument("--input", help="JSON object file path, or - for stdin")
            source.add_argument("--json", help="one inline JSON object (single-quoted literal or utf8-base64:...)")
        if name == "task-evidence-register":
            q.add_argument("--controller-session-id-hash", help=argparse.SUPPRESS)
        if name == "document-maintain":
            q.add_argument("--task-id", help="exact task selection supplied by the native handoff")
            q.add_argument("--handoff-id")
    q = sub.add_parser("task-observe", help="append own selected local observation without task revision CAS")
    q.add_argument("--role", required=True, choices=codex_adapter.role_choices())
    q.add_argument("--task-id", help="exact task selection supplied by the native handoff")
    q.add_argument("--handoff-id")
    q.add_argument("--agent-id-hash")
    observation = q.add_mutually_exclusive_group(required=True)
    observation.add_argument("--input")
    observation.add_argument("--observation-json", help="one inline JSON observation; useful to readonly native roles")
    sub.add_parser("task-show")
    q = sub.add_parser("task-status", help="bounded Controller routing packet (compact by default)")
    q.add_argument("--view", choices=("compact", "full"), default="compact",
                   help="compact: counts plus open evidence summary; full: Evidence Continuity page")
    q.add_argument("--since-revision", type=int, help="add a bounded review hint for changes after this revision")
    q.add_argument("--evidence-offset", type=int, default=0)
    q.add_argument("--suppress-protocol-notice", action="store_true", help=argparse.SUPPRESS)
    q = sub.add_parser("task-get", help="retrieve one current-task object by ID")
    q.add_argument("id")
    q = sub.add_parser("artifact-get", help="retrieve one bounded task Artifact body by ID")
    q.add_argument("id")
    q = sub.add_parser("task-artifact", help="register a bounded external task artifact pointer")
    q.add_argument("--role", default="controller", choices=codex_adapter.role_choices())
    q.add_argument("--base-revision", required=True, type=int)
    q.add_argument("--id", required=True)
    q.add_argument("--path", required=True)
    q.add_argument("--summary", required=True)
    q.add_argument("--producer-role", choices=codex_adapter.role_choices())
    q.add_argument("--source-ref", action="append", default=[])
    q.add_argument("--supersedes", action="append", default=[])
    q = sub.add_parser("task-close")
    q.add_argument("--base-revision", required=True, type=int)
    q = sub.add_parser(
        "task-promote",
        help="persist Controller-selected durable records",
        description="Store exactly the records selected by the Controller; metadata is descriptive only.",
        epilog=(
            'Example: {"records":[{"id":"D1","path":".agent-memory/architecture/d1.md",'
            '"title":"Decision","text":"..."}],"index_update":{"path":".agent-memory/INDEX.md",'
            '"base_sha256":"<current-index-sha256>","content":"<complete model-authored INDEX.md>"}}'
        ),
    )
    q.add_argument("--role", required=True, choices=codex_adapter.role_choices())
    q.add_argument("--base-revision", required=True, type=int)
    q.add_argument("--input", required=True)
    q = sub.add_parser("rollback")
    q.add_argument("backup")
    sub.add_parser("version")
    q = sub.add_parser("audit-hook", help=argparse.SUPPRESS)
    q.add_argument("event", choices=("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop", "Stop"))
    q.add_argument("--managed-hook-abi", help=argparse.SUPPRESS)
    q.add_argument("--maintenance-replay-contract", help=argparse.SUPPRESS)
    return p


def _request_parser() -> argparse.ArgumentParser:
    """Build a non-exiting parser for the first command positional.

    Unknown command-local options belong to ``remainder``.  The parser still
    uses the real global-option grammar, including argparse's option
    abbreviations and end-of-options marker, so command classification stays
    aligned with execution parsing without invoking any command behaviour.
    """
    p = _Parser(prog="thaliris", add_help=False)
    # ``ArgumentParser`` normally wires these to an exiting ``help`` action.
    # The probe must be safe to call while preparing an error response, so
    # retain the same zero-argument arity with a non-exiting flag instead.
    p.add_argument("-h", "--help", action="store_true", help=argparse.SUPPRESS)
    _add_global_arguments(p)
    p.add_argument("command", nargs="?")
    p.add_argument("remainder", nargs=argparse.REMAINDER)
    return p


def _requested_command(argv: list[str]) -> str | None:
    """Return the command resolved by the shared global-option grammar."""
    try:
        args, _unknown = _request_parser().parse_known_args(argv)
    except ValueError:
        return None
    return args.command


def _identity_session_key(root: Path, args: argparse.Namespace) -> str | None:
    """One stable, adapter-derived session key for identity suggestion scope.

    An explicit --session-id wins (hashed); otherwise the selected task's
    recorded Controller owner hash is used, so suggest, status and the close
    offer agree without the Controller repeating a flag. None when neither
    exists, which Core treats as "no session scope".
    """
    if getattr(args, "session_id", None):
        return lifecycle._identity_hash(args.session_id)
    try:
        task_id = core.selected_task(root)
        return lifecycle.active_controller_owner(root, str(task_id)) if task_id else None
    except Exception:  # noqa: BLE001 - a missing key only disables session scope
        return None


def main(argv: list[str] | None = None) -> int:
    # Let formatting be placed before or after a subcommand without changing
    # the command schema or emitting non-JSON normal output.
    if argv is None:
        argv = sys.argv[1:]
    if "--pretty" in argv:
        argv = ["--pretty", *[arg for arg in argv if arg != "--pretty"]]
    # Preserve the bootstrap protocol field even when argparse rejects the
    # invocation before it can construct ``args``.  This is deliberately
    # scoped to the codex-bootstrap command; other command error schemas stay
    # unchanged.  Classify the effective argv after the existing pretty-option
    # normalization so the probe and real parser see identical input.
    bootstrap_requested = _requested_command(argv) == "codex-bootstrap"
    args = None
    root = None
    try:
        args = _parser().parse_args(argv)
        if args.command == "runtime-check":
            invoked = Path(sys.argv[0])
            if sys.platform == "win32" and invoked.suffix != ".exe":
                invoked = Path(str(invoked) + ".exe")
            out = {"ok": True, "executable": str(invoked.resolve(strict=True)),
                   "interpreter": str(Path(sys.executable).resolve(strict=True)),
                   "venv_dir": str(Path(sys.prefix).resolve(strict=True)),
                   "package_dir": str(Path(__file__).resolve(strict=True).parent),
                   "bytecode_disabled": sys.dont_write_bytecode}
            print(json.dumps(out, sort_keys=True, separators=(",", ":")))
            return 0
        root = args.root.resolve()
        if args.command == "execution-wait" and not args.arguments:
            from .execution_observation import guide
            _write_utf8_line(json.dumps(guide(include_source=args.tool_source), ensure_ascii=False))
            return 0
        command_task_id = getattr(args, "task_id", None) if args.command in {"task-abandon", "task-observe", "document-maintain"} else None
        if args.selected_task_id and command_task_id and args.selected_task_id != command_task_id:
            raise ValueError("conflicting selected task IDs")
        selected = args.selected_task_id or command_task_id
        if selected is None and args.session_id:
            selected = lifecycle._associated_task(root, {"session_id": args.session_id})
        core.select_task(root, selected)
        if args.command in {"task-update", "task-artifact", "task-close", "task-promote", "task-mode", "task-associate", "task-dispose-dependency", "task-recover-authority", "task-recover-state", "task-evidence-register", "task-observe", "task-judge", "document-maintain", *project_identity.MUTATIONS} and selected is None:
            raise ValueError("explicit --task-id or associated --session-id required for managed control")
        if args.command == "controller-instructions":
            from . import controller_instructions
            runner = controller_instructions.runner_command(codex_adapter._codex_home() / lifecycle.HOST_RUN_SCRIPT_NAME)
            if args.resident:
                delivery = controller_instructions.guidance_delivery_fields(runner)
                _write_utf8_line(json.dumps({
                    "ok": True,
                    "controller_guidance_sha256": delivery["controller_guidance_sha256"],
                    "controller_guidance_utf8_bytes": delivery["controller_guidance_utf8_bytes"],
                    "content": delivery["controller_guidance"],
                }, ensure_ascii=False))
            else:
                content = (controller_instructions.render(runner, section=args.section) if args.section
                           else controller_instructions.index(runner))
                _write_utf8_line(json.dumps({"ok": True, "content": content}, ensure_ascii=False))
            return 0
        from . import host_transition
        if args.command not in {"codex-install", "codex-uninstall", "codex-maintenance-plan", "audit-hook", "version"} and host_transition.pending(codex_adapter._codex_home()):
            raise ValueError("HOST_TRANSITION_PENDING: replay the original standalone maintenance contract")
        if args.command in {"task-update", "task-artifact", "task-close", "task-promote", "task-mode", "task-associate", "task-dispose-dependency", "task-evidence-register", "task-observe", "task-judge", "document-maintain", *project_identity.MUTATIONS}:
            task_authority.check(root)
        if args.command == "audit-hook":
            stage = "receive"
            try:
                raw = sys.stdin.buffer.read()
                # A single document-leading UTF-8 BOM is transport syntax,
                # not actor data. Strict decoding preserves all JSON content.
                stage = "decode"
                decoded = raw.decode("utf-8-sig")
                stage = "json"
                payload = json.loads(decoded)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                diagnostics.failure(stage)
                payload = None
            else:
                if not isinstance(payload, dict):
                    diagnostics.failure("json-shape")
            if args.maintenance_replay_contract is not None:
                response = lifecycle.maintenance_replay_check(root, payload, args.maintenance_replay_contract)
            else:
                response = codex_adapter.audit_hook(root, args.event, payload, args.managed_hook_abi)
            if response:
                _write_utf8(response, newline=False)
            return 0
        if args.command == "execution-wait":
            if args.tool_source:
                raise ValueError("--tool-source is retrieval only")
            from .execution_wait import main as observe
            return observe(args.arguments)
        if args.command == "init": out = codex_adapter.init(root, accept_managed_instruction_sha256=args.accept_managed_instruction_sha256)
        elif args.command == "bootstrap-check": out = codex_adapter.bootstrap_check(root)
        elif args.command in {"codex-install", "codex-uninstall"}:
            intent = host_maintenance.contract(args.maintenance_contract, args.command, codex_adapter._codex_home())
            executor, executor_bytes = host_maintenance.selected_runtime(intent["executor"])
            if Path(json.loads(executor_bytes)["package_dir"]).resolve() != Path(__file__).resolve().parent:
                raise ValueError("Host maintenance executor import origin differs from approved identity")
            interpreter = executor.parent / ("python.exe" if sys.platform == "win32" else "python")
            invoked = Path(sys.argv[0])
            # pip's Windows console launcher removes its .exe suffix in the
            # embedded __main__.py before calling this entry point.
            if sys.platform == "win32" and executor.suffix == ".exe" and invoked.suffix != ".exe":
                invoked = Path(str(invoked) + ".exe")
            if Path(sys.executable).resolve() != interpreter.resolve() or invoked.resolve() != executor:
                raise ValueError("Host maintenance must run the exact approved standalone executor")
            if args.command == "codex-install":
                out = codex_adapter.codex_install(executable=args.executable, executable_sha256=args.sha256, execution_constraint=args.execution_constraint, maintenance_contract=args.maintenance_contract)
            else:
                out = codex_adapter.codex_uninstall(maintenance_contract=args.maintenance_contract)
        elif args.command == "codex-maintenance-plan":
            home = codex_adapter._codex_home()
            if host_transition.pending(home):
                raise ValueError("HOST_TRANSITION_PENDING: replay the original maintenance contract; do not approve a partial generation")
            executable = Path(args.executable).resolve(strict=True)
            selected = {"executable": str(executable),
                "runtime_sha256": host_maintenance.digest(runtime_identity.manifest_bytes(executable)),
                "source_pin": args.source_pin}
            host_maintenance.selected_runtime(selected)
            prior = host_maintenance._installed(home)
            values = host_maintenance._files(home)
            snapshot = {name: host_maintenance.digest(value) for name, value in values.items()
                        if name not in {"AGENTS.md", "thaliris-install.json", host_maintenance.RECEIPT_NAME}}
            global_span = host_maintenance._global_owned_bytes(values.get("AGENTS.md", b""))
            if global_span is not None:
                snapshot["AGENTS.md#global"] = host_maintenance.digest(global_span)
            intent = {"format": host_maintenance.FORMAT, "operation": args.operation,
                "codex_home": str(home), "human_instruction": args.human_instruction,
                "executor": selected, "installed_runtime_sha256": host_maintenance.digest(prior) if prior else "ABSENT",
                "legacy_owned_bytes": {}}
            if args.operation == "codex-install":
                intent.update(candidate=selected, execution_constraint=args.execution_constraint)
                if args.refresh_model_catalog:
                    intent["refresh_model_catalog"] = True
                intent["catalog_recovery_project_root"] = str((args.catalog_recovery_project_root or root).resolve())
                if args.catalog_recovery_source_root is not None:
                    intent["catalog_recovery_source_root"] = str(args.catalog_recovery_source_root.resolve())
            out = {"ok": True, "maintenance_contract": intent,
                "ownership_review_snapshot": snapshot, "ownership_approved": False,
                "host_actor_assurance": "UNKNOWN", "project_files_touched": []}
        elif args.command == "codex-bootstrap":
            try:
                if args.controller_guidance_sha256 is None:
                    out = (codex_bootstrap.bootstrap(root, args.hook_attestation)
                           if args.hook_attestation else codex_bootstrap.bootstrap(root))
                else:
                    out = codex_bootstrap.bootstrap(
                        root,
                        args.hook_attestation,
                        controller_guidance_sha256=args.controller_guidance_sha256,
                    )
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                out = {
                    "ok": False,
                    "status": "BOOTSTRAP_UNAVAILABLE",
                    "error": str(exc),
                    "session_restart_required": False,
                    **codex_bootstrap.controller_guidance_fields(args.controller_guidance_sha256),
                }
        elif args.command == "doctor": out = codex_adapter.doctor(root)
        elif args.command == "stale": out = stale(root)
        elif args.command == "memory-status":
            data = stale(root); out = {"ok": data["ok"], "entries": len(data["entries"]), "not_fresh": data["not_fresh"]}
        elif args.command == "milestone-check": out = milestone_check(root)
        elif args.command == "catalog": out = catalog(root, args.path)
        elif args.command == "document-get": out = document_get(root, args.path)
        elif args.command == "task-start":
            receipt = args.bootstrap_receipt if args.bootstrap_receipt is not None else args.controller_bridge_sha256
            if args.bootstrap_receipt is not None and args.controller_bridge_sha256 is not None and args.bootstrap_receipt != args.controller_bridge_sha256:
                raise ValueError("conflicting bootstrap receipts")
            start_args = (root, args.goal, args.milestone, args.input, args.hook_attestation, receipt)
            out = codex_adapter.task_start(*start_args, authority_contract=args.authority_contract, session_id=args.session_id) if args.authority_contract else codex_adapter.task_start(*start_args)
        elif args.command == "task-abandon": out = codex_adapter.task_abandon(root, args.task_id, args.revision, args.state_sha256, args.lifecycle_sha256, args.reason, args.hook_attestation)
        elif args.command == "task-recover-authority": out = task_authority.recover(root, args.expected_authority_sha256, args.reason)
        elif args.command == "task-recover-state": out = codex_adapter.task_recover_state(root, args.expected_sha256, args.abandon_active, args.hook_attestation, args.controller_bridge_sha256)
        elif args.command == "task-dispose-dependency": out = lifecycle.task_dispose_dependency(root, args.handoff_id, args.base_revision, args.expected_lifecycle_sha256, args.reason, args.conflict_id)
        elif args.command == "task-associate": out = lifecycle.associate_task(root, str(core.selected_task(root)), lifecycle._identity_hash(args.session_id), args.expected_authority_sha256)
        elif args.command == "task-mode": out = task_authority.switch_mode(root, args.expected_authority_sha256, args.base_revision, args.mode, args.human_instruction)
        elif args.command == "task-update":
            with _inline_input(args.json, args.input) as source:
                out = task_update(root, codex_adapter.controller_actor(args.role), args.base_revision, source)
        elif args.command == "task-evidence-register":
            with _inline_input(args.json, args.input) as source:
                out = codex_adapter.task_evidence_register(root, args.role, args.base_revision, source, args.controller_session_id_hash)
        elif args.command == "task-judge":
            with _inline_input(args.json, args.input) as source:
                out = core.task_judge(root, codex_adapter.controller_actor(args.role), args.base_revision, source, compact_evidence=True)
        elif args.command == "task-observe": out = codex_adapter.task_observe(root, args.role, args.handoff_id, args.agent_id_hash, args.input, args.observation_json)
        elif args.command == "document-maintain": out = codex_adapter.document_maintain(root, args.role, args.base_revision, args.input, args.handoff_id)
        elif args.command == "identity-status": out = identity.identity_status(root, session_key=_identity_session_key(root, args))
        elif args.command == "identity-note":
            from thaliris import identity_basis
            actor = codex_adapter.controller_actor(args.role)
            if args.list:
                out = identity_basis.identity_note_list(root, include_retracted=args.include_retracted)
            else:
                with _inline_input(args.json, args.input) as source:
                    out = identity_basis.identity_note(root, actor, source)
        elif args.command == "identity-suggest":
            from thaliris import identity_basis
            actor = codex_adapter.controller_actor(args.role)
            out = identity_basis.identity_suggest(root, actor, args.scope, "on" if args.on else "off" if args.off else "clear", session_key=_identity_session_key(root, args))
        elif args.command == "identity-get": out = identity.identity_get(root, version=args.version, items=args.item, amendment=args.amendment, challenge=args.challenge)
        elif args.command == "identity-trace": out = identity.identity_trace(root, args.ref, args.direction, args.depth)
        elif args.command in project_identity.MUTATIONS: out = getattr(identity, args.command.replace("-", "_"))(root, codex_adapter.controller_actor(args.role), args.base_revision, args.input)
        elif args.command == "task-show": out = task_show(root)
        elif args.command == "task-status": out = _task_status(root, suppress_protocol_notice=args.suppress_protocol_notice, evidence_offset=args.evidence_offset, view=args.view, since_revision=args.since_revision)
        elif args.command == "task-get": out = task_get(root, args.id)
        elif args.command == "artifact-get": out = artifact_get(root, args.id)
        elif args.command == "task-artifact": out = task_artifact(root, args.base_revision, args.id, args.path, args.summary, producer=(codex_adapter.semantic_role(args.producer_role) if getattr(args, "producer_role", None) else None), registered_by=codex_adapter.controller_actor(args.role), evidence_refs=args.source_ref or None, supersedes=args.supersedes or None)
        elif args.command == "task-close": out = codex_adapter.task_close(root, args.base_revision)
        elif args.command == "task-promote": out = task_promote(root, codex_adapter.controller_actor(args.role), args.base_revision, args.input)
        elif args.command == "rollback": out = rollback(root, args.backup)
        elif args.command == "uninstall": out = codex_adapter.uninstall(root)
        else: out = {"ok": True, "version": __version__}
        if out.get("ok") and args.command in {"task-update", "task-artifact", "task-promote", "task-judge", *project_identity.MUTATIONS}:
            task_authority.checkpoint(root)
        if args.command == "task-close" and out.get("ok"):
            line = project_identity.offer(root, _identity_session_key(root, args))
            if line:
                out = {**out, "identity_offer": line}
        out = _controller_evidence_output(root, args, out)
        if args.command == "codex-bootstrap":
            out = codex_bootstrap.ordered_response(out)
            _write_utf8_line(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None,
                                        separators=None if args.pretty else (",", ":")))
        else:
            print(json.dumps(out, sort_keys=True, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":")))
        return 0 if out.get("ok", False) else 3
    except TaskStateSchemaIncompatible as exc:
        result = codex_adapter.task_state_schema_error(root, exc)
        if args is not None and args.command == "codex-bootstrap":
            result.update(codex_bootstrap.controller_guidance_fields(args.controller_guidance_sha256))
            result = codex_bootstrap.ordered_response(result)
            _write_utf8_line(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        else:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 3
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        if args is not None and args.command == "audit-hook":
            # Preserve Hook rejection without leaking payload-derived errors.
            diagnostics.failure("dispatch")
            print(json.dumps({"ok": False, "error": "HOOK_DISPATCH_FAILED"}, separators=(",", ":")))
            return 2
        result = error_envelope(exc)
        if args is not None and root is not None:
            result = _controller_evidence_output(root, args, result)
        if bootstrap_requested or (args is not None and args.command == "codex-bootstrap"):
            result["session_restart_required"] = False
        if args is not None and args.command == "codex-bootstrap":
            result["status"] = "BOOTSTRAP_UNAVAILABLE"
            result.update(codex_bootstrap.controller_guidance_fields(args.controller_guidance_sha256))
            result = codex_bootstrap.ordered_response(result)
            _write_utf8_line(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        else:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
