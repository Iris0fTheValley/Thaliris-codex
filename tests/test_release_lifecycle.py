from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess

import pytest

from thaliris_codex import release_acquire, release_identity as identity, release_manager as manager
from thaliris_codex import host_maintenance, host_preflight, host_transition, lifecycle, runtime_identity


def manifest():
    artifacts = {}
    for name, distribution in (("adapter", "thaliris_codex"), ("core", "thaliris")):
        filename = distribution + "-0.4.6-py3-none-any.whl"
        artifacts[name] = {"filename": filename, "sha256": ("a" if name == "adapter" else "b") * 64,
            "url": f"https://github.com/{identity.REPOSITORY}/releases/download/v0.4.6/{filename}"}
    return {"format": identity.FORMAT, "repository": identity.REPOSITORY, "release": "v0.4.6",
        "adapter_commit": "1" * 40, "core_commit": "2" * 40,
        "compatibility": identity.COMPATIBILITY, "artifacts": artifacts}


def bound(value=None):
    raw = identity.canonical(value or manifest())
    return identity.binding(raw, identity.sha256(raw))


def test_release_compatibility_matches_actual_supported_protocols():
    from thaliris import core
    assert identity.COMPATIBILITY["adapter_protocol"] == lifecycle.CODEX_ADAPTER_PROTOCOL_VERSION
    assert identity.COMPATIBILITY["managed_hook_abi"] == lifecycle.MANAGED_HOOK_ABI
    assert identity.COMPATIBILITY["runtime"] == runtime_identity.MANIFEST_FORMAT
    assert identity.COMPATIBILITY["maintenance"] == host_maintenance.FORMAT
    assert identity.COMPATIBILITY["core_state_schema"] == core._STATE_SCHEMA_VERSION


@pytest.mark.parametrize("defect", ["adapter_commit", "core_commit", "compatibility", "repository", "core", "url"])
def test_release_identity_rejects_incomplete_or_incompatible_binding(defect):
    value = copy.deepcopy(manifest())
    if defect in {"adapter_commit", "core_commit"}:
        value[defect] = "0.4.6"
    elif defect == "compatibility":
        value[defect] = {"python": ">=3.11"}
    elif defect == "repository":
        value[defect] = "attacker/repo"
    elif defect == "core":
        del value["artifacts"]["core"]
    else:
        value["artifacts"]["core"]["url"] = "https://example.test/other.whl"
    with pytest.raises(ValueError):
        identity.validate(value)


def test_manifest_cannot_self_authorize_or_be_reencoded():
    raw = identity.canonical(manifest())
    with pytest.raises(ValueError, match="externally selected"):
        identity.load(raw, "0" * 64)
    pretty = json.dumps(manifest(), indent=2).encode()
    with pytest.raises(ValueError, match="canonical"):
        identity.binding(pretty, identity.sha256(pretty))


def test_selected_release_checks_both_installed_archive_hashes(tmp_path):
    value = bound()
    package = tmp_path / "thaliris_codex"
    package.mkdir()
    for name, distribution in (("adapter", "thaliris_codex"), ("core", "thaliris")):
        metadata = tmp_path / (distribution + "-0.4.6.dist-info")
        metadata.mkdir()
        (metadata / "direct_url.json").write_text(json.dumps({"archive_info": {"hashes": {
            "sha256": value["manifest"]["artifacts"][name]["sha256"]}}}))
    selected = {"source_pin": "sha256:" + "a" * 64, "release_binding": value}
    identity.validate_selected(selected, {"package_dir": str(package)})
    # Adapter equality and identical package versions do not establish pairing.
    core_provenance = tmp_path / "thaliris-0.4.6.dist-info/direct_url.json"
    core_provenance.write_text(json.dumps({"archive_info": {"hashes": {"sha256": "c" * 64}}}))
    with pytest.raises(ValueError, match="core archive"):
        identity.validate_selected(selected, {"package_dir": str(package)})


