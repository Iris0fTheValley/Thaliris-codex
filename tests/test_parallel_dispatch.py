"""Parallel dispatch with N>=2 concurrent reservations.

A Controller-selected ``parallel_dispatch`` contract lets the owning
Controller hold several unbound reservations at once, one per declared
workstream. Every reader treats the whole reservation collection as pending;
recovery drops all of it; nested spawns keep the single-reservation rules;
SubagentStart binds only the exact reservation; the managed wait guard keeps
the O3 refusals. Hook payloads are real-shaped fixtures, not a live Host.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from thaliris import core
from thaliris_codex import codex_adapter, codex_bootstrap, lifecycle, roles, task_authority

SESSION = "parallel-controller-session"
OWNER = hashlib.sha256(SESSION.encode()).hexdigest()


def _stream(identifier: str, mode: str = "write") -> dict:
    return {"id": identifier, "domain": "src", "scope": f"src/{identifier}",
            "worktree": f"wt/{identifier}" if mode == "write" else None, "mode": mode}


def _task(root: Path, monkeypatch, parallel: dict | None) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = root / "isolated-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = home / "agents" / name
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    monkeypatch.setattr(task_authority, "directory", lambda: root.parent / (root.name + "-task-authority"))
    codex_adapter.init(root)
    started = core.task_start(root, "parallel dispatch", None, None)
    contract = {
        "human_instruction": "Run independent workstreams in parallel",
        "boundary": "Parallel dispatch fixture",
        "invariants": "Keep every reservation pending until it is bound, terminal or disposed",
        "acceptance": "Selected lifecycle checks pass",
        "execution_mode": "delegated",
    }
    if parallel is not None:
        contract["parallel_dispatch"] = parallel
    task_authority.establish(root, core._load_state(root), contract, OWNER)
    lifecycle.record_task_start_owner(root, started["task_id"], OWNER)
    return root


@pytest.fixture
def parallel(tmp_path, monkeypatch) -> Path:
    return _task(tmp_path, monkeypatch, {"enabled": True, "budget": 3,
                                        "workstreams": [_stream("ws-a"), _stream("ws-b"), _stream("ws-c")]})


@pytest.fixture
def tight(tmp_path, monkeypatch) -> Path:
    return _task(tmp_path, monkeypatch, {"enabled": True, "budget": 2, "workstreams": [_stream("ws-a"), _stream("ws-b")]})


@pytest.fixture
def single(tmp_path, monkeypatch) -> Path:
    return _task(tmp_path, monkeypatch, None)


def event(**values):
    return {"session_id": SESSION, "turn_id": "controller-turn", **values}


def identity(role: str, agent: str) -> dict:
    # Codex child payloads carry the Controller's session_id.
    return event(agent_id=agent, agent_type=f"thaliris-{role}", turn_id=f"{agent}-turn")


def request(role: str = "implementer", *, workstream: str | None = None, actor: dict | None = None,
            call: str | None = None, message: str | None = None, **extra) -> dict:
    pair = roles.ROLE_MODEL_ROUTING_DEFAULTS.get(role)
    text = message or f"Selected {role} work for {workstream or 'one gap'}"
    if workstream is not None and "thaliris-workstream:" not in text:
        text += f"\nthaliris-workstream: {workstream}"
    value = {**(actor or event()), "tool_name": "spawn_agent", "tool_input": {
        "agent_type": f"thaliris-{role}", "fork_turns": "none", "message": text,
        **({"model": pair[0], "reasoning_effort": pair[1]} if pair is not None else {}), **extra}}
    value["tool_use_id"] = call or f"call-{role}-{workstream}-{len(text)}"
    return value


def pre(root: Path, value: dict) -> str:
    return lifecycle.handle_hook(root, "PreToolUse", value)


def denied(output: str, code: str) -> bool:
    return bool(output) and json.loads(output)["hookSpecificOutput"].get("permissionDecision") == "deny" and code in output


def identify(root: Path, value: dict, agent: str) -> None:
    lifecycle.handle_hook(root, "PostToolUse", {**value, "tool_response": {"agent_id": agent, "nickname": None}})


def bind(root: Path, value: dict, role: str, agent: str) -> dict:
    """Pre already allowed: identify, start and name one exact child."""
    identify(root, value, agent)
    child = identity(role, agent)
    assert lifecycle._record_subagent_start(root, child)
    lifecycle.handle_hook(root, "PostToolUse", {**value, "tool_response": {"task_name": f"/root/{agent}"}})
    return child


def finish(root: Path, child: dict, observer: dict | None = None, status: str = "completed") -> None:
    call = {**(observer or event()), "tool_name": "list_agents", "tool_use_id": "list-" + child["agent_id"] + status}
    lifecycle.handle_hook(root, "PreToolUse", call)
    lifecycle.handle_hook(root, "PostToolUse", {**call, "tool_response": {
        "agents": [{"agent_name": f'/root/{child["agent_id"]}', "agent_status": {status: "result"}}]}})


def task_id(root: Path) -> str:
    return core.task_show(root)["state"]["task_id"]


def ledger(root: Path) -> dict:
    return lifecycle._load_lifecycle(lifecycle._lifecycle_path(root, task_id(root)), task_id(root))


def reservations(root: Path) -> list[dict]:
    return lifecycle._pending_reservations(ledger(root))


def child_record(root: Path, agent: str) -> dict:
    return next(item for item in ledger(root)["children"] if item.get("agent_id_hash") == lifecycle._identity_hash(agent))


def dispose(root: Path, handoff_id: str) -> dict:
    return lifecycle.task_dispose_dependency(root, handoff_id, core.task_show(root)["state"]["revision"],
        task_authority.digest(lifecycle._lifecycle_path(root, task_id(root))), "Controller dropped this workstream")


def close(root: Path) -> dict:
    return codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])


def switch(root: Path) -> dict:
    return task_authority.switch_mode(root, task_authority.digest(task_authority.path(root)),
        core.task_show(root)["state"]["revision"], "single-agent", "User selected direct execution")


def reservation_blockers(root: Path) -> list[str | None]:
    return [row["handoff_id"] for row in lifecycle.native_execution_diagnostic(root)["blockers"]
            if row["kind"] == "authorized-reservation"]


# Finding 1 / D1: dispose, close, diagnostic, pending check and mode switch.

def test_disposing_any_reservation_keeps_the_rest_pending_until_all_are_resolved(parallel):
    root = parallel
    for stream in ("ws-a", "ws-b", "ws-c"):
        assert pre(root, request(workstream=stream)) == ""
    a, b, c = (item["handoff_id"] for item in reservations(root))
    raw = json.loads(lifecycle._lifecycle_path(root, task_id(root)).read_text(encoding="utf-8"))
    # The legacy slot is the first item of the collection, not a second truth.
    assert raw["pending_authorized_spawn"]["handoff_id"] == a
    assert [item["handoff_id"] for item in raw["pending_authorized_spawns"]] == [b, c]
    assert reservation_blockers(root) == [a, b, c]

    # A non-first reservation is found by its handoff.
    result = dispose(root, b)
    assert result["fencing"] == [{"kind": "pending", "agent_fenced": False,
                                  "agent_fence_reason": "no native actor identity recorded"}]
    assert [item["handoff_id"] for item in reservations(root)] == [a, c]
    assert lifecycle.managed_dependency_pending(root)
    with pytest.raises(core.ThalirisError) as refused:
        close(root)
    assert refused.value.code == "TASK_NATIVE_EXECUTION_RISK"
    with pytest.raises(ValueError, match="TASK_MODE_SWITCH_DEPENDENCIES_PENDING"):
        switch(root)

    # Disposing the first promotes the next; nothing is silently cleared.
    dispose(root, a)
    raw = json.loads(lifecycle._lifecycle_path(root, task_id(root)).read_text(encoding="utf-8"))
    assert raw["pending_authorized_spawn"]["handoff_id"] == c and raw["pending_authorized_spawns"] == []
    assert reservation_blockers(root) == [c]
    assert not lifecycle.native_execution_closed(root)
    assert lifecycle.managed_dependency_pending(root)
    with pytest.raises(core.ThalirisError) as refused:
        close(root)
    assert refused.value.code == "TASK_NATIVE_EXECUTION_RISK"
    with pytest.raises(ValueError, match="TASK_MODE_SWITCH_DEPENDENCIES_PENDING"):
        switch(root)
    # Another dispatch selection is refused while any reservation is pending.
    source = root / "next.json"
    source.write_text(json.dumps({"next_dispatch": {"role": "implementer", "expected_agent_type": "thaliris-implementer",
                                                    "candidate": "C1", "requirement_refs": []}}), encoding="utf-8")
    with pytest.raises(core.ThalirisError) as pending:
        codex_adapter.task_evidence_register(root, "controller", core.task_show(root)["state"]["revision"], str(source), OWNER)
    assert pending.value.code == "EVIDENCE_DISPATCH_PENDING"
    assert pending.value.details["selection"]["handoff_id"] == c

    dispose(root, c)
    assert reservations(root) == []
    assert lifecycle.native_execution_closed(root) and not lifecycle.managed_dependency_pending(root)
    assert {row["record"]["handoff_id"] for row in ledger(root)["dependency_dispositions"]} == {a, b, c}
    assert switch(root)["task_id"] == task_id(root)
    assert close(root)["task_disposition"] == "CLOSED_BY_CONTROLLER"


def test_bootstrap_and_abandon_read_every_reservation(parallel):
    root = parallel
    for stream in ("ws-a", "ws-b"):
        assert pre(root, request(workstream=stream)) == ""
    path = lifecycle._lifecycle_path(root, task_id(root))
    value = ledger(root)
    # Legacy owner evidence: no recorded owner, only depth-one reservations.
    del value["owner_session_id_hash"]
    lifecycle._write_capture(path, value)
    assert lifecycle._pending_controller_owner(ledger(root)) == OWNER
    assert lifecycle.active_controller_owner(root, task_id(root)) == OWNER
    status = codex_bootstrap._task_preflight(root)
    assert status["status"] == "ACTIVE"
    assert status["owner_session_id_hash"] == OWNER and status["owner_provenance"] == "DEPTH_ONE_PENDING_RESERVATION"
    # A nested reservation is not depth-one owner evidence.
    nested = dict(value["pending_authorized_spawns"][0], depth=2)
    assert lifecycle._pending_controller_owner({"pending_authorized_spawn": nested}) is None

    # A foreign takeover fences the session of every pending reservation.
    state_path = core._state_path(root)
    revision = core.task_show(root)["state"]["revision"]
    command = (f'thaliris task-abandon --task-id {task_id(root)} --revision {revision} '
               f'--state-sha256 {task_authority.digest(state_path)} --lifecycle-sha256 {task_authority.digest(path)} --reason abandon')
    output = lifecycle.handle_hook(root, "PreToolUse", {"cwd": str(root), "session_id": "replacement", "tool_name": "Bash",
        "tool_input": {"command": command}}, lifecycle.MANAGED_HOOK_ABI)
    token = json.loads(output)["hookSpecificOutput"]["updatedInput"]["command"].split("--hook-attestation ", 1)[1]
    result = codex_adapter.task_abandon(root, task_id(root), revision, task_authority.digest(state_path),
                                        task_authority.digest(path), "abandon", token)
    manifest = json.loads((root / result["archive"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["old_controller_owner_provenance"] == "DEPTH_ONE_PENDING_RESERVATION"
    assert manifest["fenced_old_session_provenance"][OWNER][:3] == [
        "owner:DEPTH_ONE_PENDING_RESERVATION", "pending_authorized_spawn", "pending_authorized_spawns[0]"]


# Finding 2 / D2: recovery drops the whole collection and fences its agents.

def test_recovery_drops_every_reservation_and_fences_identified_agents(parallel):
    root = parallel
    first, second = request(workstream="ws-a"), request(workstream="ws-b")
    assert pre(root, first) == "" and pre(root, second) == ""
    identify(root, second, "old-child-b")  # identified, never started
    assert len(reservations(root)) == 2
    path = lifecycle._lifecycle_path(root, task_id(root))
    original = task_authority.path(root).read_bytes()
    path.unlink()
    task_authority.recover(root, hashlib.sha256(original).hexdigest(), "Human selected recovery; fence the old dispatches")

    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored["pending_authorized_spawn"] is None and restored["pending_authorized_spawns"] == []
    assert reservations(root) == [] and not lifecycle.managed_dependency_pending(root)
    assert lifecycle._identity_hash("old-child-b") in task_authority.read(root)["fenced_agents"]
    # The identified agent is fenced: its hooks are refused and its Start binds nothing.
    old_b = identity("implementer", "old-child-b")
    assert "ABANDONED_ACTOR" in lifecycle.handle_hook(root, "PreToolUse", {**old_b, "tool_name": "Bash",
        "tool_input": {"command": "git status"}}, lifecycle.MANAGED_HOOK_ABI)
    assert lifecycle.handle_hook(root, "SubagentStart", old_b) == ""
    assert not lifecycle._record_subagent_start(root, old_b)
    # The unidentified dispatch's late child has no reservation to bind to.
    old_a = identity("implementer", "old-child-a")
    assert not lifecycle._record_subagent_start(root, old_a)
    assert child_record(root, "old-child-a")["managed"] is False
    assert all(item.get("managed") is False for item in ledger(root)["children"])
    # A fresh handoff is required and may use the workstreams again.
    assert pre(root, request(workstream="ws-a", message="Fresh handoff after recovery")) == ""


# Finding 3 / D3: nested spawns never receive the parallel policy.

def test_nested_executor_keeps_scanner_slot_and_cannot_claim_a_workstream(parallel):
    root = parallel
    executor_request = request("focused-implementer", workstream="ws-a")
    assert pre(root, executor_request) == ""
    executor = bind(root, executor_request, "focused-implementer", "executor")
    assert child_record(root, "executor")["workstream_id"] == "ws-a"
    # Same session id as the Controller: the nested spawn is still nested.
    assert executor["session_id"] == SESSION

    scanner_request = request("investigator", workstream="ws-b", actor=executor, workstream_id="ws-b",
                              message="Scanner facts only")
    assert pre(root, scanner_request) == ""
    nested = reservations(root)[0]
    assert nested["depth"] == 2 and "workstream_id" not in nested
    # While the nested reservation is unbound, the single-reservation rule holds.
    second_scanner = request("investigator", actor=executor, message="Another scanner", workstream_id="ws-c")
    assert denied(pre(root, second_scanner), "THALIRIS_UNBOUND_DISPATCH_PENDING")
    scanner = bind(root, scanner_request, "investigator", "scanner")
    assert child_record(root, "scanner")["workstream_id"] is None
    # One live Scanner per exact parent, whatever the contract says.
    assert denied(pre(root, second_scanner), "THALIRIS_SCANNER_SLOT_ACTIVE")
    assert denied(pre(root, request("investigator", actor=executor, message="Third scanner")), "THALIRIS_SCANNER_SLOT_ACTIVE")

    # The workstream the nested spawn named is still the Controller's to use.
    controller_b = request(workstream="ws-b")
    assert pre(root, controller_b) == ""
    assert [item.get("workstream_id") for item in reservations(root)] == ["ws-b"]
    # A nested spawn is refused while a Controller reservation is unbound.
    finish(root, scanner, observer=executor)
    assert denied(pre(root, request("investigator", actor=executor, message="Fresh scanner")),
                  "THALIRIS_UNBOUND_DISPATCH_PENDING")


# Finding 6 / D4: SubagentStart binds the exact reservation.

def test_out_of_order_start_binds_the_exactly_identified_reservation(parallel):
    root = parallel
    first, second = request(workstream="ws-a"), request(workstream="ws-b")
    assert pre(root, first) == "" and pre(root, second) == ""
    a, b = (item["handoff_id"] for item in reservations(root))
    identify(root, second, "child-b")
    assert lifecycle._record_subagent_start(root, identity("implementer", "child-b"))
    assert child_record(root, "child-b")["handoff_id"] == b
    assert child_record(root, "child-b")["workstream_id"] == "ws-b"
    assert [item["handoff_id"] for item in reservations(root)] == [a]
    identify(root, first, "child-a")
    assert lifecycle._record_subagent_start(root, identity("implementer", "child-a"))
    assert child_record(root, "child-a")["handoff_id"] == a
    assert reservations(root) == []


def test_start_without_exact_identity_binds_nothing_when_ambiguous(parallel):
    root = parallel
    assert pre(root, request(workstream="ws-a")) == "" and pre(root, request(workstream="ws-b")) == ""
    before = [item["handoff_id"] for item in reservations(root)]
    assert not lifecycle._record_subagent_start(root, identity("implementer", "unknown-child"))
    assert child_record(root, "unknown-child")["managed"] is False
    assert [item["handoff_id"] for item in reservations(root)] == before


# Finding 4 / D6: the wait guard fails closed for every target shape.

@pytest.mark.parametrize("wait_input", [{}, {"timeout_ms": 1000}, {"target": "ordinary-child"},
                                        {"id": "ordinary-child"}, {"targets": ["ordinary-child"]}])
def test_wait_with_unidentified_reservations_is_refused_for_every_shape(parallel, wait_input):
    root = parallel
    assert pre(root, request(workstream="ws-a")) == "" and pre(root, request(workstream="ws-b")) == ""
    wait = event(tool_name="wait_agent", tool_input=dict(wait_input))
    output = pre(root, wait)
    assert denied(output, "THALIRIS_WAIT_DEPENDENCY_UNKNOWN"), output
    assert wait["tool_input"] == wait_input


def test_wait_after_identification_and_identity_conflicts_still_refuse(parallel):
    root = parallel
    first, second = request(workstream="ws-a"), request(workstream="ws-b")
    assert pre(root, first) == "" and pre(root, second) == ""
    identify(root, first, "child-a")
    # One identified, one not: the unidentified reservation keeps the wait UNKNOWN.
    assert denied(pre(root, event(tool_name="wait_agent", tool_input={})), "reserved dispatch has no observable native identity")
    identify(root, second, "child-b")
    assert pre(root, event(tool_name="wait_agent", tool_input={})) == ""
    assert pre(root, event(tool_name="wait_agent", tool_input={"targets": ["child-a", "child-b"]})) == ""
    assert denied(pre(root, event(tool_name="wait_agent", tool_input={"targets": ["ordinary-child"]})),
                  "wait target is not an exact direct dependency")
    # Two reservations claiming one native actor: the identity check refuses.
    value = ledger(root)
    value["pending_authorized_spawns"][0]["native_agent_id_hash"] = lifecycle._identity_hash("child-a")
    lifecycle._write_capture(lifecycle._lifecycle_path(root, task_id(root)), value)
    for wait_input in ({}, {"targets": ["child-a"]}, {"target": "child-a"}):
        assert denied(pre(root, event(tool_name="wait_agent", tool_input=wait_input)), "THALIRIS_WAIT_DEPENDENCY_UNKNOWN")


# Finding 5 / D5: evidence plus a workstream.

def test_parallel_dispatch_with_evidence_and_workstreams_is_reserved(parallel):
    root = parallel
    path = root / "requirements.json"
    path.write_text(json.dumps({"requirements": [{"id": "R1", "workchain_ref": "opaque"}]}), encoding="utf-8")
    core.task_evidence_register(root, "controller", core.task_show(root)["state"]["revision"], str(path))
    task_authority.checkpoint(root)
    marker = 'thaliris-evidence: {"candidate":"C1","requirement_refs":["R1"]}'
    first = request(workstream="ws-a", message="Implement slice A\n" + marker)
    second = request("investigator", workstream="ws-b", message="Investigate slice B\n" + marker)
    assert pre(root, first) == "" and pre(root, second) == ""
    pending = reservations(root)
    assert [item["workstream_id"] for item in pending] == ["ws-a", "ws-b"]
    handoffs = {item["id"]: item for item in core.task_show(root)["state"]["evidence_continuity"]["handoffs"]}
    for item in pending:
        assert handoffs[item["handoff_id"]]["candidate"] == "C1"
        assert "workstream_id" not in handoffs[item["handoff_id"]]
    bind(root, second, "investigator", "child-b")
    assert child_record(root, "child-b")["workstream_id"] == "ws-b"
    assert task_authority.check(root) is not None


# Finding 8 / D7: the collection validator equals the singular one.

@pytest.mark.parametrize("damage", ["producer", "missing", "extra", "hash", "parent", "duplicate_handoff",
                                    "duplicate_sequence", "not_a_dict"])
def test_every_collection_item_passes_the_singular_validator(parallel, damage):
    root = parallel
    assert pre(root, request(workstream="ws-a")) == "" and pre(root, request(workstream="ws-b")) == ""
    path = lifecycle._lifecycle_path(root, task_id(root))
    value = json.loads(path.read_text(encoding="utf-8"))
    head, item = value["pending_authorized_spawn"], value["pending_authorized_spawns"][0]
    if damage == "producer":
        item["producer"] = "child"
    elif damage == "missing":
        del item["payload_hash"]
    elif damage == "extra":
        item["unexpected"] = True
    elif damage == "hash":
        item["native_agent_id_hash"] = "not-a-hash"
    elif damage == "parent":
        item["root_handoff_id"] = "handoff-other"
    elif damage == "duplicate_handoff":
        item["handoff_id"] = head["handoff_id"]
    elif damage == "duplicate_sequence":
        item["authorized_sequence"] = head["authorized_sequence"]
    else:
        value["pending_authorized_spawns"][0] = "reservation"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        lifecycle._load_lifecycle(path, task_id(root), verify_authority=False)


# Finding 9 / D8: workstream retry after a terminal dispatch; the budget still counts.

def test_workstream_retry_after_terminal_and_nested_scanners_do_not_count(tight):
    root = tight
    executor_request = request("focused-implementer", workstream="ws-a")
    assert pre(root, executor_request) == ""
    executor = bind(root, executor_request, "focused-implementer", "executor")
    scanner_request = request("investigator", actor=executor, message="Scanner facts only")
    assert pre(root, scanner_request) == ""
    scanner = bind(root, scanner_request, "investigator", "scanner")
    # The user's number counts live top-level dispatches; a nested Scanner is not one.
    assert pre(root, request(workstream="ws-b")) == ""
    retry = request("focused-implementer", workstream="ws-a", message="Retry slice A")
    assert denied(pre(root, retry), "THALIRIS_PARALLEL_WORKSTREAM_DUPLICATE")
    finish(root, scanner, observer=executor)
    assert denied(pre(root, retry), "THALIRIS_PARALLEL_WORKSTREAM_DUPLICATE")  # executor still live
    finish(root, executor, status="errored")
    # A failed dispatch is terminal: its workstream may be reserved again.
    assert pre(root, retry) == ""
    assert sorted(item["workstream_id"] for item in reservations(root)) == ["ws-a", "ws-b"]
    assert denied(pre(root, request(workstream="ws-a", message="Third try")), "THALIRIS_PARALLEL_WORKSTREAM_DUPLICATE")
    # A disposed dispatch is terminal too.
    dispose(root, next(item["handoff_id"] for item in reservations(root) if item["workstream_id"] == "ws-a"))
    assert pre(root, request(workstream="ws-a", message="Third try")) == ""
    assert len(reservations(root)) == 2
    assert denied(pre(root, request(workstream="ws-a", message="Fourth try")), "THALIRIS_PARALLEL_WORKSTREAM_DUPLICATE")


# Revised D8 / D10: user-directed scale; domain overlap is the only refusal.

def _fanout(tmp_path, monkeypatch, count: int, mode: str = "read") -> Path:
    streams = [{"id": f"ws-{index}", "domain": "research", "scope": f"area/{index}",
                "worktree": f"wt/{index}" if mode == "write" else None, "mode": mode} for index in range(count)]
    return _task(tmp_path, monkeypatch, {"enabled": True, "budget": count, "workstreams": streams})


def test_large_read_fanout_runs_at_the_user_selected_scale(tmp_path, monkeypatch):
    root = _fanout(tmp_path, monkeypatch, 12)
    for index in range(12):
        role = "investigator" if index % 2 else "reviewer"
        assert pre(root, request(role, workstream=f"ws-{index}", message=f"Read area {index}")) == ""
    assert sorted(item["workstream_id"] for item in reservations(root)) == sorted(f"ws-{index}" for index in range(12))
    assert len(reservation_blockers(root)) == 12


def test_disjoint_write_scopes_run_in_parallel(tmp_path, monkeypatch):
    root = _fanout(tmp_path, monkeypatch, 5, mode="write")
    for index in range(5):
        assert pre(root, request(workstream=f"ws-{index}", message=f"Write module {index}")) == ""
    assert len(reservations(root)) == 5


def _policy(monkeypatch, *streams: dict, budget: int | None = None) -> None:
    """Patch in a contract shape Core now refuses at admission (overlapping or unscoped writes), to prove the adapter's own dispatch-time guard."""
    policy = {"enabled": True, "workstreams": list(streams)}
    if budget is not None:
        policy["budget"] = budget
    monkeypatch.setattr(lifecycle, "_parallel_dispatch_policy", lambda _root, _session=None: policy)


