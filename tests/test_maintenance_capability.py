from __future__ import annotations

import copy
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from thaliris_codex import maintenance_capability as cap, lifecycle, release_manager as manager
from thaliris_codex import release_identity as identity, runtime_setup
from tests.test_release_lifecycle import bound


def test_runtime_root_discovery_does_not_allocate_a_leaf(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(runtime_setup, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)}))
    monkeypatch.setattr(runtime_setup, "_host_package_family", lambda: "OpenAI.Codex_123456789abcd")
    monkeypatch.setattr(runtime_setup.runtime_identity, "physical_directory", lambda _path: tmp_path)
    monkeypatch.setattr(runtime_setup, "_source", lambda *a: pytest.fail("root discovery needs no artifact source"))
    monkeypatch.setattr(runtime_setup.uuid, "uuid4", lambda: pytest.fail("root discovery must not allocate candidate"))
    root = runtime_setup.default_runtime_root()
    assert root == tmp_path / "Thaliris" / "runtimes"
    assert not root.exists()


@pytest.fixture
def operation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(cap, "directory", lambda: tmp_path / "observations")
    monkeypatch.setattr(cap, "installed_identity", lambda _home: "ABSENT")
    updater = {"python": str(tmp_path / "python.exe"), "console": str(tmp_path / "thaliris-release.exe"),
               "runtime_sha256": "c" * 64}
    monkeypatch.setattr(cap, "updater_identity", lambda _home: updater)
    # No task is needed to observe a maintenance operation. Fence tests below
    # exercise the real deny-only lookup independently.
    args = manager.argument_parser().parse_args(["update", "--home", str(home), "--project", str(tmp_path),
        "--cache", str(tmp_path / "cache"), "--manifest", str(tmp_path / "release.json"),
        "--manifest-sha256", "a" * 64, "--human-instruction", "Update the release I selected",
        "--current-user-intent"])
    payload = {"session_id": "session-one", "prompt": "Please update Thaliris"}
    cap.observe_prompt(home, payload, lifecycle.MANAGED_HOOK_ABI)
    request = cap.scope(args)
    return home, args, payload, request, updater


def issue(operation, **changes):
    home, _args, payload, request, updater = operation
    return cap.issue(home, {**payload, **changes}, request, updater, lifecycle.MANAGED_HOOK_ABI,
                     root=Path(request["project"]), task_id=None)


@pytest.mark.parametrize("action", sorted(cap.ACTIONS))
def test_operation_capability_single_use_and_actor_assurance_unknown(operation, action):
    home, args, payload, request, updater = operation
    args.action = action
    request = cap.scope(args)
    token = cap.issue(home, payload, request, updater, lifecycle.MANAGED_HOOK_ABI,
                      root=Path(request["project"]), task_id=None)
    admitted = cap.consume(token, cap.digest(payload["session_id"].encode()), request, updater)
    assert admitted["host_actor_assurance"] == "UNKNOWN"
    assert admitted["scope"]["action"] == action
    assert admitted["provenance"] == "MODEL_SELECTED_CURRENT_USER_INSTRUCTION"
    cap.check_dispatch(admitted, request)
    with pytest.raises(ValueError, match="replay"):
        cap.consume(token, admitted["session"], request, updater)


@pytest.mark.parametrize("restriction", [{"agent_id": "child"}, {"agent_type": "thaliris-implementer"},
    {"readonly": True}, {"fenced": True}, {"abandoned": True}, {"delegated": True}, {"parent_agent_id": "parent"},
    {"agentId": "child"}, {"agent_role": "reviewer"}, {"readonly": "UNKNOWN"}])
def test_known_restricted_actor_cannot_issue(operation, restriction):
    with pytest.raises(ValueError, match="ACTOR_DENIED"):
        issue(operation, **restriction)


@pytest.mark.parametrize("field,value", [("action", "repair"), ("home", "/another/home"),
    ("project", "/another/project"), ("cache", "/another/cache"), ("manifest_sha256", "b" * 64),
    ("manifest", "https://example.test/other"), ("refresh_model_catalog", True),
    ("instruction_sha256", "f" * 64), ("resume_sha256", "e" * 64), ("artifacts", "/other/wheels")])
def test_capability_binds_every_operation_scope(operation, field, value):
    _home, _args, payload, request, updater = operation
    token = issue(operation)
    with pytest.raises((OSError, ValueError)):
        cap.consume(token, cap.digest(payload["session_id"].encode()), {**request, field: value}, updater)