def test_acquire_verifies_artifacts_and_preserves_failed_attempt(tmp_path, monkeypatch):
    raw = identity.canonical(manifest())
    selected = tmp_path / "release.json"
    selected.write_bytes(raw)
    monkeypatch.setattr(release_acquire, "download", lambda *_args, **_kw: b"bad wheel")
    attempt = tmp_path / "attempt"
    with pytest.raises(ValueError, match="artifact SHA-256"):
        release_acquire.acquire(str(selected), identity.sha256(raw), attempt)
    assert (attempt / "release.json").read_bytes() == raw
    with pytest.raises(FileExistsError):
        release_acquire.acquire(str(selected), identity.sha256(raw), attempt)


def test_reuse_revalidates_runtime_and_preflight_without_constructing(tmp_path, monkeypatch):
    binding = bound()
    selected = {"executable": str(tmp_path / "runtime/bin/thaliris"), "runtime_sha256": "c" * 64,
        "source_pin": "sha256:" + "a" * 64, "release_binding": binding}
    record = {"format": manager.CANDIDATE_FORMAT, "selected": selected}
    (tmp_path / "candidate-test.json").write_bytes(identity.canonical(record))
    seen = []
    monkeypatch.setattr(host_maintenance, "selected_runtime", lambda value: seen.append(value) or (Path(value["executable"]), b"runtime"))
    monkeypatch.setattr(host_preflight, "verify_runtime", lambda *args: seen.append(args))
    monkeypatch.setattr(manager.runtime_setup, "create", lambda *args: pytest.fail("must reuse"))
    assert manager.prepare(tmp_path, binding, {}) == selected
    assert seen == [selected, (Path(selected["executable"]), b"runtime")]


@pytest.mark.parametrize("actor", [{"agent_id": "child"}, {"agent_type": "thaliris-implementer"},
    {"readonly": True}, {"fenced": True}, {"abandoned": True}])
def test_known_denied_actor_cannot_start_high_level_maintenance(tmp_path, actor, monkeypatch):
    monkeypatch.setattr(manager, "_run", lambda *a, **k: pytest.fail("denied before subprocess"))
    with pytest.raises(ValueError, match="ACTOR_DENIED"):
        manager.maintain("install", {}, tmp_path / "home", tmp_path, tmp_path, "Install selected release", actor=actor)


def test_plan_keeps_actual_instruction_and_complete_binding(tmp_path, monkeypatch):
    instruction = "Please update this temporary Host to the exact release I selected."
    selected = {"executable": "/selected/thaliris", "runtime_sha256": "c" * 64,
                "source_pin": "sha256:" + "a" * 64, "release_binding": bound()}
    home = tmp_path / "home"
    calls = []
    def run(exe, args, **kwargs):
        calls.append((exe, args, kwargs))
        if args[0] == "codex-maintenance-plan":
            assert args[args.index("--human-instruction") + 1] == instruction
            return {"ok": True, "maintenance_contract": {"format": host_maintenance.FORMAT,
                "operation": "codex-install", "codex_home": str(home), "human_instruction": instruction,
                "installed_runtime_sha256": "ABSENT", "legacy_owned_bytes": {}}}
        return {"ok": True}
    monkeypatch.setattr(manager, "_run", run)
    monkeypatch.setattr(host_maintenance, "contract", lambda path, *a, **k: json.loads(path.read_bytes()))
    out = manager.maintain("update", selected, home, tmp_path, tmp_path, instruction, refresh_model_catalog=True)
    plan = json.loads(Path(out["saved_contract"]).read_bytes())
    assert plan["human_instruction"] == instruction
    assert plan["executor"] == plan["candidate"] == selected
    assert plan["legacy_owned_bytes"] == {}
    assert plan["refresh_model_catalog"] is True
    assert len(calls) == 2 and all(item[0] == selected["executable"] for item in calls)