def _write(identifier: str, scope: object) -> dict:
    return {"id": identifier, "domain": "src", "scope": scope, "worktree": None, "mode": "write"}


def test_overlapping_write_scopes_are_refused_and_reads_never_are(parallel, monkeypatch):
    root = parallel
    _policy(monkeypatch, _write("w-pkg", ["src/pkg"]), _write("w-sub", "src/pkg/sub"), _write("w-other", "src/other"),
            _write("w-parent", "src"), {**_stream("r-pkg", "read"), "scope": "src/pkg"})
    first = request(workstream="w-pkg")
    assert pre(root, first) == ""
    for overlapping in ("w-sub", "w-parent"):
        output = pre(root, request(workstream=overlapping))
        assert denied(output, "THALIRIS_PARALLEL_DOMAIN_OVERLAP") and "disjoint" in output
    assert pre(root, request(workstream="w-other")) == ""
    # A read workstream over the same paths is never refused for overlap.
    assert pre(root, request("investigator", workstream="r-pkg")) == ""
    # Once the overlapping write dispatch is terminal, the inner scope may run.
    dispose(root, next(item["handoff_id"] for item in reservations(root) if item["workstream_id"] == "w-pkg"))
    assert pre(root, request(workstream="w-sub")) == ""
    assert denied(pre(root, request(workstream="w-parent")), "THALIRIS_PARALLEL_DOMAIN_OVERLAP")


