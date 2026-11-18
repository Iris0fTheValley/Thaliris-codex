"""ACTIVE tasks created by "old" adapter code keep working under "new" code.

Each case builds a task with the current code, then simulates an upgrade by
monkeypatching the constants or tables a later release would change (ledger
version and migrations, adapter protocol and its supported range, matcher
tool lists, rendered profiles, rename tables). Only data newer than the code
and real violations of a frozen constraint are refused.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from thaliris import core
from thaliris_codex import cli, codex_adapter, host_maintenance, lifecycle, roles, task_authority
from tests.host_maintenance_test_support import authorized_host_install
from tests.test_nested_scanner import active, event, finish, identity, native_return, spawn, start, state  # noqa: F401


def ledger_path(root: Path) -> Path:
    return lifecycle._lifecycle_path(root, core.task_show(root)["state"]["task_id"])


def raw_ledger(root: Path) -> dict:
    return json.loads(ledger_path(root).read_text(encoding="utf-8"))


def old_code_write(root: Path, mutate) -> None:
    """Rewrite the ledger through the checked capture path, as older code did."""
    with task_authority._lock(root):
        value = raw_ledger(root)
        mutate(value)
        lifecycle._write_capture(ledger_path(root), value)


def close(root: Path) -> dict:
    return codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])


def abandon(root: Path, session: str = "recovery-session") -> dict:
    task_id = core.selected_task(root) or core.task_show(root)["state"]["task_id"]
    core.select_task(root, task_id)
    payload = {"session_id": session, "turn_id": "recovery-turn", "tool_name": "Bash", "tool_input": {
        "command": f"thaliris task-abandon --task-id {task_id} --revision 1 --state-sha256 x --lifecycle-sha256 x --reason upgrade"}}
    result = json.loads(lifecycle.handle_hook(root, "PreToolUse", payload, lifecycle.MANAGED_HOOK_ABI))
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow", result
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", result["hookSpecificOutput"]["updatedInput"]["command"]).group(1)
    revision = core.task_show(root)["state"]["revision"]
    path = ledger_path(root)
    return codex_adapter.task_abandon(
        root, task_id, revision, task_authority.digest(core._state_path(root, task_id)),
        task_authority.digest(path), "Controller abandons the task after an adapter upgrade", token)


# --- 1. ledger versions migrate forward ---------------------------------

def test_older_ledger_version_migrates_forward_and_persists_on_next_write(active, monkeypatch):
    child = start(active)
    assert raw_ledger(active)["version"] == 12
    seen = []

    def v12_to_v13(value):
        seen.append(value["version"])
        value["v13_field"] = "migrated"
        return value

    monkeypatch.setattr(lifecycle, "LIFECYCLE_STATE_VERSION", 13)
    monkeypatch.setattr(lifecycle, "_LIFECYCLE_MIGRATIONS", {12: v12_to_v13})
    loaded = state(active)
    assert loaded["version"] == 13 and loaded["v13_field"] == "migrated" and seen == [12]
    assert raw_ledger(active)["version"] == 12  # reading never rewrites
    assert lifecycle.native_execution_diagnostic(active)["blockers"][0]["kind"] != "lifecycle-schema-or-task-conflict"
    finish(active, child)  # the next checked write persists the migration
    assert raw_ledger(active)["version"] == 13 and raw_ledger(active)["v13_field"] == "migrated"
    assert task_authority.check(active)["lifecycle_sha256"] == task_authority.digest(ledger_path(active))
    assert lifecycle.native_execution_closed(active)
    assert close(active)["status"] == "DONE"


def test_newer_ledger_version_is_refused_with_upgrade_message(active):
    start(active)
    old_code_write(active, lambda value: value.update(version=lifecycle.LIFECYCLE_STATE_VERSION + 1))
    with pytest.raises(lifecycle.LifecycleVersionUnsupported, match="NEWER_THAN_ADAPTER.*[Uu]pgrade the adapter"):
        state(active)
    blockers = lifecycle.native_execution_diagnostic(active)["blockers"]
    assert blockers[0]["kind"] == "lifecycle-version-unsupported"
    assert blockers[0]["version"] == lifecycle.LIFECYCLE_STATE_VERSION + 1
    with pytest.raises(core.ThalirisError, match="native execution risk"):
        close(active)


def test_unmigratable_old_version_is_named_not_misread(active, monkeypatch):
    start(active)
    monkeypatch.setattr(lifecycle, "LIFECYCLE_STATE_VERSION", 14)
    monkeypatch.setattr(lifecycle, "_LIFECYCLE_MIGRATIONS", {})
    with pytest.raises(lifecycle.LifecycleVersionUnsupported, match="no migration from lifecycle state version 12"):
        state(active)


# --- 2. protocol-range stamps -------------------------------------------

def test_protocol_bump_inside_supported_range_keeps_wait_and_close(active, monkeypatch):
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {"status": "PASS", "effective_max_wait_timeout_ms": 60000})
    parent = start(active, "implementer")
    scanner = start(active, "investigator", "scanner", parent)
    assert raw_ledger(active)["adapter_protocol_version"] == 9
    # New code: protocol 10 whose range keeps 9 interpretable.
    monkeypatch.setattr(lifecycle, "CODEX_ADAPTER_PROTOCOL_VERSION", 10)
    monkeypatch.setattr(lifecycle, "SUPPORTED_ADAPTER_PROTOCOLS", range(9, 11))
    assert lifecycle.managed_dependency_pending(active, parent)
    assert all(item["kind"] != "lifecycle-protocol-conflict"
               for item in lifecycle.native_execution_diagnostic(active)["blockers"])
    wait = {**parent, "tool_name": "wait_agent", "tool_input": {"timeout_ms": 10_000}}
    assert codex_adapter.audit_hook(active, "PreToolUse", wait) == ""
    finish(active, scanner, parent)
    finish(active, parent)
    assert raw_ledger(active)["adapter_protocol_version"] == 10  # refreshed by the stamping write
    assert lifecycle.native_execution_closed(active)
    assert close(active)["status"] == "DONE"


def test_protocol_outside_supported_range_is_refused_but_abandon_works(active, monkeypatch):
    child = start(active)
    monkeypatch.setattr(lifecycle, "CODEX_ADAPTER_PROTOCOL_VERSION", 11)
    monkeypatch.setattr(lifecycle, "SUPPORTED_ADAPTER_PROTOCOLS", range(11, 12))
    diagnostic = lifecycle.native_execution_diagnostic(active)
    conflict = next(item for item in diagnostic["blockers"] if item["kind"] == "lifecycle-protocol-conflict")
    assert conflict["adapter_protocol_version"] == 9 and conflict["supported_adapter_protocols"] == [11, 11]
    assert not lifecycle.managed_dependency_pending(active)
    wait = {**event(), "tool_name": "wait_agent", "tool_input": {"timeout_ms": 10_000}}
    assert "protocol is unresolved" in lifecycle._managed_wait_guard(active, wait)
    with pytest.raises(core.ThalirisError, match="native execution risk"):
        close(active)
    assert child  # the old child stays recorded; abandon archives it unchanged
    assert abandon(active)["status"] == "ABANDONED"


def test_tool_list_edit_changes_hook_hash_but_not_compatibility(active, monkeypatch):
    child = start(active)
    finish(active, child)
    stamped = raw_ledger(active)["managed_hook_spec_hash"]
    names = (*lifecycle._COLLABORATION_TOOL_NAMES, "future_collaboration_tool")
    pattern = "(?:" + "|".join(re.escape(name) for name in names) + ")"
    monkeypatch.setattr(lifecycle, "POST_TOOL_MATCHER", rf"^(?:{pattern}|(?:[A-Za-z0-9_]+\.)+{pattern})$")
    assert lifecycle.managed_hook_spec_hash() != stamped
    assert lifecycle.lifecycle_stamp_compatible(raw_ledger(active))
    assert lifecycle.native_execution_closed(active)
    assert close(active)["status"] == "DONE"


# --- 3. semantic execution-constraint check -----------------------------

def _install_profiles(home: Path, constraint, *, model=None, effort=None, suffix: str = "") -> None:
    agents = home / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name, (default_model, default_effort, role) in roles.agent_profiles(constraint).items():
        rendered = codex_adapter._agent_profile(name[:-5], role, model or default_model, effort or default_effort)
        (agents / name).write_bytes(rendered + suffix.encode())


@pytest.fixture
def constrained(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "authority")
    _install_profiles(home, "luna-only")
    codex_adapter.init(root)
    started = core.task_start(root, "constraint continuity", None, None)
    intent = dict(human_instruction="Use Luna for every worker", boundary="marker", invariants="Same roles",
                  acceptance="All roles available", execution_mode="delegated", execution_constraint="luna-only")
    owner = hashlib.sha256(b"root-session").hexdigest()
    task_authority.establish(root, core._load_state(root), intent, owner)
    lifecycle.record_task_start_owner(root, started["task_id"], owner)
    return root, home


def luna_spawn(role="implementer"):
    return dict(session_id="root-session", turn_id="root-turn", tool_name="spawn_agent", tool_input=dict(
        agent_type=roles.get_codex_binding(role).native_profile, fork_turns="none", message="Selected marker task"))


def test_constrained_task_survives_regenerated_luna_profiles_and_unrelated_config_edit(constrained):
    root, home = constrained
    anchored = task_authority.read(root)["execution_profiles"]
    assert anchored["status"] == "SATISFIED" and "files" not in anchored
    # A later release renders different text on a newer Luna model and effort.
    _install_profiles(home, "luna-only", model="gpt-6.1-luna", effort="max", suffix="# regenerated\n")
    (home / "config.toml").write_text('model = "gpt-6.1-sol"\n[features]\nunrelated = true\n', encoding="utf-8")
    assert task_authority.check(root)["contract"]["execution_constraint"] == "luna-only"
    assert lifecycle.handle_hook(root, "PreToolUse", luna_spawn()) == ""
    child = dict(session_id="root-session", turn_id="child-turn", agent_id="child",
                 agent_type=roles.get_codex_binding("implementer").native_profile, model="gpt-6.1-luna")
    lifecycle.handle_hook(root, "PostToolUse", {**luna_spawn(), "tool_response": {"agent_id": "child", "nickname": None}})
    assert lifecycle._record_subagent_start(root, child)


def test_constrained_task_refuses_non_luna_edit_then_recovers_or_abandons(constrained):
    root, home = constrained
    reviewer = home / "agents" / roles.get_codex_binding("reviewer").profile_filename
    original = reviewer.read_bytes()
    reviewer.write_bytes(original.replace(b'model = "gpt-6-luna"', b'model = "gpt-6.1-sol"'))
    with pytest.raises(task_authority.ExecutionConstraintUnsatisfied, match="CONSTRAINT_MISMATCH"):
        task_authority.check(root)
    assert "EXECUTION_CONSTRAINT_UNSATISFIED" in lifecycle.handle_hook(root, "PreToolUse", luna_spawn())
    unnamed = luna_spawn()
    unnamed["tool_input"].pop("agent_type")
    assert "EXECUTION_CONSTRAINT" in lifecycle.handle_hook(root, "PreToolUse", unnamed)
    status = cli._task_status(root, suppress_protocol_notice=True)
    assert status["Task Authority"]["execution_constraint"]["status"] == "UNSATISFIED"
    # Removing the model so the user config decides is also judged by policy.
    reviewer.write_bytes(re.sub(rb'model = "[^"]+"\n', b"", original, count=1))
    (home / "config.toml").write_text('model = "gpt-6.1-sol"\n', encoding="utf-8")
    with pytest.raises(task_authority.ExecutionConstraintUnsatisfied):
        task_authority.check(root)
    # Recovery re-derives the summary and records the unmet policy.
    recovered = task_authority.recover(root, task_authority.digest(task_authority.path(root)), "profile edited")
    assert recovered["status"] == "TASK_AUTHORITY_RECOVERED"
    assert task_authority.read(root)["execution_profiles"]["status"] == "UNSATISFIED"
    # Restoring a policy-satisfying installation restores managed control.
    reviewer.write_bytes(original)
    assert task_authority.check(root) is not None
    assert lifecycle.handle_hook(root, "PreToolUse", luna_spawn()) == ""
    # Abandon stays available while the constraint is unsatisfied.
    reviewer.write_bytes(original.replace(b'model = "gpt-6-luna"', b'model = "gpt-6.1-sol"'))
    assert abandon(root)["status"] == "ABANDONED"


def test_unknown_constraint_refuses_control_but_allows_close(constrained, monkeypatch):
    root, _ = constrained
    monkeypatch.setattr(roles, "EXECUTION_CONSTRAINTS", ())
    with pytest.raises(task_authority.ExecutionConstraintUnsatisfied, match="UNSUPPORTED_EXECUTION_CONSTRAINT"):
        task_authority.check(root)
    assert "EXECUTION_CONSTRAINT_UNSATISFIED" in lifecycle.handle_hook(root, "PreToolUse", luna_spawn())
    assert close(root)["status"] == "DONE"


def test_renamed_constraint_resolves_through_alias(constrained, monkeypatch):
    root, home = constrained
    monkeypatch.setattr(roles, "EXECUTION_CONSTRAINTS", ("luna-family",))
    monkeypatch.setattr(roles, "EXECUTION_CONSTRAINT_ALIASES", {"luna-only": "luna-family"})
    monkeypatch.setattr(roles, "EXECUTION_CONSTRAINT_POLICIES",
                        {"luna-family": roles.ExecutionConstraintPolicy("luna", frozenset({"xhigh"}))})
    assert task_authority.check(root)["contract"]["execution_constraint"] == "luna-family"
    assert task_authority.read(root)["contract"]["execution_constraint"] == "luna-only"  # stored intent unchanged


# --- 4. role / profile aliases ------------------------------------------

def _reserve(root, role, agent, actor=None):
    request = spawn(actor, role)
    assert lifecycle.handle_hook(root, "PreToolUse", request) == ""
    native_return(root, request, agent)
    return identity(role, agent)


def _retire(value, old_role, old_type):
    reservation = value["pending_authorized_spawn"]
    reservation["role"], reservation["expected_agent_type"] = old_role, old_type


def test_renamed_role_resolves_through_alias_table(active, monkeypatch):
    child = _reserve(active, "investigator", "scout")
    old_code_write(active, lambda value: _retire(value, "scout", "thaliris-scout"))
    monkeypatch.setattr(roles, "ROLE_ID_ALIASES", {"scout": "investigator"})
    monkeypatch.setattr(roles, "NATIVE_PROFILE_ALIASES", {"thaliris-scout": "thaliris-investigator"})
    pending = state(active)["pending_authorized_spawn"]
    assert (pending["role"], pending["expected_agent_type"]) == ("investigator", "thaliris-investigator")
    assert "role_resolution" not in pending
    # The Host may still report the retired profile name for this dispatch.
    assert lifecycle._record_subagent_start(active, {**child, "agent_type": "thaliris-scout"})
    assert state(active)["children"][-1]["handoff_bound"] is True


def test_unknown_role_fails_only_that_reservation(active):
    bound = start(active, "implementer", "known-child")
    child = _reserve(active, "investigator", "retired")
    old_code_write(active, lambda value: _retire(value, "retired-role", "thaliris-retired-role"))
    ledger = state(active)  # the whole ledger still loads
    pending = ledger["pending_authorized_spawn"]
    assert pending["role_resolution"] == "UNKNOWN" and pending["role"] == "retired-role"
    # That dispatch fails closed: it can never bind.
    assert not lifecycle._record_subagent_start(active, child)
    assert state(active)["pending_authorized_spawn"]["handoff_id"] == pending["handoff_id"]
    # The other dependency is unaffected, and the unknown one stays visible and disposable.
    assert lifecycle.handle_hook(active, "PreToolUse", {**bound, "tool_name": "read_file", "tool_input": {}}) == ""
    blockers = lifecycle.native_execution_diagnostic(active)["blockers"]
    assert any(item["kind"] == "authorized-reservation" and item["handoff_id"] == pending["handoff_id"] for item in blockers)
    revision = core.task_show(active)["state"]["revision"]
    lifecycle.task_dispose_dependency(active, pending["handoff_id"], revision,
                                      task_authority.digest(ledger_path(active)), "retired role cannot run")
    assert not lifecycle._pending_reservations(state(active))


# --- 5. receipt-based ownership -----------------------------------------

def test_receipt_owns_previously_written_profiles_after_a_changed_render(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "host"
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert authorized_host_install(tmp_path, pinned_test_thaliris)["ok"]
    name = roles.get_codex_binding("reviewer").profile_filename
    written = (home / "agents" / name).read_bytes()
    receipt = json.loads((home / host_maintenance.RECEIPT_NAME).read_bytes())
    assert receipt["owned_bytes"]["agents/" + name] == hashlib.sha256(written).hexdigest()
    # A new release renders different profile text; no historical table entry exists.
    render = codex_adapter._agent_profile
    monkeypatch.setattr(codex_adapter, "_agent_profile", lambda *args: render(*args) + b"# next release\n")
    assert hashlib.sha256(written).hexdigest() not in codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES.get(name, ())
    assert codex_adapter._agent_profile_state(written, name) == "user"  # tables alone cannot see it
    assert codex_adapter._agent_profile_state(written, name, home=home) == "legacy"
    assert codex_adapter._host_profile_definition_present(home) == "YES"
    assert codex_adapter._installed_execution_constraint() is None
    # A user edit of another profile is still preserved and reported.
    edited = home / "agents" / roles.get_codex_binding("curator").profile_filename
    edited.write_bytes(edited.read_bytes() + b"# user edit\n")
    assert codex_adapter._agent_profile_state(edited.read_bytes(), edited.name, home=home) == "user"
    result = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert result["ok"] is False and any(str(edited) in item for item in result["manual_action_required"])
    assert (home / "agents" / name).read_bytes() == written  # nothing was changed
    # Restoring the user's file lets the receipt-owned refresh proceed.
    edited.write_bytes(edited.read_bytes().removesuffix(b"# user edit\n"))
    assert authorized_host_install(tmp_path, pinned_test_thaliris)["ok"]
    assert (home / "agents" / name).read_bytes() == written + b"# next release\n"


# --- 6. tolerant anchor fields ------------------------------------------

def test_old_anchor_without_adapter_fields_still_loads(active):
    path = task_authority.path(active)
    record = json.loads(path.read_text(encoding="utf-8"))
    for name in ("fenced_sessions", "fenced_agents"):
        record.pop(name)
    path.write_text(json.dumps(record), encoding="utf-8")
    checked = task_authority.check(active)
    assert checked["fenced_sessions"] == [] and checked["fenced_agents"] == []
    # Hook paths that index the fields keep working, and the first checked
    # ledger write persists them.
    child = start(active)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["fenced_sessions"] == [] and stored["lifecycle_sha256"] == task_authority.digest(ledger_path(active))
    finish(active, child)
    assert close(active)["status"] == "DONE"


def test_old_anchor_without_lifecycle_digest_implies_no_ledger(active):
    path = task_authority.path(active)
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("lifecycle_sha256")
    path.write_text(json.dumps(record), encoding="utf-8")
    # A ledger the old anchor never recorded is still detected (fail closed).
    with pytest.raises(ValueError, match="TASK_AUTHORITY_LIFECYCLE_CHANGED"):
        task_authority.check(active)
    ledger_path(active).unlink()
    assert task_authority.check(active)["lifecycle_sha256"] == "ABSENT"