def test_pending_requires_original_contract_and_resume_replays_exact_bytes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / host_transition.NAME).write_text("pending")
    with pytest.raises(ValueError, match="HOST_TRANSITION_PENDING"):
        manager.maintain("repair", {}, home, tmp_path, tmp_path, "Repair selected release")
    contract = tmp_path / "original.json"
    selected = {"executable": "/original/thaliris"}
    contract.write_bytes(identity.canonical({"operation": "codex-install", "codex_home": str(home),
        "executor": selected, "human_instruction": "Original actual request", "installed_runtime_sha256": "b" * 64}))
    before = contract.read_bytes()
    monkeypatch.setattr(host_maintenance, "contract", lambda *a, **k: {})
    seen = []
    monkeypatch.setattr(manager, "_run", lambda exe, args, **k: seen.append((exe, args)) or {"ok": True})
    manager.maintain("repair", {}, home, tmp_path, tmp_path, "Retry the original request", resume=contract)
    assert contract.read_bytes() == before
    assert seen == [(selected["executable"], ["codex-install", "--maintenance-contract", str(contract)])]


def test_interrupted_execution_reports_exact_saved_recovery_contract(tmp_path, monkeypatch):
    home = tmp_path / "home"
    selected = {"executable": "/selected/thaliris", "release_binding": bound()}
    contract = tmp_path / "original.json"
    contract.write_bytes(identity.canonical({"operation": "codex-install", "codex_home": str(home),
        "executor": selected, "human_instruction": "Actual original request"}))
    before = contract.read_bytes()
    monkeypatch.setattr(host_maintenance, "contract", lambda *a, **k: {})
    def interrupted(*args, **kwargs):
        raise subprocess.TimeoutExpired([selected["executable"]], 180)
    monkeypatch.setattr(manager, "_run", interrupted)
    out = manager.maintain("repair", {}, home, tmp_path, tmp_path, "Retry actual request", resume=contract)
    assert not out["ok"] and out["saved_contract"] == str(contract)
    assert contract.read_bytes() == before


def test_status_keeps_project_and_pending_facts_when_installed_bytes_are_corrupt(tmp_path, monkeypatch):
    from thaliris_codex import codex_adapter
    home = tmp_path / "home"
    home.mkdir()
    (home / runtime_identity.MANIFEST_NAME).write_bytes(b"corrupt user-owned evidence")
    intent = identity.canonical({"codex_home": str(home), "operation": "codex-install"})
    plan = tmp_path / "maintenance-original.json"
    plan.write_bytes(intent)
    (home / host_transition.NAME).write_bytes(identity.canonical({"format": host_transition.FORMAT,
        "phase": "COMMITTED", "operation": "codex-install", "contract_sha256": identity.sha256(intent)}))
    monkeypatch.setattr(codex_adapter, "bootstrap_check", lambda project, **_kwargs: {"definition_recovery_status": "INIT_REQUIRED"})
    before = {p: p.read_bytes() for p in home.iterdir()}
    out = manager.status(home, tmp_path, bound(), tmp_path)
    assert not out["ok"] and out["installed_disk"] == "UNVERIFIED"
    assert out["loaded_host"] == out["restart_required"] == "UNKNOWN"
    assert out["project_host_relation"] == "UNKNOWN"
    assert out["project_definition"]["definition_recovery_status"] == "INIT_REQUIRED"
    assert out["saved_maintenance_plans"][0]["matches_pending"] is True
    assert {p: p.read_bytes() for p in home.iterdir()} == before