def test_write_workstream_without_scope_cannot_run_beside_another_write(parallel, monkeypatch):
    root = parallel
    _policy(monkeypatch, _write("w-any", None), _write("w-mod", "src/mod"), {**_stream("r-any", "read"), "scope": None})
    alone = request(workstream="w-any")
    assert pre(root, alone) == ""  # alone it may run
    output = pre(root, request(workstream="w-mod"))
    assert denied(output, "THALIRIS_PARALLEL_DOMAIN_OVERLAP") and "undeclared" in output and "disjoint" in output
    assert pre(root, request("investigator", workstream="r-any")) == ""
    dispose(root, next(item["handoff_id"] for item in reservations(root) if item["workstream_id"] == "w-any"))
    assert pre(root, request(workstream="w-mod")) == ""
    output = pre(root, request(workstream="w-any", message="Unscoped again"))
    assert denied(output, "THALIRIS_PARALLEL_DOMAIN_OVERLAP") and "no declared scope" in output


def test_an_explicit_user_number_is_honored_and_otherwise_there_is_no_cap(tmp_path, monkeypatch):
    streams = [_write(f"w-{index}", f"src/w{index}") for index in range(14)]
    root = _task(tmp_path, monkeypatch, {"enabled": True, "budget": 3, "workstreams": streams})
    for index in range(3):
        assert pre(root, request(workstream=f"w-{index}")) == ""
    output = pre(root, request(workstream="w-3"))
    assert denied(output, "THALIRIS_PARALLEL_DISPATCH_BUDGET") and "sets 3" in output
    # The stated number counts writing dispatches only: review is never counted.
    assert pre(root, request("reviewer", message="Review the live candidates")) == ""
    # Without a stated number the adapter imposes none.
    root = _task(tmp_path / "uncapped", monkeypatch, {"enabled": True, "workstreams": streams})
    for index in range(14):
        assert pre(root, request(workstream=f"w-{index}")) == ""
    assert len(reservations(root)) == 14