def test_session_updater_tampering_and_parallel_consume(operation):
    _home, _args, payload, request, updater = operation
    token = issue(operation)
    session = cap.digest(payload["session_id"].encode())
    with pytest.raises((OSError, ValueError)):
        cap.consume(token, "f" * 64, request, updater)
    with pytest.raises(ValueError):
        cap.consume(token, session, request, {**updater, "runtime_sha256": "d" * 64})
    def consume():
        try:
            cap.consume(token, session, request, updater)
            return True
        except (OSError, ValueError):
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: consume(), range(2))) == [False, True]


def test_repeated_prompt_epochs_do_not_deduplicate_or_saturate(operation):
    home, _args, payload, request, updater = operation
    old = issue(operation)
    for _ in range(20):
        cap.observe_prompt(home, payload, lifecycle.MANAGED_HOOK_ABI)
    session = cap.digest(payload["session_id"].encode())
    with pytest.raises(ValueError):
        cap.consume(old, session, request, updater)
    current = cap.consume(issue(operation), session, request, updater)
    assert current["prompt_epoch"] == 21
    assert "Please update" not in json.dumps(current)
    cap.observe_prompt(home, payload, lifecycle.MANAGED_HOOK_ABI)
    with pytest.raises(ValueError):
        cap.check_dispatch(current, request)


def test_failed_new_prompt_cannot_leave_previous_intent_usable(operation):
    home, _args, payload, _request, _updater = operation
    with pytest.raises(ValueError):
        cap.observe_prompt(home, {"session_id": payload["session_id"]}, lifecycle.MANAGED_HOOK_ABI)
    with pytest.raises(ValueError, match="latest"):
        issue(operation)
    cap.observe_prompt(home, payload, lifecycle.MANAGED_HOOK_ABI)
    assert issue(operation).startswith("m1.")


def test_resume_bytes_remain_bound_until_dispatch(operation):
    home, args, payload, _request, updater = operation
    args.resume = args.project / "original-contract.json"
    args.resume.write_text("original")
    request = cap.scope(args)
    token = cap.issue(home, payload, request, updater, lifecycle.MANAGED_HOOK_ABI,
                      root=args.project, task_id=None)
    admitted = cap.consume(token, cap.digest(payload["session_id"].encode()), request, updater)
    args.resume.write_text("replaced")
    with pytest.raises(ValueError, match="resume contract"):
        cap.check_dispatch(admitted, request)


def test_expired_missing_and_wrong_abi_evidence_cannot_issue(operation, monkeypatch):
    home, _args, payload, request, updater = operation
    now = cap.time.time_ns()
    monkeypatch.setattr(cap.time, "time_ns", lambda: now + cap.TTL_NS + 1)
    with pytest.raises(ValueError):
        issue(operation)
    with pytest.raises(ValueError):
        cap.issue(home, payload, request, updater, "old-abi", root=Path(request["project"]), task_id=None)
    with pytest.raises(ValueError):
        cap.issue(home, {"prompt": "request"}, request, updater, lifecycle.MANAGED_HOOK_ABI,
                  root=Path(request["project"]), task_id=None)


def test_real_fence_lookup_denies_changed_session_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "_session_fenced", lambda *_args: True)
    with pytest.raises(ValueError, match="fenced"):
        cap.check_fences(tmp_path, "a" * 64, None)


@pytest.mark.parametrize("status,denied", [("DONE", False), ("ABANDONED", True)])
def test_maintenance_observation_is_separate_from_task_admission(tmp_path, monkeypatch, status, denied):
    from thaliris_codex import task_authority
    monkeypatch.setattr(task_authority, "check", lambda root: {"status": status, "fenced_sessions": []})
    if denied:
        with pytest.raises(ValueError, match="abandoned"):
            cap.check_fences(tmp_path, "a" * 64, None)
    else:
        cap.check_fences(tmp_path, "a" * 64, None)


def test_retired_authority_cannot_hide_abandonment(tmp_path, monkeypatch):
    from thaliris_codex import task_authority
    monkeypatch.setattr(task_authority, "check", lambda root: None)
    monkeypatch.setattr(task_authority, "read", lambda root: {"status": "ABANDONED", "fenced_sessions": []})
    with pytest.raises(ValueError, match="abandoned"):
        cap.check_fences(tmp_path, "a" * 64, None)