@pytest.mark.parametrize("command", [
    "thaliris-release install --manifest release.json --manifest-sha256 abc",
    "thaliris-release --manifest release.json update --manifest-sha256 abc",
    "python -I -B -m thaliris_codex.release_manager repair --manifest release.json",
    "python -IB -m thaliris_codex.release_manager install --manifest release.json",
    "python -X utf8 -W ignore -IB -m thaliris_codex.release_manager repair --manifest release.json",
    "python -IBXutf8Wignore -m thaliris_codex.release_manager update --manifest release.json",
    "python -IBm thaliris_codex.release_manager uninstall --manifest release.json",
    "pythonw.exe -IB -m thaliris_codex.release_manager install --manifest release.json",
    "pythonw3.11.exe -Xutf8 -IB -m thaliris_codex.release_manager repair --manifest release.json",
    "py -3.11 -Wignore -Xutf8 -IB 'some dir/thaliris-bootstrap.py' install --manifest release.json",
    "pyw.exe -3.11 -IB 'some dir/thaliris-bootstrap.py' update --manifest release.json",
    "python -- thaliris-bootstrap.py repair --manifest release.json",
    "py -3.11 -I -B 'some dir/thaliris-bootstrap.py' uninstall --manifest release.json",
    "& 'C:/runtime/Scripts/thaliris-release.exe' install --human-instruction 'Install it'",
    "git status; python thaliris-bootstrap.py install --manifest selected.json",
    "Write-Output $(thaliris-release update --manifest selected.json)",
    'git status > "$(python -m thaliris_codex.release_manager repair)"',
    "thaliris-release install --help; thaliris-release install --manifest selected.json",
])
def test_release_maintenance_shell_forms_are_denied_for_automation(tmp_path, command):
    payload = {"tool_name": "exec_command", "agent_id": "child", "agent_type": "thaliris-implementer",
               "tool_input": {"cmd": command, "shell": "powershell"}}
    assert lifecycle._release_maintenance_attempt(payload)
    assert "THALIRIS_RELEASE_MAINTENANCE_CAPABILITY_REQUIRED" in lifecycle._pre_tool_output(payload, tmp_path)


@pytest.mark.parametrize("command", [
    "thaliris-release status --manifest selected.json",
    "python -m thaliris_codex.release_manager prepare --manifest selected.json",
    "python -W -m thaliris_codex.release_manager repair --manifest selected.json",
    "python -X 'value -m thaliris_codex.release_manager install' -c 'print(1)'",
    "python -c \"print('-m thaliris_codex.release_manager repair')\"",
    "py -3.11 thaliris-bootstrap.py install --help",
    "Write-Output 'thaliris-release install'",
    "git status # python thaliris-bootstrap.py install",
    'Write-Output "`$(thaliris-release install)"',
])
def test_release_readonly_help_and_shell_literals_do_not_create_mutation(command):
    assert not lifecycle._release_maintenance_attempt({"tool_name": "exec_command",
        "tool_input": {"cmd": command, "shell": "powershell"}})


@pytest.mark.parametrize("command", [
    "pythonw.exe -IB -m thaliris_codex.release_manager install",
    "pyw.exe -3.11 -IB 'some dir/thaliris-bootstrap.py' uninstall",
])
@pytest.mark.parametrize("actor", [
    {"agent_id": "child", "agent_type": "thaliris-implementer"},
    {"agent_type": "thaliris-controller"},
    {"readonly": True},
    {"fenced": True},
])
def test_release_maintenance_is_denied_on_each_automation_hook_route(tmp_path, actor, command):
    payload = {"tool_name": "exec_command", **actor,
        "tool_input": {"cmd": command, "shell": "powershell"}}
    output = lifecycle._handle_hook_selected(tmp_path, "PreToolUse", payload)
    assert '"permissionDecision":"deny"' in output


def test_low_level_exact_contract_is_outside_release_cli_denial():
    payload = {"tool_name": "exec_command", "tool_input": {
        "cmd": "thaliris codex-install --maintenance-contract approved.json", "shell": "powershell"}}
    assert not lifecycle._release_maintenance_attempt(payload)