# D11: non-writing roles never need a workstream and never contend.

def test_non_writing_roles_need_no_workstream_and_are_never_counted(tmp_path, monkeypatch):
    root = _task(tmp_path, monkeypatch, {"enabled": True, "budget": 1, "workstreams": [
        _write("w-a", "src/a"), {**_stream("r-a", "read"), "scope": "src/a"}]})
    assert pre(root, request(workstream="w-a")) == ""
    # The one writing slot the user stated is taken; reads still fan out freely.
    roles_cycle = ("investigator", "reasoning-specialist", "reviewer")
    for index in range(12):
        role = roles_cycle[index % 3]
        assert pre(root, request(role, message=f"Non-writing work {index}")) == "", role
    # Naming a workstream, even the live write one, is allowed for a non-writing role.
    assert pre(root, request("reviewer", workstream="w-a", message="Review slice A")) == ""
    assert pre(root, request("investigator", workstream="r-a", message="Read slice A")) == ""
    assert len(reservations(root)) == 15
    # A writing role still needs a declared write workstream.
    assert denied(pre(root, request("focused-implementer", message="Unnamed write")), "THALIRIS_PARALLEL_WORKSTREAM_REQUIRED")
    assert denied(pre(root, request(workstream="r-a", message="Write on a read stream")),
                  "THALIRIS_PARALLEL_WRITE_WORKSTREAM_REQUIRED")
    assert not lifecycle._parallel_executor_role("verifier") and not lifecycle._parallel_executor_role("reviewer")
    assert lifecycle._parallel_executor_role("curator") and lifecycle._parallel_executor_role("implementer")


