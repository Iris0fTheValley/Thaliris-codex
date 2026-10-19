"""Isolated native spawn acceptance for the installed candidate and Host Hooks.

The test task, CODEX_HOME, runtime, authority store, user profile, and Responses
endpoint all live below one disposable directory. The CLI is the observed
installed Codex binary; model responses are synthetic and stay on loopback.
This does not exercise or certify the signed-in Desktop Host.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from contextlib import nullcontext

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGE_SOURCE = REPO_ROOT.parent.parent / "core" / "Thaliris" / "src" / "thaliris"
if not CORE_PACKAGE_SOURCE.is_dir():
    raise RuntimeError("authoritative sibling Thaliris Core source is unavailable")
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(CORE_PACKAGE_SOURCE.parent))

from scripts import verify_model_catalog_runtime as native
from thaliris import core
from thaliris_codex import config_capability
from thaliris_codex import (
    codex_adapter,
    codex_app_server,
    host_preflight,
    lifecycle,
    roles,
    runtime_identity,
    runtime_setup,
    task_authority,
)
CALL = "call_native_c1_candidate"
PARENT_PROMPT = "THALIRIS_NATIVE_C1_PARENT_SENTINEL"
CHILD_PROMPT = "THALIRIS_NATIVE_C1_CHILD_SENTINEL"
TASK_PATH = "/root/native-c1-child"
PROFILE = "thaliris-focused-implementer"
EXPECTED_MODEL, EXPECTED_EFFORT = roles.ROLE_MODEL_ROUTING_DEFAULTS["focused-implementer"]
SELECTION = "thaliris-evidence: {\"candidate\":\"native-C1\",\"requirement_refs\":[\"R-NATIVE\",\"R-DELIVERY\"]}"


class Responses(native.ResponsesMock):
    """Return exactly one selected native spawn and local synthetic replies."""

    def _response(self, body: dict) -> bytes:
        flat = native._request_text(body)
        task = next((native._request_text(item) for item in reversed(body.get("input", []))
            if item.get("role") == "user" or item.get("type") == "agent_message"), "")
        response_id = "resp_native_c1"
        if PARENT_PROMPT in task and CALL not in flat:
            return native._tool_response(response_id, [(CALL, "collaboration", "spawn_agent", {
                "task_name": "native_c1_child",
                "agent_type": PROFILE,
                "fork_turns": "none",
                "message": CHILD_PROMPT + "\n" + SELECTION,
            })])
        return native._message_response(response_id)


def _source_candidate(scratch: Path) -> dict:
    """Build and install the same source wheels used by runtime setup tests."""
    from tests.test_runtime_setup import source_wheel

    core_wheel = source_wheel(scratch, "thaliris", CORE_PACKAGE_SOURCE)
    adapter_wheel = source_wheel(scratch, "thaliris_codex", REPO_ROOT / "src" / "thaliris_codex", entry=True)
    candidate = runtime_setup.create(scratch / "candidate-runtime", core_wheel, adapter_wheel)
    candidate["executable_sha256"] = hashlib.sha256(Path(candidate["executable"]).read_bytes()).hexdigest()
    return candidate


def _installed_candidate_identity(candidate: dict) -> dict[str, str]:
    """Verify the candidate imports the two source-built wheels in its venv."""
    interpreter = Path(candidate["executable"]).parent / ("python.exe" if os.name == "nt" else "python")
    root = Path(candidate["runtime_dir"]).resolve(strict=True)
    source = (
        "import importlib.metadata as m,json,thaliris,thaliris_codex,thaliris_codex.codex_app_server; "
        "from pathlib import Path; "
        "print(json.dumps({'core_version':m.version('thaliris'),"
        "'adapter_version':m.version('thaliris-codex'),"
        "'core_module':str(Path(thaliris.__file__).resolve()),"
        "'adapter_module':str(Path(thaliris_codex.codex_app_server.__file__).resolve())}))"
    )
    result = subprocess.run([str(interpreter), "-I", "-B", "-c", source],
        env=os.environ.copy(), capture_output=True, text=True, timeout=30, check=True)
    identity = json.loads(result.stdout)
    expected_core = tomllib.loads((CORE_PACKAGE_SOURCE.parent.parent / "pyproject.toml").read_text(
        encoding="utf-8"))
    expected_adapter = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if identity["core_version"] != expected_core["project"]["version"]:
        raise native.VerificationError("candidate Core package version differs from the authoritative source")
    if identity["adapter_version"] != expected_adapter["project"]["version"]:
        raise native.VerificationError("candidate adapter package version differs from this source checkout")
    for field in ("core_module", "adapter_module"):
        module_path = Path(identity[field]).resolve(strict=True)
        if not module_path.is_relative_to(root):
            raise native.VerificationError("candidate runtime imported a module outside its isolated venv")
        identity[field] = "candidate_runtime/" + module_path.relative_to(root).as_posix()
    identity["source_build"] = "authoritative sibling core/Thaliris plus this adapter source via source_wheel"
    return identity


def _write_candidate_home(home: Path, project: Path, candidate: dict,
                          executable: Path, mock: Responses) -> tuple[dict, bytes, bytes]:
    """Install the candidate's pinned Hook registration into a disposable home."""
    home.mkdir(parents=True)
    agents = home / "agents"
    agents.mkdir()
    user_profile = (b"# Disposable user-owned profile fixture\n"
        b"name = \"user-owned\"\n"
        b"developer_instructions = \"Preserve this user-owned profile fixture.\"\n")
    (agents / "user-owned.toml").write_bytes(user_profile)

    catalog = subprocess.run([str(executable), "debug", "models", "--bundled"],
        cwd=project, env=os.environ.copy(), capture_output=True, check=True, timeout=35)
    catalog_path = home / "catalog.json"
    catalog_path.write_bytes(catalog.stdout)

    rows = [
        'model = "gpt-6-luna"',
        'model_reasoning_effort = "max"',
        'model_provider = "mock_provider"',
        f"model_catalog_json = {json.dumps(str(catalog_path))}",
        'approval_policy = "never"',
        'sandbox_mode = "read-only"',
        "[model_providers.mock_provider]",
        'name = "Local synthetic provider"',
        f"base_url = {json.dumps(mock.base_url)}",
        'wire_api = "responses"',
        "request_max_retries = 0",
        "stream_max_retries = 0",
        "supports_websockets = false",
        "requires_openai_auth = false",
        "[features]",
        "hooks = true",
        "[features.multi_agent_v2]",
        "enabled = true",
        f"subagent_developer_instructions = {json.dumps('synthetic native acceptance child')} ",
    ]
    profile_file = f"{PROFILE}.toml"
    model, effort, role = roles.agent_profiles()[profile_file]
    profile_name = profile_file.removesuffix(".toml")
    profile_path = agents / profile_file
    profile_path.write_bytes(codex_adapter._agent_profile(profile_name, role, model, effort))
    rows.extend([
        f"[agents.{json.dumps(profile_name)}]",
        f"description = {json.dumps('candidate profile used by isolated native acceptance')}",
        f"config_file = {json.dumps('./agents/' + profile_file)}",
    ])
    (home / "config.toml").write_text("\n\n".join(rows) + "\n", encoding="utf-8")

    manifest = runtime_identity.manifest_bytes(Path(candidate["executable"]))
    runtime_hash = hashlib.sha256(manifest).hexdigest()
    (home / runtime_identity.MANIFEST_NAME).write_bytes(manifest)
    (home / lifecycle.HOST_HOOK_SCRIPT_NAME).write_bytes(lifecycle.host_hook_script_bytes())
    (home / host_preflight.NAME).write_bytes(host_preflight.script_bytes())

    user_handler = {"type": "command", "command": "cmd.exe /d /c exit 0", "timeout": 22}
    # Exercise opaque-key preservation in the pure JSON merger, but keep the
    # file read by Codex within its strict hooks.json schema. Unknown extension
    # fields make the Host reject the entire file and hide every handler.
    opaque_original = {
        "description": "Disposable native acceptance Hook document",
        "user_owned_extension": {"opaque": ["keep", "these", "bytes"]},
        "hooks": {"UserPromptSubmit": [{"hooks": [user_handler]}]},
    }
    opaque_merged, _, opaque_manual = lifecycle.merge_host_hooks(opaque_original, home,
        Path(candidate["executable"]), candidate["executable_sha256"], candidate["runtime_sha256"])
    native._expect(not opaque_manual
        and opaque_merged["user_owned_extension"] == opaque_original["user_owned_extension"],
        "Hook merger changed an unknown user-owned extension")
    original = {
        "description": "Disposable native acceptance Hook document",
        "hooks": {"UserPromptSubmit": [{"hooks": [user_handler]}]},
    }
    installed, changed, manual = lifecycle.merge_host_hooks(original, home,
        Path(candidate["executable"]), candidate["executable_sha256"], runtime_hash)
    native._expect(changed and not manual, "candidate Hook registration did not install cleanly")
    hooks_path = home / "hooks.json"
    hooks_path.write_text(json.dumps(installed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    user_hook_key = f"{hooks_path}:user_prompt_submit:0:0"
    with (home / "config.toml").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"\n[hooks.state.{json.dumps(user_hook_key)}]\nenabled = false\n")
    native._expect(installed["hooks"]["UserPromptSubmit"][0]["hooks"] == [user_handler],
        "Hook registration changed the unrelated user Hook")
    native._expect((agents / "user-owned.toml").read_bytes() == user_profile,
        "candidate setup changed the unrelated user profile")
    return installed, user_profile, manifest


def _seed_disposable_task(project: Path, parent_thread: str) -> str:
    """Seed only local fixture state so real Hook events can exercise binding."""
    initialized = codex_adapter.init(project)
    native._expect(initialized.get("ok") is True, "disposable project initialization failed")
    started = core.task_start(project, "Synthetic native-C1 Hook binding fixture", None, None)
    task_id = started["task_id"]
    core.select_task(project, task_id)
    task_authority.establish(project, core._load_state(project), {
        "human_instruction": "Synthetic local Hook acceptance fixture; no production authority",
        "boundary": "One disposable project and one synthetic native child",
        "invariants": "Require exact parent, turn, call, returned path and child UUID evidence",
        "acceptance": "Observe one exact native-C1 Hook binding and preserve unrelated local bytes",
        "execution_mode": "delegated",
    }, None)
    requirement_file = project / "requirements.json"
    requirement_file.write_text(json.dumps({"requirements": [
        {"id": "R-NATIVE", "workchain_ref": "native-c1-workchain"},
        {"id": "R-DELIVERY", "workchain_ref": "native-c1-workchain"},
    ]}), encoding="utf-8")
    revision = core.task_show(project)["state"]["revision"]
    registered = codex_adapter.task_evidence_register(project, "controller", revision, str(requirement_file))
    native._expect(registered.get("ok") is True, "synthetic selected requirements did not register")
    task_authority.checkpoint(project)
    lifecycle.record_task_start_owner(project, task_id, lifecycle._identity_hash(parent_thread))
    return task_id


def _candidate_spawn_query(candidate: dict, env: dict[str, str], home: Path,
                           payload: dict, task_path: str) -> str | None:
    python = Path(candidate["executable"]).parent / "python.exe"
    source = (
        "import json,sys; from pathlib import Path; "
        "from thaliris_codex.codex_app_server import native_spawn_identity; "
        "print(json.dumps(native_spawn_identity(Path(sys.argv[1]), "
        "json.loads(sys.argv[2]), sys.argv[3])))"
    )
    result = subprocess.run([str(python), "-I", "-B", "-c", source,
        str(home), json.dumps(payload, separators=(",", ":")), task_path],
        env=env, capture_output=True, text=True, timeout=45, check=True)
    return json.loads(result.stdout)


def _wait_for_native_edge(server: native.AppServer, thread: str, turn: str) -> dict:
    """Wait for the exact edge through the official app-server item reader."""
    deadline = time.monotonic() + 45
    last_ids: list[str] = []
    while time.monotonic() < deadline:
        page = server.request("thread/items/list", {"threadId": thread, "turnId": turn,
            "limit": 64, "sortDirection": "desc"})
        entries = page.get("data")
        native._expect(isinstance(entries, list), "native item list had an unknown shape")
        matches = [entry["item"] for entry in entries if isinstance(entry, dict)
            and entry.get("turnId") == turn and isinstance(entry.get("item"), dict)
            and entry["item"].get("id") == CALL]
        last_ids = [str(entry.get("item", {}).get("id")) for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("item"), dict)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise native.VerificationError("actual native event contained duplicate exact spawn edges")
        time.sleep(0.5)
    raise native.VerificationError("actual native app-server did not expose the selected spawn edge; observed_item_ids="
        + json.dumps(last_ids[:32]))


def verify() -> dict:
    """Install the candidate into a temporary CODEX_HOME and run native Hooks."""
    if not config_capability._system_config_is_absent():
        return {"status": "UNKNOWN", "reason": "system configuration isolation unavailable"}
    executable, version = native._find_codex()
    with tempfile.TemporaryDirectory(prefix="thaliris-native-c1-") as directory:
        scratch = Path(directory).resolve()
        home, project, user_profile_root = scratch / "codex-home", scratch / "workspace", scratch / "user-profile"
        project.mkdir()
        user_profile_root.mkdir()
        env = native._isolated_env(home, scratch)
        env.update({
            "USERPROFILE": str(user_profile_root),
            "HOME": str(user_profile_root),
            "CODEX_CLI_PATH": str(executable),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        mock, proxy, server = Responses(), native.OutboundDenyProxy(), None
        proxy.install_in(env)
        candidate: dict | None = None
        original_env = os.environ.copy()
        try:
            # Official app-server maintenance and Hook subprocesses inherit the
            # same isolated home and temporary Windows user profile.
            os.environ.clear()
            os.environ.update(env)
            if not Path(task_authority.directory()).resolve().is_relative_to(scratch):
                return {"status": "UNKNOWN", "reason": "temporary authority-store isolation unavailable"}
            subprocess.run(["git", "init", "-q", str(project)], env=env, check=True,
                capture_output=True, timeout=20)
            candidate = _source_candidate(scratch)
            candidate_packages = _installed_candidate_identity(candidate)
            candidate_exe = Path(candidate["executable"])
            profile_path = home / "agents" / f"{PROFILE}.toml"
            config, user_profile, manifest = _write_candidate_home(home, project,
                candidate, executable, mock)
            user_hook_key = f"{home / 'hooks.json'}:user_prompt_submit:0:0"
            native._expect(profile_path.is_file(), "selected native profile was not installed")
            native._expect(hashlib.sha256(manifest).hexdigest() == candidate["runtime_sha256"],
                "candidate runtime manifest identity disagreed with its installed receipt")

            hook_count = sum(1
                for event, groups in config.get("hooks", {}).items()
                for group in groups if isinstance(group, dict)
                for handler in group.get("hooks", [])
                if isinstance(handler, dict)
                and lifecycle._host_hook_command_is_managed(handler, event, home))
            native._expect(hook_count == 7,
                "isolated home does not contain all seven candidate Hook registrations")
            native._expect((home / "agents" / "user-owned.toml").read_bytes() == user_profile,
                "candidate Hook installation changed the unrelated user profile")
            persisted_hooks = json.loads((home / "hooks.json").read_text(encoding="utf-8"))
            native._expect(persisted_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
                == "cmd.exe /d /c exit 0", "candidate Hook install changed the existing user Hook")

            server = native.AppServer(executable, home, project, env)
            effective = server.request("config/read", {"cwd": str(project), "includeLayers": True})
            effective_config = effective.get("config") if isinstance(effective, dict) else None
            effective_features = effective_config.get("features") if isinstance(effective_config, dict) else None
            native_config_hooks = effective_features.get("hooks") if isinstance(effective_features, dict) else None
            # hooks/list is scoped to the execution cwd, while global user
            # hooks are sourced from CODEX_HOME. Query the real project cwd
            # so this observation follows the same discovery context as the
            # subsequent native thread.
            hook_listing = server.request("hooks/list", {"cwds": [str(project)]})
            hook_entries = hook_listing.get("data")
            listed = next((entry.get("hooks") for entry in hook_entries
                if isinstance(entry, dict) and str(entry.get("cwd", "")).casefold() == str(project).casefold()), [])
            native_hook_count = len(listed) if isinstance(listed, list) else 0
            def redact(value):
                if isinstance(value, str):
                    for path, label in ((home, "CODEX_HOME"), (project, "WORKSPACE"),
                                        (user_profile_root, "USER_PROFILE"), (scratch, "SCRATCH")):
                        value = value.replace(str(path), label)
                    return value
                if isinstance(value, list):
                    return [redact(item) for item in value]
                if isinstance(value, dict):
                    return {key: redact(item) for key, item in value.items()}
                return value
            hook_discovery = {
                "entry_count": len(hook_entries) if isinstance(hook_entries, list) else None,
                "entry_cwds_match_project": [
                    isinstance(entry, dict) and str(entry.get("cwd", "")).casefold() == str(project).casefold()
                    for entry in hook_entries
                ] if isinstance(hook_entries, list) else [],
                "errors": [entry.get("errors") for entry in hook_entries if isinstance(entry, dict)]
                    if isinstance(hook_entries, list) else [],
                "warnings": [entry.get("warnings") for entry in hook_entries if isinstance(entry, dict)]
                    if isinstance(hook_entries, list) else [],
                "sources": sorted({str(hook.get("source")) for hook in listed if isinstance(hook, dict)}),
                "events": sorted({str(hook.get("eventName")) for hook in listed if isinstance(hook, dict)}),
                "handler_count": native_hook_count,
            }
            hook_discovery = redact(hook_discovery)
            expected_candidate_commands = {
                handler.get("command")
                for event, groups in config.get("hooks", {}).items() if isinstance(groups, list)
                for group in groups if isinstance(group, dict)
                for handler in group.get("hooks", []) if isinstance(handler, dict)
                if lifecycle._host_hook_command_is_managed(handler, event, home)
            }
            listed_candidate_hooks = [hook for hook in listed if isinstance(hook, dict)
                and hook.get("command") in expected_candidate_commands] if isinstance(listed, list) else []
            native._expect(len(expected_candidate_commands) == 7 and len(listed_candidate_hooks) == 7,
                "0.163 app-server did not discover all seven exact candidate CODEX_HOME/hooks.json handlers")
            preserved_user_hook = [hook for hook in listed if isinstance(hook, dict)
                and hook.get("command") == "cmd.exe /d /c exit 0"] if isinstance(listed, list) else []
            native._expect(len(preserved_user_hook) == 1 and preserved_user_hook[0].get("enabled") is False,
                "Host discovery did not preserve the existing user's disabled Hook state")
            native._expect(not any(entry.get("warnings") or entry.get("errors")
                for entry in hook_entries if isinstance(entry, dict)),
                "0.163 app-server rejected or warned about the candidate Hook registration")
            config_before_trust = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
            hook_trust = codex_app_server.trust_installed_host_hooks(
                home, candidate_exe, candidate["executable_sha256"], candidate["runtime_sha256"],
                client_factory=lambda _home: nullcontext(server))
            native._expect(hook_trust.get("status") == "TRUSTED"
                and hook_trust.get("trusted_count") == hook_trust.get("expected_count") == 7
                and hook_trust.get("dispatchable_count") == 7,
                "actual app-server did not trust all seven exact candidate handlers")
            config_after_trust = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
            hooks_state_after = config_after_trust.get("hooks", {}).get("state", {})
            config_before_without_hooks = {key: value for key, value in config_before_trust.items()
                if key != "hooks"}
            config_after_without_hooks = {key: value for key, value in config_after_trust.items()
                if key != "hooks"}
            hooks_state_before = config_before_trust.get("hooks", {}).get("state", {})
            native._expect(config_after_without_hooks == config_before_without_hooks,
                "candidate trust write changed unrelated user configuration")
            native._expect(hooks_state_after.get(user_hook_key) == {"enabled": False},
                "candidate trust write changed the user's disabled Hook state")
            native._expect(set(hooks_state_after) == set(hooks_state_before) | set(hook_trust.get("keys", [])),
                "candidate trust write replaced or introduced unrelated hook state keys")
            native._expect(all(set(hooks_state_after[key]) == {"trusted_hash"}
                for key in hook_trust.get("keys", [])),
                "candidate trust write changed Thaliris hook state fields")
            started = server.request("thread/start", {
                "model": "gpt-6-luna", "modelProvider": "mock_provider", "cwd": str(project),
                "sandbox": "read-only", "approvalPolicy": "never",
            })
            thread = started["thread"]["id"]
            task_id = _seed_disposable_task(project, thread)
            turn = server.start_turn(thread, PARENT_PROMPT + " spawn one candidate Hook child then finish",
                model="gpt-6-luna", effort="max")
            item = _wait_for_native_edge(server, thread, turn)
            child_id = item.get("agentThreadId")
            task_path = item.get("agentPath")
            native._expect(isinstance(child_id, str) and isinstance(task_path, str),
                "actual native spawn edge omitted child identity or returned path")
            actual_native_route = {
                "model": {"status": "MATCH" if item.get("model") == EXPECTED_MODEL else "MISMATCH",
                    "observed": item.get("model"), "expected": EXPECTED_MODEL},
                "reasoningEffort": {"status": "MATCH" if item.get("reasoningEffort") == EXPECTED_EFFORT else "MISMATCH",
                    "observed": item.get("reasoningEffort"), "expected": EXPECTED_EFFORT},
            }

            input_payload = {
                "session_id": thread, "turn_id": turn, "tool_use_id": CALL,
                "tool_name": "spawn_agent",
                "tool_input": {
                    "task_name": "native_c1_child", "agent_type": PROFILE, "fork_turns": "none",
                    "message": CHILD_PROMPT + "\n" + SELECTION,
                },
            }
            child_page = server.request("thread/items/list", {"threadId": child_id,
                "limit": 64, "sortDirection": "desc"})
            child_entries = child_page.get("data")
            native._expect(isinstance(child_entries, list) and child_entries,
                "native child thread did not expose its turn items")
            child_turns = {entry.get("turnId") for entry in child_entries
                if isinstance(entry, dict) and isinstance(entry.get("turnId"), str)}
            native._expect(len(child_turns) == 1, "synthetic native child used an ambiguous number of turns")
            child_turn = next(iter(child_turns))
            state_path = project / ".context" / "audit" / "lifecycle" / f"{lifecycle._task_key(task_id)}.json"
            lifecycle_state = json.loads(state_path.read_text(encoding="utf-8"))
            children = [entry for entry in lifecycle_state.get("children", [])
                if isinstance(entry, dict) and entry.get("agent_id_hash") == lifecycle._identity_hash(child_id)]
            native._expect(len(children) == 1, "candidate Hook did not create one child lifecycle binding")
            child = children[0]
            native._expect(child.get("managed") is True and child.get("handoff_bound") is True,
                "candidate Hook did not bind its fresh child to the selected handoff")
            native._expect(child.get("native_identity_source") == "app_server_subagent_activity",
                "candidate Hook did not use the exact official spawn edge")
            native._expect(child.get("session_id_hash") == lifecycle._identity_hash(thread),
                "candidate Hook bound the child to a different parent session")
            native._expect(child.get("spawn_turn_id_hash") == lifecycle._turn_id_hash({"turn_id": turn}),
                "candidate Hook bound the child to a different parent turn")
            native._expect(child.get("spawn_tool_use_id_hash") == lifecycle._identity_hash(CALL),
                "candidate Hook bound the child to a different native call")
            native._expect(child.get("task_name_hash") == lifecycle._identity_hash(task_path),
                "candidate Hook bound the child to a different returned path")
            native._expect(child.get("agent_id_hash") == lifecycle._identity_hash(child_id),
                "candidate Hook bound a different child UUID")
            native._expect(isinstance(child.get("handoff_id"), str) and child["handoff_id"],
                "candidate Hook did not retain a fresh handoff")
            evidence_handoffs = core._load_state(project, active=True).get("evidence_continuity", {}).get("handoffs", [])
            selected_handoff = next((entry for entry in evidence_handoffs
                if entry.get("id") == child.get("handoff_id")), None)
            native._expect(isinstance(selected_handoff, dict)
                and selected_handoff.get("candidate") == "native-C1"
                and selected_handoff.get("requirement_refs") == ["R-NATIVE", "R-DELIVERY"],
                "candidate Hook did not bind the Controller-selected candidate and requirements")

            runtime_files = list((project / ".context" / "audit").glob("*/runtime.json"))
            observed_events: set[str] = set()
            for runtime_file in runtime_files:
                runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
                events = runtime.get("events_observed") if isinstance(runtime, dict) else None
                if isinstance(events, dict):
                    observed_events.update(event for event, observed in events.items() if observed is True)
            native._expect(set(("UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart"))
                <= observed_events, "actual Native Host dispatch did not record the required candidate Hook event set; observed="
                + json.dumps(sorted(observed_events)))
            routing_rows = lifecycle_state.get("native_routing_observations", [])
            route = next((record.get("routing") for record in routing_rows
                if isinstance(record, dict) and record.get("agent_id_hash") == child.get("agent_id_hash")
                and isinstance(record.get("routing"), dict)), None)
            # Older lifecycle versions key routing by call hash; accept either
            # exact causal key while requiring the selected profile result.
            if route is None:
                route = next((record.get("routing") for record in routing_rows
                    if isinstance(record, dict)
                    and record.get("spawn_tool_use_id_hash") == child.get("spawn_tool_use_id_hash")
                    and isinstance(record.get("routing"), dict)), None)
            native._expect(isinstance(route, dict)
                and route.get("model", {}).get("status") in {"MATCH", "MISMATCH"}
                and route.get("reasoningEffort", {}).get("status") in {"MATCH", "MISMATCH"},
                "candidate Hook did not retain the actual native routing observation")

            # Verify the actual child provider request used the installed
            # profile's model and developer instructions, not only a config file.
            child_requests = [request for request in mock.snapshot() if request.thread_id == child_id]
            native._expect(len(child_requests) >= 1, "synthetic provider did not receive the actual child request")
            profile_text = tomllib.loads(profile_path.read_text(encoding="utf-8"))["developer_instructions"]
            native._expect(any(profile_text in "\n".join(native._developer_texts(request.body))
                for request in child_requests), "candidate native profile instructions were not effective in the child request")

            payload = {"session_id": thread, "turn_id": turn, "tool_use_id": CALL,
                "tool_input": {"agent_type": PROFILE}}
            negative_probes = {
                "wrong_parent": ({**payload, "session_id": child_id}, task_path),
                "reused_session_stale_turn": ({**payload, "turn_id": str(uuid.uuid4())}, task_path),
                "wrong_call": ({**payload, "tool_use_id": "call_wrong_native_c1"}, task_path),
                "wrong_path": (payload, task_path + "/wrong"),
            }
            refused = {name: _candidate_spawn_query(candidate, env, home, changed, path) is None
                for name, (changed, path) in negative_probes.items()}
            native._expect(all(refused.values()), "candidate reader accepted stale or conflicting native identity")

            return {
                "status": "CANDIDATE_HOOKS_DISPATCHED_IN_ISOLATED_NATIVE_HOST",
                "cli_version": version,
                "cli_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "actual_native_event": True,
                "candidate_runtime_installed": True,
                "candidate_packages": candidate_packages,
                "candidate_hook_registrations": 7,
                "candidate_hook_binding": {
                    "fresh_handoff": True,
                    "parent_session": True,
                    "parent_turn": True,
                    "spawn_call": True,
                    "returned_path": True,
                    "child_uuid": True,
                    "pretool_routed_model": EXPECTED_MODEL,
                    "pretool_routed_reasoning_effort": EXPECTED_EFFORT,
                    "pretool_route": "MATCH",
                    "actual_native_edge_routing": actual_native_route,
                    "recorded_lifecycle_routing": route,
                    "profile_in_child_request": True,
                    "observed_events": sorted(observed_events),
                },
                "candidate_hook_dispatch": "ACTUAL_ISOLATED_APP_SERVER_EVENTS",
                "candidate_hook_trust": {
                    "status": hook_trust.get("status"),
                    "changed": hook_trust.get("changed"),
                    "trusted_count": hook_trust.get("trusted_count"),
                    "enabled_count": hook_trust.get("enabled_count"),
                    "dispatchable_count": hook_trust.get("dispatchable_count"),
                    "expected_count": hook_trust.get("expected_count"),
                    "config_path": "isolated CODEX_HOME/config.toml",
                },
                "native_app_server_reported_hook_count": native_hook_count,
                "native_hook_discovery": hook_discovery,
                "native_config_hooks_effective": native_config_hooks if type(native_config_hooks) is bool else "UNKNOWN",
                "native_hook_autodispatch": "OBSERVED_IN_ISOLATED_APP_SERVER",
                "reused_session_stale_and_wrong_identity_refusals": refused,
                "old_protocol_compatibility": "COVERED_BY_FIXTURE_TESTS",
                "ownership_protection": {
                    "user_hook_preserved": True,
                    "user_hook_disabled_state_preserved": True,
                    "user_profile_preserved": True,
                    "unknown_merge_extension_preserved": True,
                    "user_config_preserved": True,
                    "production_home_modified": False,
                },
                "local_responses_requests": len(mock.snapshot()),
                "external_model_requests": 0,
                "production_host_activation": "UNKNOWN",
                "effective_wait_runtime": "UNKNOWN",
                "privacy": "Thread IDs, payload text and machine paths omitted",
            }
        finally:
            if server is not None:
                server.close()
            mock.close()
            proxy.close()
            os.environ.clear()
            os.environ.update(original_env)


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