def test_historical_ownership_reader_rejects_release_receipt_schema():
    import types

    old_source = subprocess.check_output(["git", "show",
        "f593539dec7ad33b5808d3a1bfab9627ae23f7e1:src/thaliris_codex/host_maintenance.py"])
    historical = types.ModuleType("thaliris_codex.historical_maintenance")
    historical.__package__ = "thaliris_codex"
    exec(compile(old_source, "historical-host-maintenance.py", "exec"), historical.__dict__)
    installed = b"historically installed runtime"
    legacy = {"format": host_maintenance.RECEIPT_FORMAT, "runtime_sha256": host_maintenance.digest(installed),
        "maintenance_contract_sha256": "a" * 64, "human_instruction": "selected maintenance",
        "owned_bytes": {}, "hook_handlers": {}, "source_pin": "sha256:" + "b" * 64,
        "release_binding": {"format": "future release"}}
    assert historical.validate_ownership(identity.canonical(legacy), installed, {})["release_binding"] == {
        "format": "future release"}
    release_receipt = {**legacy, "format": host_maintenance.RELEASE_RECEIPT_FORMAT,
        "required_capabilities": [host_maintenance.RELEASE_CAPABILITY]}
    with pytest.raises(ValueError, match="ownership record"):
        historical.validate_ownership(identity.canonical(release_receipt), installed, {})


def test_release_receipt_schema_is_strict_and_keeps_existing_config_capabilities(tmp_path, monkeypatch, pinned_test_thaliris):
    from thaliris_codex import catalog_recovery, mode_hint_config, model_catalog_config as catalog
    from thaliris_codex import wait_guidance_config

    executable, _ = pinned_test_thaliris
    home = tmp_path / "home"
    installed = runtime_identity.manifest_bytes(executable)
    binding = bound()
    monkeypatch.setattr(identity, "validate_selected", lambda selected, runtime: None)
    catalog_record = {"path": str(home / "config.toml"), "catalog_path": str(home / catalog.NAME),
        "prior": {"present": False}, "fragment": catalog.fragment(home, "\n"),
        "catalog_sha256": "c" * 64,
        "source": {"kind": "bundled", "cli_version": "codex-cli 0.162.0", "upstream_sha256": "d" * 64}}
    receipt = {"format": host_maintenance.RELEASE_RECEIPT_FORMAT,
        "runtime_sha256": host_maintenance.digest(installed),
        "maintenance_contract_sha256": "e" * 64, "human_instruction": "selected maintenance",
        "source_pin": "sha256:" + "a" * 64, "release_binding": binding,
        "required_capabilities": [host_maintenance.RELEASE_CAPABILITY, host_maintenance.CATALOG_CAPABILITY],
        "owned_bytes": {}, "hook_handlers": {},
        mode_hint_config.RECORD_KEY: {"path": str(home / "config.toml"), "prior": {"present": False},
            "fragment": mode_hint_config.MARKER, "leaf_fragment": mode_hint_config.MARKER},
        wait_guidance_config.RECORD_KEY: {"path": str(home / "config.toml"), "prior": {"present": False},
            "fragment": wait_guidance_config._fragment("\n")},
        catalog.RECORD_KEY: catalog_record,
        catalog_recovery.POLICY_KEY: {"format": catalog_recovery.POLICY_FORMAT,
            "project_root": str(tmp_path.resolve())}}
    assert host_maintenance.validate_ownership(identity.canonical(receipt), installed, {}) == receipt
    incomplete = {**receipt, "release_binding": {"manifest_sha256": "f" * 64}}
    with pytest.raises(ValueError, match="release"):
        host_maintenance.validate_ownership(identity.canonical(incomplete), installed, {})
    wrong_capability = {**receipt, "required_capabilities": [host_maintenance.RELEASE_CAPABILITY]}
    with pytest.raises(ValueError, match="release"):
        host_maintenance.validate_ownership(identity.canonical(wrong_capability), installed, {})

    # The old version-1 reader ignores unknown fields, so that field remains
    # legacy data and cannot be promoted to current release ownership.
    legacy = {**receipt, "format": host_maintenance.RECEIPT_FORMAT,
        "required_capabilities": receipt["required_capabilities"]}
    legacy.pop(mode_hint_config.RECORD_KEY)
    legacy.pop(wait_guidance_config.RECORD_KEY)
    legacy.pop(catalog.RECORD_KEY)
    legacy.pop(catalog_recovery.POLICY_KEY)
    legacy["release_binding"] = {"not": "trusted by a v1 receipt"}
    legacy.pop("required_capabilities")
    old = host_maintenance.validate_ownership(identity.canonical(legacy), installed, {})
    assert host_maintenance.selected_release_binding({"source_pin": receipt["source_pin"]}, installed, old) is None