def test_uncapped_overlapping_read_contract_admitted_by_core(tmp_path, monkeypatch):
    """Core admits no budget, no worktree, overlapping reads and workstream-free fan-out; overlapping writes are refused at admission."""
    policy = {"enabled": True, "workstreams": [
        {"id": "w-a", "domain": "one", "scope": "src/a", "worktree": None, "mode": "write"},
        {"id": "w-b", "domain": "two", "scope": "src/b", "worktree": None, "mode": "write"},
        {"id": "r-all", "domain": "one", "scope": "src", "worktree": None, "mode": "read"},
        {"id": "r-inner", "domain": "one", "scope": "src/a/inner", "worktree": None, "mode": "read"},
    ]}
    root = _task(tmp_path, monkeypatch, policy)
    for index in range(20):
        assert pre(root, request("investigator", message=f"Uncapped read {index}")) == ""
    assert pre(root, request(workstream="w-a")) == "" and pre(root, request(workstream="w-b")) == ""
    assert pre(root, request("investigator", workstream="r-all", message="Read everything")) == ""
    assert pre(root, request("investigator", workstream="r-inner", message="Read inner")) == ""
    # Write-write overlap, whatever the domain label, is refused by Core when the contract is established.
    with pytest.raises(core.ThalirisError) as refused:
        _task(tmp_path / "overlap", monkeypatch, {"enabled": True, "workstreams": [
            {"id": "w-a", "domain": "one", "scope": "src/a", "worktree": None, "mode": "write"},
            {"id": "w-c", "domain": "three", "scope": "src/a/inner", "worktree": None, "mode": "write"}]})
    assert refused.value.code == "TASK_AUTHORITY_CONTRACT_REQUIRED"