def test_capability_state_is_guarded_control_state(operation):
    directory = str(cap.directory() / "forged.json")
    assert lifecycle._control_state_target({"tool_name": "exec_command", "tool_input": {
        "cmd": f'Set-Content "{directory}" forged', "shell": "powershell"}}) is not None


def hook_payload(operation):
    _home, args, _payload, _request, updater = operation
    return {"session_id": "session-one", "tool_name": "exec_command", "tool_input": {
        "cmd": f'& "{updater["python"]}" -I -B -m thaliris_codex.release_manager update '
        f'--home "{args.home}" --project "{args.project}" --cache "{args.cache}" '
        f'--manifest "{args.manifest}" --manifest-sha256 {args.manifest_sha256} '
        '--human-instruction "Update the release I selected" --current-user-intent', "shell": "powershell"}}


@pytest.mark.parametrize("route", ["direct", "selected"])
def test_hook_issues_for_current_model_selected_intent(operation, route):
    _home, args, _payload, _request, _updater = operation
    payload = hook_payload(operation)
    result = (lifecycle._pre_tool_output(payload, args.project, lifecycle.MANAGED_HOOK_ABI) if route == "direct" else
              lifecycle._handle_hook_selected(args.project, "PreToolUse", payload, lifecycle.MANAGED_HOOK_ABI))
    updated = json.loads(result)["hookSpecificOutput"]
    assert updated["permissionDecision"] == "allow"
    assert "--maintenance-capability m1." in updated["updatedInput"]["cmd"]


@pytest.mark.parametrize("defect", ["no-intent", "duplicate", "compound", "token", "relative", "foreign-home", "child", "readonly", "fenced", "abandoned"])
def test_hook_refuses_unscoped_or_restricted_maintenance(operation, defect):
    _home, args, _payload, _request, _updater = operation
    payload = hook_payload(operation)
    cmd = payload["tool_input"]["cmd"]
    if defect == "no-intent": cmd = cmd.replace(" --current-user-intent", "")
    elif defect == "duplicate": cmd += " --manifest other.json"
    elif defect == "compound": cmd = "git status; " + cmd
    elif defect == "token": cmd += " --maintenance-capability forged"
    elif defect == "relative": cmd = cmd.replace(str(args.project), "relative", 1)
    elif defect == "foreign-home": cmd = cmd.replace(str(args.home), str(args.home.parent / "other"))
    elif defect == "child": payload["agent_id"] = "child"
    else: payload[defect] = True
    payload["tool_input"]["cmd"] = cmd
    assert '"permissionDecision":"deny"' in lifecycle._pre_tool_output(payload, args.project, lifecycle.MANAGED_HOOK_ABI)


def test_cli_cannot_mint_permission_from_human_instruction(operation, monkeypatch, capsys):
    _home, args, _payload, _request, _updater = operation
    monkeypatch.setattr(manager.release_acquire, "download", lambda *a, **k: pytest.fail("no unauthorized network"))
    assert manager.main(["install", "--human-instruction", "I authorize everything"]) == 1
    assert "CAPABILITY_REQUIRED" in capsys.readouterr().out