@pytest.mark.parametrize("selected", [None, [], {"release_binding": []},
    {"executable": [], "runtime_sha256": "not-a-hash", "source_pin": {}, "release_binding": {}}])
def test_malformed_saved_candidate_records_are_preserved_and_skipped(tmp_path, monkeypatch, selected):
    cache = tmp_path / "cache"
    cache.mkdir()
    malformed = cache / "candidate-interrupted.json"
    original = identity.canonical({"format": manager.CANDIDATE_FORMAT, "selected": selected})
    malformed.write_bytes(original)
    binding = bound()
    replacement = {"executable": str(tmp_path / "runtime" / "Scripts" / "thaliris.exe"),
        "runtime_sha256": "c" * 64, "source_pin": "sha256:" + "a" * 64,
        "release_binding": binding}
    monkeypatch.setattr(host_maintenance, "selected_runtime", lambda _value: (Path(replacement["executable"]), b"runtime"))
    monkeypatch.setattr(host_preflight, "verify_runtime", lambda *_args: None)
    monkeypatch.setattr(manager.runtime_setup, "create", lambda *_args: {
        "executable": replacement["executable"], "runtime_sha256": replacement["runtime_sha256"]})
    selected_result = manager.prepare(cache, binding, {"core": Path("core.whl"), "adapter": Path("adapter.whl")})
    assert selected_result == replacement
    assert malformed.read_bytes() == original
    candidates = sorted(cache.glob("candidate-*.json"))
    assert len(candidates) == 2 and malformed in candidates
    created = next(path for path in candidates if path != malformed)
    assert manager.validate_candidate(json.loads(created.read_bytes()), binding) == replacement


def _installed_status_fixture(tmp_path, monkeypatch, executable):
    from thaliris_codex import codex_adapter
    from thaliris_codex import wait_guidance_config
    from tests.test_host_maintenance_contract import intent as maintenance_intent

    home = tmp_path / "host"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(wait_guidance_config, "capability", lambda: "SUPPORTED")
    contract = maintenance_intent(tmp_path, home, executable)
    outcome = codex_adapter.codex_install(maintenance_contract=contract)
    assert outcome["ok"], outcome
    installed = runtime_identity.manifest_bytes(executable)
    monkeypatch.setattr(host_maintenance, "_installed", lambda _home: installed)
    monkeypatch.setattr(runtime_identity, "validate_existing_manifest", lambda *_args: None)
    return home