# pd-F1: workstream-less parallel dispatches are enforced read-only, whatever the role.

def _write_attempts(child: dict, scope: str) -> list[dict]:
    return [
        {**child, "tool_name": "apply_patch", "tool_input": {"input": f"*** Begin Patch\n*** Add File: {scope}/x.py\n+x\n*** End Patch"}},
        {**child, "tool_name": "Bash", "tool_input": {"command": f"Set-Content {scope}/x.py value"}},
        {**child, "tool_name": "Bash", "tool_input": {"command": f"echo x > {scope}/y.py"}},
    ]


def test_workstream_less_parallel_read_roles_are_refused_writes_into_a_live_writer_scope(parallel):
    root = parallel
    writer_request = request("focused-implementer", workstream="ws-a")
    assert pre(root, writer_request) == ""
    writer = bind(root, writer_request, "focused-implementer", "writer-a")
    readers = {}
    for role in ("investigator", "reasoning-specialist"):
        value = request(role, message=f"Read slice A as {role}")
        assert pre(root, value) == ""
        assert next(item for item in reservations(root) if item["role"] == role)["parallel_readonly"] is True
        readers[role] = bind(root, value, role, f"reader-{role}")
        assert child_record(root, f"reader-{role}")["parallel_readonly"] is True
    assert child_record(root, "writer-a").get("parallel_readonly") is None
    for role, child in readers.items():
        for attempt in _write_attempts(child, "src/ws-a"):
            output = lifecycle.handle_hook(root, "PreToolUse", attempt, lifecycle.MANAGED_HOOK_ABI)
            assert denied(output, "THALIRIS_READONLY_ACTOR"), (role, attempt["tool_input"], output)
        # Reads stay available.
        read = {**child, "tool_name": "Bash", "tool_input": {"command": "git status"}}
        assert not denied(lifecycle.handle_hook(root, "PreToolUse", read, lifecycle.MANAGED_HOOK_ABI), "THALIRIS_")
    # The declared writer keeps its write grant in its own scope.
    for attempt in _write_attempts(writer, "src/ws-a"):
        output = lifecycle.handle_hook(root, "PreToolUse", attempt, lifecycle.MANAGED_HOOK_ABI)
        assert not denied(output, "THALIRIS_READONLY_ACTOR"), output
    # Read-only dispatches are never counted as live writers.
    assert lifecycle._live_parallel_writes(ledger(root)) == ["ws-a"]


def test_parallel_write_classification_follows_the_handoff(tmp_path, monkeypatch):
    root = _task(tmp_path, monkeypatch, {"enabled": True, "budget": 1, "workstreams": [
        _write("w-a", "src/a"), _write("w-b", "src/b"), {**_stream("r-a", "read"), "scope": "src/a"}]})
    # An investigator with a declared write workstream is a writer: it counts and contends.
    assert pre(root, request("investigator", workstream="w-a", message="Write as investigator")) == ""
    assert "parallel_readonly" not in reservations(root)[0]
    assert denied(pre(root, request(workstream="w-b")), "THALIRIS_PARALLEL_DISPATCH_BUDGET")
    # With a read workstream it is admitted read-only and is never counted.
    assert pre(root, request("reasoning-specialist", workstream="r-a", message="Reason over A")) == ""
    assert reservations(root)[-1]["parallel_readonly"] is True
    # Executors still need a declared write workstream.
    for executor in ("implementer", "focused-implementer", "curator"):
        assert denied(pre(root, request(executor, message=f"Unnamed {executor}")), "THALIRIS_PARALLEL_WORKSTREAM_REQUIRED")
        assert denied(pre(root, request(executor, workstream="r-a", message=f"Read stream {executor}")),
                      "THALIRIS_PARALLEL_WRITE_WORKSTREAM_REQUIRED")
    # Non-writing roles get no flag: their binding is already readonly.
    assert pre(root, request("reviewer", message="Review")) == ""
    assert "parallel_readonly" not in reservations(root)[-1]
    assert not lifecycle._parallel_executor_role("investigator") and not lifecycle._parallel_executor_role("reviewer")
    assert lifecycle._parallel_executor_role("curator") and lifecycle._parallel_executor_role("implementer")