def test_cli_status_needs_no_release_no_network_or_mutation(tmp_path, monkeypatch, capsys):
    cache, home = tmp_path / "absent-cache", tmp_path / "absent-home"
    monkeypatch.setattr(runtime_setup, "default_runtime_root", lambda: cache)
    monkeypatch.setattr(manager.release_acquire, "download", lambda *a, **k: pytest.fail("offline status"))
    monkeypatch.setattr(manager.release_acquire, "acquire", lambda *a, **k: pytest.fail("no wheels"))
    monkeypatch.setattr(runtime_setup, "create", lambda *a, **k: pytest.fail("no candidate"))
    from thaliris_codex import codex_adapter
    monkeypatch.setattr(codex_adapter, "bootstrap_check", lambda *a, **k: {"ok": True})
    assert manager.main(["status", "--home", str(home), "--project", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["available_release"] is None
    assert result["loaded_host"] == result["restart_required"] == "UNKNOWN"
    assert not cache.exists() and not home.exists()


def test_status_optional_release_adds_comparison_only(tmp_path, monkeypatch, capsys):
    binding = bound()
    path = tmp_path / "release.json"
    path.write_bytes(identity.canonical(binding["manifest"]))
    seen = []
    monkeypatch.setattr(manager, "status", lambda home, cache, release, project: seen.append(release) or
                        {"ok": True, "installed_disk": "ABSENT", "available_release": release, "loaded_host": "UNKNOWN"})
    common = ["status", "--cache", str(tmp_path / "cache")]
    assert manager.main(common) == 0
    local = json.loads(capsys.readouterr().out)
    assert manager.main(common + ["--manifest", str(path), "--manifest-sha256", binding["manifest_sha256"]]) == 0
    compared = json.loads(capsys.readouterr().out)
    assert seen == [None, binding]
    assert local["installed_disk"] == compared["installed_disk"]
    assert local["loaded_host"] == compared["loaded_host"] == "UNKNOWN"


def test_status_survives_unavailable_cache_discovery(tmp_path, monkeypatch, capsys):
    def unavailable():
        raise ValueError("native package/cache discovery unavailable")
    monkeypatch.setattr(runtime_setup, "default_runtime_root", unavailable)
    from thaliris_codex import codex_adapter
    monkeypatch.setattr(codex_adapter, "bootstrap_check", lambda *a, **k: {"ok": True})
    assert manager.main(["status", "--home", str(tmp_path / "home"), "--project", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["cache_inventory"] == "UNKNOWN"
    assert result["installed_disk"] == "ABSENT"
    assert result["loaded_host"] == "UNKNOWN"
    assert not (tmp_path / "home").exists()


def test_hook_capability_reaches_exact_contract_not_a_second_installer(operation, monkeypatch, capsys):
    home, args, payload, _request, updater = operation
    binding = bound()
    Path(args.manifest).write_bytes(identity.canonical(binding["manifest"]))
    args.manifest_sha256 = binding["manifest_sha256"]
    request = cap.scope(args)
    token = cap.issue(home, payload, request, updater, lifecycle.MANAGED_HOOK_ABI, root=args.project, task_id=None)
    selected = {"executable": str(args.project / "selected-thaliris"), "release_binding": binding,
                "source_pin": "sha256:" + "a" * 64}
    monkeypatch.setattr(manager, "find_saved_candidate", lambda *_args: selected)
    from thaliris_codex import host_maintenance
    calls = []
    def run(executable, arguments, **kwargs):
        calls.append(arguments)
        if arguments[0] == "codex-maintenance-plan":
            return {"ok": True, "maintenance_contract": {"operation": "codex-install", "codex_home": str(home),
                    "human_instruction": args.human_instruction, "installed_runtime_sha256": "ABSENT"}}
        return {"ok": True}
    monkeypatch.setattr(manager, "_run", run)
    checked = []
    monkeypatch.setattr(host_maintenance, "contract", lambda path, *a, **k: checked.append(json.loads(path.read_bytes())))
    assert manager.main(["update", "--manifest", args.manifest, "--manifest-sha256", args.manifest_sha256,
        "--home", str(home), "--cache", str(args.cache), "--project", str(args.project),
        "--human-instruction", args.human_instruction, "--current-user-intent", "--maintenance-capability", token,
        "--maintenance-session-hash", cap.digest(payload["session_id"].encode())]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["loaded_host"] == "UNKNOWN"
    assert checked[0]["executor"] == checked[0]["candidate"] == selected
    assert checked[0]["agent_maintenance_observation"]["scope"] == request
    assert [call[0] for call in calls] == ["codex-maintenance-plan", "codex-install"]


def test_cli_reuses_before_wheel_acquisition(operation, monkeypatch, capsys):
    home, args, _payload, _request, _updater = operation
    binding = bound()
    path = Path(args.manifest)
    path.write_bytes(identity.canonical(binding["manifest"]))
    args.manifest_sha256 = binding["manifest_sha256"]
    args.action = "prepare"
    selected = {"executable": "verified", "release_binding": binding}
    seen = []
    monkeypatch.setattr(manager, "find_saved_candidate", lambda cache, actual: seen.append(actual) or selected)
    monkeypatch.setattr(manager.release_acquire, "acquire", lambda *a, **k: pytest.fail("candidate hit must not download"))
    monkeypatch.setattr(runtime_setup, "create", lambda *a, **k: pytest.fail("candidate hit must not rebuild"))
    assert manager.main(["prepare", "--manifest", str(path), "--manifest-sha256", args.manifest_sha256,
        "--cache", str(args.cache), "--home", str(home)]) == 0
    assert seen == [binding]
    assert json.loads(capsys.readouterr().out)["selected"] == selected


def test_new_prompt_during_contract_validation_prevents_mutation(operation, monkeypatch):
    home, args, payload, request, updater = operation
    token = issue(operation)
    admission = cap.consume(token, cap.digest(payload["session_id"].encode()), request, updater)
    from thaliris_codex import host_maintenance
    calls = []
    def run(_exe, arguments, **_kwargs):
        calls.append(arguments[0])
        assert arguments[0] == "codex-maintenance-plan"
        return {"ok": True, "maintenance_contract": {"operation": "codex-install", "codex_home": str(home)}}
    monkeypatch.setattr(manager, "_run", run)
    monkeypatch.setattr(host_maintenance, "contract", lambda *a, **k:
                        cap.observe_prompt(home, payload, lifecycle.MANAGED_HOOK_ABI))
    outcome = manager.maintain("update", {"executable": "selected", "source_pin": "sha256:" + "a" * 64},
        home, args.project, args.cache, args.human_instruction, admission=admission)
    assert outcome["ok"] is False
    assert calls == ["codex-maintenance-plan"]
    assert Path(outcome["saved_contract"]).exists()


@pytest.mark.parametrize("failure", ["runtime", "preflight"])
def test_failed_candidate_validation_is_lazy_cache_miss(tmp_path, monkeypatch, failure):
    binding = bound()
    original = b'{"format":"interrupted candidate"}'
    (tmp_path / "candidate-interrupted.json").write_bytes(original)
    selected = {"executable": str(tmp_path / "runtime/thaliris"), "runtime_sha256": "c" * 64,
                "source_pin": "sha256:" + "a" * 64, "release_binding": binding}
    (tmp_path / "candidate-valid.json").write_bytes(identity.canonical({"format": manager.CANDIDATE_FORMAT, "selected": selected}))
    seen = []
    def validate(record, actual):
        seen.append(record)
        raise ValueError(failure + " mismatch")
    monkeypatch.setattr(manager, "validate_candidate", validate)
    assert manager.find_saved_candidate(tmp_path, binding) is None
    assert len(seen) == 2
    assert (tmp_path / "candidate-interrupted.json").read_bytes() == original


@pytest.mark.parametrize("failure", ["provenance", "preflight"])
def test_invalid_candidate_acquires_then_builds_without_modifying_original(tmp_path, monkeypatch, failure):
    from thaliris_codex import host_maintenance, host_preflight
    binding = bound()
    selected = {"executable": str(tmp_path / "old-runtime/thaliris"), "runtime_sha256": "c" * 64,
                "source_pin": "sha256:" + "a" * 64, "release_binding": binding}
    record_path = tmp_path / "candidate-original.json"
    original = identity.canonical({"format": manager.CANDIDATE_FORMAT, "selected": selected})
    record_path.write_bytes(original)
    events = []
    def verify(value):
        events.append("runtime")
        if failure == "provenance" and events == ["runtime"]:
            raise ValueError("Core archive provenance mismatch")
        return Path(value["executable"]), b"verified-runtime"
    def preflight(*_args):
        events.append("preflight")
        if failure == "preflight" and "acquire" not in events:
            raise ValueError("Host preflight unavailable")
    monkeypatch.setattr(host_maintenance, "selected_runtime", verify)
    monkeypatch.setattr(host_preflight, "verify_runtime", preflight)
    def acquire():
        events.append("acquire")
        return {"core": tmp_path / "core.whl", "adapter": tmp_path / "adapter.whl"}
    def create(directory, core, adapter):
        events.append("create")
        assert directory != tmp_path / "old-runtime"
        assert core.endswith("#sha256=" + "b" * 64)
        assert adapter.endswith("#sha256=" + "a" * 64)
        return {"executable": str(directory / "thaliris"), "runtime_sha256": "d" * 64}
    monkeypatch.setattr(runtime_setup, "create", create)
    result = manager.prepare(tmp_path, binding, acquire)
    assert result["executable"] != selected["executable"]
    assert events.index("runtime") < events.index("acquire") < events.index("create")
    assert events[-2:] == ["runtime", "preflight"]
    assert record_path.read_bytes() == original