def test_status_detects_owned_host_surface_edits_separately_from_runtime(tmp_path, monkeypatch, pinned_test_thaliris):
    from thaliris_codex import codex_adapter, mode_hint_config, model_catalog_config as catalog
    from thaliris_codex import wait_guidance_config

    executable, _ = pinned_test_thaliris
    home = _installed_status_fixture(tmp_path, monkeypatch, executable)
    receipt_path = home / host_maintenance.RECEIPT_NAME
    receipt = json.loads(receipt_path.read_bytes())
    agents_path = next(home / name for name in receipt["owned_bytes"] if name.startswith("agents/"))
    agents_path.write_bytes(agents_path.read_bytes() + b"\n# user changed owned profile\n")

    agents = home / "AGENTS.md"
    raw = agents.read_bytes()
    span = codex_adapter._global_agents_span(raw)
    assert span is not None
    start, end = span
    managed = raw[start:end]
    changed = managed.replace(b"Thaliris", b"Thalirix", 1)
    assert changed != managed
    agents.write_bytes(raw[:start] + changed + raw[end:])

    hooks_path = home / "hooks.json"
    hooks = json.loads(hooks_path.read_bytes())
    owned_entry = receipt["hook_handlers"][next(event for event, entries in receipt["hook_handlers"].items() if entries)][0]
    event = next(event for event, entries in receipt["hook_handlers"].items() if entries)
    stored = hooks["hooks"][event]
    target = next(entry for entry in stored if entry == owned_entry)
    target["hooks"][0]["command"] += " --edited"
    hooks_path.write_text(json.dumps(hooks), encoding="utf-8")

    config_path = home / "config.toml"
    config = config_path.read_bytes()
    catalog_record = receipt[catalog.RECORD_KEY]
    config = config.replace(b'multi_agent_mode_hint_text = ""', b'multi_agent_mode_hint_text = "user edit"', 1)
    config = config.replace(json.dumps(wait_guidance_config.GUIDANCE).encode(),
                            json.dumps(wait_guidance_config.GUIDANCE + " user edit").encode(), 1)
    config = config.replace(json.dumps(catalog_record["catalog_path"]).encode(),
                            json.dumps(catalog_record["catalog_path"] + ".changed").encode(), 1)
    config_path.write_bytes(config)
    (home / catalog.NAME).write_bytes((home / catalog.NAME).read_bytes() + b" ")

    before = {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}
    out = manager.status(home, tmp_path, bound(), tmp_path)
    surfaces = out["host_surfaces"]
    assert out["installed_disk"]["runtime_status"] == "MATCH"
    assert out["loaded_host"] == out["restart_required"] == "UNKNOWN"
    assert surfaces["status"] == "USER_CHANGED_PRESERVED"
    assert surfaces["owned_files"][agents_path.relative_to(home).as_posix()] == "USER_CHANGED_PRESERVED"
    assert surfaces["global_agents"] == "USER_CHANGED_PRESERVED"
    assert surfaces["owned_hooks"] == "USER_CHANGED_PRESERVED"
    assert surfaces["owned_config_fragments"][mode_hint_config.RECORD_KEY] == "USER_CHANGED_PRESERVED"
    assert surfaces["owned_config_fragments"][wait_guidance_config.RECORD_KEY] == "USER_CHANGED_PRESERVED"
    assert surfaces["owned_config_fragments"][catalog.RECORD_KEY] == "USER_CHANGED_PRESERVED"
    assert agents_path.relative_to(home).as_posix() in surfaces["preserved_user_modifications"]
    assert {path: path.read_bytes() for path in home.rglob("*") if path.is_file()} == before


def test_status_ignores_unrelated_user_edits_inside_shared_host_files(tmp_path, monkeypatch, pinned_test_thaliris):
    executable, _ = pinned_test_thaliris
    home = _installed_status_fixture(tmp_path, monkeypatch, executable)
    agents = home / "AGENTS.md"
    agents.write_bytes(agents.read_bytes() + b"\n## User preference\nKeep this text.\n")

    hooks_path = home / "hooks.json"
    hooks = json.loads(hooks_path.read_bytes())
    hooks.setdefault("hooks", {}).setdefault("PostToolUse", []).append({
        "matcher": "User-owned", "hooks": [{"type": "command", "command": "user-hook"}]})
    hooks_path.write_text(json.dumps(hooks), encoding="utf-8")

    config = home / "config.toml"
    config.write_bytes(b'unrelated_user_setting = "keep"\n' + config.read_bytes())
    (home / "user-owned.txt").write_text("preserve", encoding="utf-8")
    before = {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}

    out = manager.status(home, tmp_path, bound(), tmp_path)
    surfaces = out["host_surfaces"]
    assert surfaces["status"] == "MATCH"
    assert surfaces["global_agents"] == surfaces["owned_hooks"] == "MATCH"
    assert all(value in {"MATCH", "NOT_MANAGED"} for value in surfaces["owned_config_fragments"].values())
    assert surfaces["preserved_user_modifications"] == []
    assert {path: path.read_bytes() for path in home.rglob("*") if path.is_file()} == before