def test_a_legacy_unflagged_investigator_record_still_counts_as_a_writer(parallel):
    root = parallel
    assert pre(root, request("investigator", message="Legacy read")) == ""
    value = ledger(root)
    del value["pending_authorized_spawn"]["parallel_readonly"]
    lifecycle._write_capture(lifecycle._lifecycle_path(root, task_id(root)), value)
    # Written before the flag existed: it could write, so it blocks comparison (fail closed).
    output = pre(root, request(workstream="ws-a"))
    assert denied(output, "THALIRIS_PARALLEL_DOMAIN_OVERLAP") and "undeclared" in output


# pd-F2: overlap uses Core's canonical scopes.

@pytest.mark.parametrize(("first", "second"), [
    ("src/Mod", "src/mod"),
    ("src/MOD/inner", "src/mod"),
    ("src/caf\u00e9", "src/cafe\u0301"),
    ("/src/mod/", "src/mod"),
    ("./src//mod", "src\\mod\\sub"),
    ("SRC/Stra\u00dfe", "src/strasse"),
])
def test_overlap_is_case_unicode_and_separator_insensitive(parallel, monkeypatch, first, second):
    root = parallel
    _policy(monkeypatch, _write("w-1", first), _write("w-2", second), _write("w-3", "src/other"))
    assert pre(root, request(workstream="w-1")) == ""
    output = pre(root, request(workstream="w-2"))
    assert denied(output, "THALIRIS_PARALLEL_DOMAIN_OVERLAP"), output
    assert pre(root, request(workstream="w-3")) == ""


def test_scope_core_rejects_is_unusable_and_cannot_run_beside_a_writer(parallel, monkeypatch):
    root = parallel
    _policy(monkeypatch, _write("w-1", "src/mod"), _write("w-drive", "C:/repo/src/mod"), _write("w-glob", "src/*"))
    assert pre(root, request(workstream="w-1")) == ""
    for other in ("w-drive", "w-glob"):
        output = pre(root, request(workstream=other))
        assert denied(output, "THALIRIS_PARALLEL_DOMAIN_OVERLAP") and "no declared scope" in output


# pd-F3: a stored parallel contract Core now refuses fails closed for writers.

def test_pre_ca46611_overlapping_contract_refuses_writers_and_admits_reads_readonly(tmp_path, monkeypatch):
    root = _task(tmp_path, monkeypatch, None)
    # Cross-domain overlapping write scopes: admitted before ca46611, refused now.
    legacy = {"enabled": True, "budget": 2, "workstreams": [
        {"id": "w-a", "domain": "one", "scope": "src/a", "worktree": None, "mode": "write"},
        {"id": "w-c", "domain": "three", "scope": "src/a/inner", "worktree": None, "mode": "write"}]}
    from thaliris import authority as core_authority
    with pytest.raises(ValueError):
        core_authority._validate_parallel_dispatch(legacy)
    real_check, real_read = task_authority.check, task_authority.read

    def stale(function):
        def read(root_):
            record = function(root_)
            if record is not None:
                record = {**record, "contract": {**record["contract"], "parallel_dispatch": legacy}}
            return record
        return read
    monkeypatch.setattr(task_authority, "check", stale(real_check))
    monkeypatch.setattr(task_authority, "read", stale(real_read))
    assert lifecycle._parallel_dispatch_policy(root, OWNER) is None
    assert lifecycle._parallel_contract_invalid(root, OWNER)
    for executor in ("implementer", "focused-implementer", "curator"):
        for stream in (None, "w-a"):
            output = pre(root, request(executor, workstream=stream, message=f"{executor} {stream}"))
            assert denied(output, "THALIRIS_PARALLEL_CONTRACT_INVALID") and "Re-admit" in output, output
    # Read-type spawns proceed, enforced read-only; the legacy single-reservation rule still holds.
    value = request("investigator", workstream="w-a", message="Read under a stale contract")
    assert pre(root, value) == ""
    pending = reservations(root)
    assert len(pending) == 1 and pending[0]["parallel_readonly"] is True and "workstream_id" not in pending[0]
    assert denied(pre(root, request("reasoning-specialist", message="Second")), "THALIRIS_UNBOUND_DISPATCH_PENDING")
    child = bind(root, value, "investigator", "stale-reader")
    for attempt in _write_attempts(child, "src/a"):
        assert denied(lifecycle.handle_hook(root, "PreToolUse", attempt, lifecycle.MANAGED_HOOK_ABI), "THALIRIS_READONLY_ACTOR")
    assert pre(root, request("reviewer", message="Review under a stale contract")) == ""
    # Another session is not the owner: the stale contract is not its evidence.
    assert not lifecycle._parallel_contract_invalid(root, hashlib.sha256(b"other").hexdigest())


# N1: the deny-only write heuristic recognizes the wider command families.