def test_status_identifies_project_definition_ahead_of_validated_installed_reader(tmp_path, monkeypatch, pinned_test_thaliris):
    from thaliris_codex import codex_adapter

    executable, _ = pinned_test_thaliris
    home = _installed_status_fixture(tmp_path, monkeypatch, executable)
    project = tmp_path / "current-project"
    project.mkdir()
    codex_adapter.init(project)
    expected_current = identity.sha256(codex_adapter.render_managed().removesuffix("\n").encode("utf-8"))
    monkeypatch.setattr(identity, "validate_selected", lambda *_args, **_kwargs: None)
    observed = {}

    def old_reader(exe, arguments, *, home: Path, project: Path):
        observed["executable"] = exe
        observed["arguments"] = arguments
        observed["home"] = home
        observed["project"] = project
        return {"ok": True, "expected_managed_instruction_sha256": "0" * 64,
                "session_restart_required": False}

    monkeypatch.setattr(manager, "_run", old_reader)
    out = manager.status(home, tmp_path / "cache", bound(), project)
    assert out["project_definition"]["expected_managed_instruction_sha256"] == expected_current
    assert out["project_definition"]["managed_instruction_sha256"] == expected_current
    assert out["project_host_relation"] == "HOST_UPDATE_REQUIRED"
    assert out["project_host_relation_reason"] == "project_matches_current_reader_but_not_installed_reader"
    assert out["project_host_relation_evidence"]["installed_reader_expected_managed_instruction_sha256"] == "0" * 64
    assert any(item.startswith("HOST_UPDATE_REQUIRED:") for item in out["manual_action_required"])
    assert out["loaded_host"] == out["restart_required"] == "UNKNOWN"
    assert observed == {"executable": str(executable), "arguments": ["bootstrap-check"],
                        "home": home, "project": project}


def test_status_passes_custom_home_to_current_and_installed_diagnostics(tmp_path, monkeypatch, pinned_test_thaliris):
    from thaliris_codex import codex_adapter, lifecycle

    executable, _ = pinned_test_thaliris
    custom_home = _installed_status_fixture(tmp_path, monkeypatch, executable)
    default_home = tmp_path / "different-process-home"
    monkeypatch.setenv("CODEX_HOME", str(default_home))
    project = tmp_path / "custom-home-project"
    project.mkdir()
    calls = []
    original = lifecycle.host_hooks_health
    monkeypatch.setattr(lifecycle, "host_hooks_health", lambda home: (calls.append(home), original(home))[1])
    observed = {}

    def installed_reader(_exe, _arguments, *, home: Path, project: Path):
        observed["home"] = home
        observed["project"] = project
        return {"ok": True, "expected_managed_instruction_sha256": "1" * 64}

    monkeypatch.setattr(manager, "_run", installed_reader)
    out = manager.status(custom_home, tmp_path / "cache", bound(), project)
    assert out["project_definition"]["host_hook_registration_present"] == original(custom_home)["hooks_configured"]
    assert calls and calls[-1] == custom_home
    assert observed == {"home": custom_home, "project": project}
    assert out["project_host_relation"] == "UNKNOWN"
    assert out["restart_required"] == "UNKNOWN"


def test_status_does_not_execute_unverified_installed_runtime_for_project_relation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / runtime_identity.MANIFEST_NAME).write_bytes(b"malformed user-owned manifest")
    executed = []
    monkeypatch.setattr(manager, "_run", lambda *args, **kwargs: executed.append(args) or {"ok": True})
    out = manager.status(home, tmp_path / "cache", bound(), tmp_path)
    assert out["installed_disk"] == "UNVERIFIED"
    assert out["project_host_relation"] == "UNKNOWN"
    assert executed == []