_WRITE_FAMILIES = {
    "file-ops": ["mv a.py b.py", "cp a.py b.py", "rm -rf build", "rmdir build", "touch x.py", "ln -s a b"],
    "in-place-and-tee": ["sed -i 's/a/b/' x.py", "sed -i.bak s/a/b/ x.py", "perl -pi -e 's/a/b/' x.py",
                         "cat x.py | tee y.py"],
    "powershell": ["Get-Date | Out-File x.txt", "Rename-Item a b", "Clear-Content x.txt", "ni x.txt", "ri x.txt",
                   "mi a b", "cpi a b", "Set-Content x v", "Add-Content x v"],
    "dotnet": ["[IO.File]::WriteAllText('x','y')", "[System.IO.File]::AppendAllText('x','y')",
               "[IO.File]::Delete('x')", "[IO.Directory]::CreateDirectory('d')"],
    "python-node-one-liners": [
        "python -c \"open('x','w').write('y')\"", "python3 -c \"open('x', mode='a')\"",
        "python -c \"from pathlib import Path; Path('x').write_text('y')\"",
        "python -c \"Path('x').write_bytes(b'y')\"", "python -c \"import shutil; shutil.rmtree('d')\"",
        "python -c \"import os; os.remove('x')\"", "python -c \"import os; os.rename('a','b')\"",
        "python -c \"import os; os.makedirs('d')\"",
        "node -e \"require('fs').writeFileSync('x','y')\"", "node -e \"fs.rmSync('x')\"",
        "node -e \"fs.unlinkSync('x')\"", "node -e \"fs.renameSync('a','b')\"", "node -e \"fs.mkdirSync('d')\"",
        "node -e \"fs.copyFileSync('a','b')\""],
    "git-working-tree": ["git add .", "git stash", "git stash push -m x", "git restore x.py", "git clean -fd",
                         "git rm x.py", "git mv a b", "git merge other", "git rebase main",
                         "git cherry-pick abc", "git revert abc", "git am p.patch", "git pull",
                         "git switch other", "git -c safe.directory=* add ."],
    "git-refs": ["git tag v1", "git tag -d v1", "git branch -d old", "git branch -D old", "git branch -m a b",
                 "git branch newbranch", "git worktree add ../w"],
    "package-installs": ["npm install", "npm i left-pad", "pnpm add x", "yarn add x", "pip install x",
                         "uv add x", "uv sync", "npm ci", "pnpm remove x", "python -m pip install x",
                         "uv pip install x"],
    "wrapped-and-compound": ["cd src && rm x.py", "bash -lc 'rm x.py'", "powershell -Command \"Remove-Item x\"",
                             "cmd /c del x.py", "find . -name x -delete", "ls | xargs rm", "sudo rm x.py"],
    "argv-lists": [["rm", "x.py"], ["git", "add", "."], ["bash", "-lc", "rm x.py"], ["npm", "install"],
                   ["python", "-c", "open('x','w')"], ["pwsh", "-Command", "Get-Date | Out-File x"]],
}
_READ_COMMANDS = [
    "git status", "git log --oneline", "git diff", "git show HEAD", "git stash list", "git stash show",
    "git branch", "git branch -a", "git branch --list 'feat/*'", "git tag", "git tag -l", "git worktree list",
    "git -C repo status", "cat README.md", "ls -la", "rg rm src", "rg \"rm -rf\" docs",
    "grep -r 'git add' .", "Get-Content x.txt", "Get-ChildItem", "python -c \"print(1)\"",
    "python -c \"print(open('x').read())\"", "node -e \"console.log(1)\"", "npm test", "pytest", "pytest -q tests/",
    "pip list", "uv run pytest", "sed -n '1,5p' x.py", ["git", "status"], ["cat", "README.md"],
]


def _readonly_attempts(child: dict, command) -> dict:
    return {**child, "tool_name": "Bash", "tool_input": {"command": command}}


@pytest.mark.parametrize("family", sorted(_WRITE_FAMILIES))
def test_widened_write_detection_is_denied_for_readonly_actors_and_parallel_readers(parallel, family):
    root = parallel
    value = request("investigator", message="Read slice A")
    assert pre(root, value) == ""
    reader = bind(root, value, "investigator", "wide-reader")
    assert child_record(root, "wide-reader")["parallel_readonly"] is True
    for command in _WRITE_FAMILIES[family]:
        for actor in (reader, {"cwd": str(root), "session_id": "readonly-session", "readonly": True}):
            output = lifecycle.handle_hook(root, "PreToolUse", _readonly_attempts(actor, command),
                                           lifecycle.MANAGED_HOOK_ABI)
            assert denied(output, "THALIRIS_READONLY_ACTOR"), (command, output)


def test_widened_write_detection_leaves_read_commands_available(parallel):
    root = parallel
    value = request("investigator", message="Read slice B")
    assert pre(root, value) == ""
    reader = bind(root, value, "investigator", "wide-reader-2")
    for command in _READ_COMMANDS:
        for actor in (reader, {"cwd": str(root), "session_id": "readonly-session", "readonly": True}):
            output = lifecycle.handle_hook(root, "PreToolUse", _readonly_attempts(actor, command),
                                           lifecycle.MANAGED_HOOK_ABI)
            assert not denied(output, "THALIRIS_READONLY_ACTOR"), (command, output)


def test_widened_write_detection_does_not_refuse_the_declared_writer(parallel):
    root = parallel
    value = request("focused-implementer", workstream="ws-a")
    assert pre(root, value) == ""
    writer = bind(root, value, "focused-implementer", "wide-writer")
    for command in ("git add .", "npm install", "mv a.py b.py", "sed -i s/a/b/ x.py", "rm x.py"):
        output = lifecycle.handle_hook(root, "PreToolUse", _readonly_attempts(writer, command),
                                       lifecycle.MANAGED_HOOK_ABI)
        assert not denied(output, "THALIRIS_READONLY_ACTOR"), (command, output)


def test_readonly_actor_can_still_record_an_observation_that_mentions_write_words(parallel):
    root = parallel
    inline = json.dumps({"text": "git add and rm -rf and npm install were all refused for readers"})
    command = f"thaliris --root \"{root}\" task-observe --role investigator --observation-json '{inline}'"
    assert lifecycle._context_operation({"tool_input": {"command": command}}) == "task-observe"
    for actor in ({"readonly": True}, ):
        output = lifecycle.handle_hook(root, "PreToolUse", {"cwd": str(root), "session_id": "ro", "tool_name": "Bash",
                                                            "tool_input": {"command": command}, **actor})
        assert not denied(output, "THALIRIS_READONLY_ACTOR"), output
    assert lifecycle._obvious_write_attempt({"tool_name": "Bash", "tool_input": {"command": command}}, broad=True) is False
    chained = command + "; rm -rf x"
    assert lifecycle._obvious_write_attempt({"tool_name": "Bash", "tool_input": {"command": chained}}, broad=True) is True
