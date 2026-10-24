"""Codex delivery of the Core Project Identity plane.

Core owns identity semantics; these tests cover the Adapter boundary only:
CLI wiring and Controller-only gating, Hook classification, one-line summary
delivery to the Controller, absence-neutral outputs and no child injection.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from thaliris import core, identity
from thaliris_codex import cli, codex_adapter, codex_bootstrap, controller_instructions, lifecycle, project_identity, roles, task_authority

TEXT_V1 = """# Example project identity

## ID-1 Identity
We build a reliable ledger.

## INV-1: Never lose recorded data
Recorded data survives every crash.

## INV-2 Explicit authority
Only the owner changes direction.
"""
TEXT_V2 = TEXT_V1 + "\n## NG-1 Non-goal: hosting\nWe do not host.\n"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("THALIRIS_HOME", str(tmp_path / "thaliris-home"))
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "host"))
    monkeypatch.setattr(task_authority, "directory", lambda: tmp_path / "external")
    observed = lifecycle.managed_executable_health()
    monkeypatch.setattr(lifecycle, "managed_executable_health", lambda: {**observed, "canonical_executable_available": "YES"})
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _: "BLOCKING_WAIT")
    agents = Path(os.environ["CODEX_HOME"]) / "agents"
    for name, (model, effort, role) in roles.agent_profiles().items():
        profile = agents / name
        if not profile.exists():
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_bytes(codex_adapter._agent_profile(name[:-5], role, model, effort))
    codex_adapter.init(root)
    return root


def start(root, mode="delegated"):
    filename = root / "authority.json"
    filename.write_text(json.dumps({"human_instruction": "Work on the example", "boundary": "Example module",
        "invariants": "Keep public behavior", "acceptance": "Focused checks pass", "execution_mode": mode}))
    result = codex_adapter.task_start(root, "Work on the example", None, None, authority_contract=str(filename), session_id="first")
    assert result["ok"], result
    return result


def payload(root, command, session="first", **actor):
    return {"cwd": str(root), "session_id": session, "tool_name": "Bash",
            "tool_input": {"command": command}, **actor}


def child_call(root, command, role="implementer"):
    """Role-bound child PreToolUse decision, as a native child session would present it."""
    return lifecycle._child_pre_tool_output(root, {
        "agent_type": f"thaliris-{role}", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(root)})


def run(capsys, root, *args):
    code = cli.main(["--root", str(root), *args])
    out = capsys.readouterr().out
    return code, json.loads(out)


def packet(root, name, value):
    path = root / name
    path.write_text(json.dumps(value))
    return str(path)


def amend_input(base_version, base_sha256, text, **extra):
    return {"base_version": base_version, "base_sha256": base_sha256, "text": text,
            "summary": f"move to v{base_version + 1}", "rationale": "the owner decided",
            "decision": {"decided_by": "project owner", "human_instruction": "Please record this identity."}, **extra}


def mutate(capsys, root, task_id, command, name, value, revision=1, role="controller"):
    return run(capsys, root, "--task-id", task_id, command, "--role", role, "--base-revision", str(revision),
               "--input", packet(root, name, value))


def test_absent_identity_leaves_every_delivery_output_unchanged(workspace, capsys, monkeypatch):
    task_id = start(workspace)["task_id"]
    code, status = run(capsys, workspace, "identity-status")
    assert code == 0 and status["ok"] and status["state"] == "ABSENT" and status["summary"] is None
    code, packet_out = run(capsys, workspace, "--task-id", task_id, "task-status")
    assert code == 0 and "Project Identity" not in packet_out
    monkeypatch.setattr(codex_bootstrap, "_trusted_executable", lambda: ["thaliris"])
    assert project_identity.SUMMARY_FIELD not in codex_bootstrap.bootstrap(workspace)
    assert not (workspace / ".project-identity").exists()
    code, refused = run(capsys, workspace, "identity-get")
    assert code == 2 and not refused["ok"]


def test_controller_establishes_reads_challenges_relates_and_amends(workspace, capsys, monkeypatch):
    task_id = start(workspace)["task_id"]
    monkeypatch.setattr(codex_bootstrap, "_trusted_executable", lambda: ["thaliris"])
    code, amended = mutate(capsys, workspace, task_id, "identity-amend", "v1.json", amend_input(0, None, TEXT_V1))
    assert code == 0 and amended["ok"] and amended["version"] == 1 and amended["amendment"] == "A-0001"
    # Identity is a separate plane: neither the task revision nor the checked Authority baseline moves.
    assert core._load_state(workspace)["revision"] == 1
    assert task_authority.check(workspace)["contract"]["boundary"] == "Example module"
    assert ".project-identity" not in "".join(task_authority.SECURITY_PATHS)

    code, status = run(capsys, workspace, "identity-status")
    assert code == 0 and status["state"] == "CURRENT" and status["version"] == 1
    assert {item["id"] for item in status["items"]} == {"ID-1", "INV-1", "INV-2"}
    summary = identity.identity_summary(workspace)
    assert summary and status["summary"] == summary

    # The summary reaches the Controller at admission/continuation and in task-status.
    code, routed = run(capsys, workspace, "--task-id", task_id, "task-status")
    assert code == 0 and routed["Project Identity"] == summary
    assert codex_bootstrap.bootstrap(workspace)[project_identity.SUMMARY_FIELD] == summary

    code, current = run(capsys, workspace, "identity-get")
    assert code == 0 and current["text"] == TEXT_V1
    code, selected = run(capsys, workspace, "identity-get", "--item", "INV-1", "--item", "INV-2")
    assert code == 0 and [item["id"] for item in selected["items"]] == ["INV-1", "INV-2"]

    code, challenged = mutate(capsys, workspace, task_id, "identity-challenge", "ch.json", {
        "targets": ["identity:INV-1"], "summary": "Crash safety is too strong", "text": "Evidence says it cannot hold."})
    assert code == 0 and challenged["status"] == "open"
    challenge = challenged["challenge"]
    code, fetched = run(capsys, workspace, "identity-get", "--challenge", challenge)
    assert code == 0 and fetched["status"] == "open"

    (workspace / "design.md").write_text("design\n")
    code, related = mutate(capsys, workspace, task_id, "identity-relate", "rel.json", {
        "add": [{"from": "path:design.md", "rel": "serves", "to": "identity:INV-1", "note": "design serves the invariant"}]})
    assert code == 0 and len(related["added"]) == 1
    code, traced = run(capsys, workspace, "identity-trace", "identity:INV-1", "--direction", "down", "--depth", "2")
    assert code == 0 and any(edge["from"] == "path:design.md" and edge["to"] == "identity:INV-1" for edge in traced["edges"])
    assert "Registered relations only" in traced["notice"]

    code, status = run(capsys, workspace, "identity-status")
    assert status["open_challenges_total"] == 1
    code, v2 = mutate(capsys, workspace, task_id, "identity-amend", "v2.json", amend_input(
        1, status["on_disk_sha256"], TEXT_V2, resolves=[challenge], why_not_lower="Lower-level repair cannot satisfy INV-1."))
    assert code == 0 and v2["version"] == 2 and v2["challenges_resolved"]
    code, resolved = run(capsys, workspace, "identity-get", "--challenge", challenge)
    assert resolved["status"] == "amended"
    code, old = run(capsys, workspace, "identity-get", "--version", "1")
    assert old["text"] == TEXT_V1
    core.select_task(workspace, task_id)
    assert core._load_state(workspace)["revision"] == 1
    assert task_authority.check(workspace)["status"] == "ACTIVE"
    # An ordinary checked task operation still succeeds at the unchanged revision.
    code, updated = run(capsys, workspace, "--task-id", task_id, "task-update", "--role", "controller",
                        "--base-revision", "1", "--input", packet(workspace, "update.json", {"active_work": ["after identity"]}))
    assert code == 0 and updated["ok"]


@pytest.mark.parametrize("command,value", [
    ("identity-amend", amend_input(0, None, TEXT_V1)),
    ("identity-challenge", {"targets": ["identity"], "summary": "s", "text": "t"}),
    ("identity-relate", {"add": [{"from": "commit:abcdef1", "rel": "serves", "to": "identity"}]}),
])
@pytest.mark.parametrize("role", ["implementer", "reviewer", "curator", "investigator"])
def test_non_controller_roles_are_refused_before_any_identity_write(workspace, capsys, command, value, role):
    task_id = start(workspace)["task_id"]
    code, refused = mutate(capsys, workspace, task_id, command, "input.json", value, role=role)
    assert code == 2 and not refused["ok"] and "only Controller" in refused["error"]
    assert not (workspace / ".project-identity").exists()


def test_mutations_require_a_selected_task(workspace, capsys):
    start(workspace)
    code, refused = run(capsys, workspace, "identity-amend", "--role", "controller", "--base-revision", "1",
                        "--input", packet(workspace, "v1.json", amend_input(0, None, TEXT_V1)))
    assert code == 2 and "task-id" in refused["error"]
    assert not (workspace / ".project-identity").exists()


def test_hooks_classify_mutations_as_controller_state_and_reads_as_reads(workspace):
    # Role-session classification applies to a bound child before and without a Controller anchor.
    for command in ("thaliris identity-amend --role controller --base-revision 1 --input v1.json",
                    "thaliris identity-challenge --role controller --base-revision 1 --input c.json",
                    "thaliris identity-relate --role controller --base-revision 1 --input r.json"):
        for role in ("implementer", "reviewer", "curator"):
            assert "THALIRIS_ROLE_SESSION_CONTROL_STATE_MUTATION" in child_call(workspace, command, role), (role, command)
    for command in ("thaliris identity-status", "thaliris identity-get --item INV-1", "thaliris identity-trace identity"):
        assert "deny" not in child_call(workspace, command), command
    start(workspace)
    for command in ("thaliris identity-amend --role controller --base-revision 1 --input v1.json",
                    "thaliris identity-challenge --role controller --base-revision 1 --input c.json",
                    "thaliris identity-relate --role controller --base-revision 1 --input r.json",
                    "thaliris identity-status", "thaliris identity-get --item INV-1", "thaliris identity-trace identity"):
        assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command), lifecycle.MANAGED_HOOK_ABI) == "", command
    for command in ("thaliris identity-amend --role controller --base-revision 1 --input v1.json",
                    "thaliris identity-challenge --role controller --base-revision 1 --input c.json",
                    "thaliris identity-relate --role controller --base-revision 1 --input r.json"):
        output = lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, agent_id="child", agent_type="thaliris-implementer"), lifecycle.MANAGED_HOOK_ABI)
        assert "deny" in output, command


def test_identity_record_files_get_the_obvious_path_guard_but_stay_readable(workspace):
    targets = (".project-identity/IDENTITY.md", ".project-identity/ledger.json", ".project-identity/versions/v0001.md",
               ".project-identity\\amendments\\A-0001.md", ".project-identity/challenges/x.json", ".project-identity/relations/x.json")
    for target in targets:
        assert "THALIRIS_ROLE_SESSION_CONTROL_STATE_MUTATION" in child_call(workspace, f"Set-Content {target} 'x'"), target
    read = "cat .project-identity/IDENTITY.md"
    assert "deny" not in child_call(workspace, read)
    start(workspace)
    for target in targets:
        assert "THALIRIS_CONTROL_STATE_DIRECT_WRITE" in lifecycle.handle_hook(
            workspace, "PreToolUse", payload(workspace, f"Set-Content {target} 'x'"), lifecycle.MANAGED_HOOK_ABI), target
    assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, read), lifecycle.MANAGED_HOOK_ABI) == ""
    assert lifecycle._control_state_target(payload(workspace, read)) == ".project-identity/IDENTITY.md"


def test_children_receive_no_identity_text(workspace, capsys):
    task_id = start(workspace)["task_id"]
    mutate(capsys, workspace, task_id, "identity-amend", "v1.json", amend_input(0, None, TEXT_V1))
    child = {"session_id": "first", "turn_id": "t", "agent_id": "child", "agent_type": "thaliris-implementer", "cwd": str(workspace)}
    assert lifecycle.handle_hook(workspace, "SubagentStart", child) == ""
    assert identity.identity_summary(workspace) is not None


def test_identity_guidance_is_resident_and_expresses_the_layered_procedure():
    from tests.test_prompt_contract import concepts
    assert "identity" in controller_instructions.SECTIONS
    assert "identity" in controller_instructions.RESIDENT_SECTIONS
    section = controller_instructions.render(codex_bootstrap._controller_guidance_runner(), section="identity")
    assert section.strip() in codex_bootstrap.controller_guidance()
    concepts(section,
             ("task authority", "memory", "milestones", "evidence"),
             ("legacy", "agent-memory", "labels", "confer", "no identity authority"),
             ("most projects start with no identity", "nothing is blocked", "current task always comes first"),
             ("identity-note", "verbatim", "identity_offer", "identity-suggest", "no answer means no", "never write a draft"),
             ("directional", "architectural", "replanning", "cross-layer", "ordinary local repair"),
             ("locate", "trace up", "repair", "lowest sufficient layer", "challenge up", "amend", "human owner's explicit decision"),
             ("never by editing", "project-identity"),
             ("registered dependents", "nothing propagates automatically"),
             ("registered relations only", "absence of a relation is not independence"),
             ("amendment is not memory promotion",),
             ("never rewrites a running task's frozen contract",),
             ("no identity text is injected into children", "quote selected item ids and text", "bind the child's work"),
             ("identity-status", "identity-get", "identity-trace", "identity-amend", "identity-challenge", "identity-relate"))


NOTE = {"quote": "This project exists to keep our ledger honest.", "kind": "purpose"}


def note(capsys, root, value=None, role="controller", *extra):
    path = packet(root, "note.json", value if value is not None else NOTE)
    return run(capsys, root, "identity-note", "--role", role, "--input", path, *extra)


def test_controller_notes_lists_and_retracts_without_a_task(workspace, capsys):
    assert core.selected_task(workspace) is None
    code, added = note(capsys, workspace)
    assert code == 0 and added["ok"], added
    code, listed = run(capsys, workspace, "identity-note", "--role", "controller", "--list")
    assert code == 0 and listed["ok"] and "ledger honest" in json.dumps(listed)
    code, retracted = note(capsys, workspace, {"retract": "N-0001", "reason": "wrong recording"})
    assert code == 0 and retracted["ok"], retracted
    code, listed = run(capsys, workspace, "identity-note", "--role", "controller", "--list")
    assert "ledger honest" not in json.dumps(listed)
    code, listed = run(capsys, workspace, "identity-note", "--role", "controller", "--list", "--include-retracted")
    assert "ledger honest" in json.dumps(listed)
    code, status = run(capsys, workspace, "identity-status")
    assert code == 0 and status["state"] == "ABSENT" and status["basis"]["retracted"] == 1


def test_inline_json_note_and_missing_source(workspace, capsys):
    code, added = run(capsys, workspace, "identity-note", "--role", "controller", "--json", json.dumps(NOTE))
    assert code == 0 and added["ok"], added
    code, refused = run(capsys, workspace, "identity-note", "--role", "controller")
    assert code != 0 and not refused["ok"]


@pytest.mark.parametrize("role", ["implementer", "reviewer", "curator", "investigator"])
def test_children_cannot_note_or_suggest_by_cli_or_hook(workspace, capsys, role):
    code, refused = note(capsys, workspace, role=role)
    assert code == 2 and "only Controller" in refused["error"]
    code, refused = run(capsys, workspace, "identity-suggest", "--role", role, "--off", "--scope", "project")
    assert code == 2 and "only Controller" in refused["error"]
    assert run(capsys, workspace, "identity-note", "--role", "controller", "--list")[1]["notes"] == []
    for command in ("thaliris identity-note --role controller --list",
                    "thaliris identity-suggest --role controller --off --scope project"):
        assert "THALIRIS_ROLE_SESSION_CONTROL_STATE_MUTATION" in child_call(workspace, command, role), command


def test_controller_hooks_allow_formation_commands(workspace):
    start(workspace)
    for command in ("thaliris identity-note --role controller --list",
                    "thaliris identity-suggest --role controller --off --scope project"):
        assert lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command), lifecycle.MANAGED_HOOK_ABI) == "", command
        assert "deny" in lifecycle.handle_hook(workspace, "PreToolUse", payload(workspace, command, agent_id="child", agent_type="thaliris-implementer"), lifecycle.MANAGED_HOOK_ABI)


def test_suggest_scopes_and_session_key_passthrough(workspace, capsys):
    note(capsys, workspace)
    code, off = run(capsys, workspace, "identity-suggest", "--role", "controller", "--off", "--scope", "project")
    assert code == 0 and off["ok"], off
    code, status = run(capsys, workspace, "identity-status")
    assert status["suggestions"] == {"enabled": False, "source": "project"}
    # Session scope needs the native session key; Core refuses it without one.
    code, refused = run(capsys, workspace, "identity-suggest", "--role", "controller", "--on", "--scope", "session")
    assert code != 0 and not refused["ok"]
    code, on = run(capsys, workspace, "--session-id", "s-1", "identity-suggest", "--role", "controller", "--on", "--scope", "session")
    assert code == 0 and on["ok"], on
    assert run(capsys, workspace, "--session-id", "s-1", "identity-status")[1]["suggestions"] == {"enabled": True, "source": "session"}
    assert run(capsys, workspace, "--session-id", "s-2", "identity-status")[1]["suggestions"]["source"] == "project"
    for scope in ("workspace", "global"):
        assert run(capsys, workspace, "identity-suggest", "--role", "controller", "--clear", "--scope", scope)[0] == 0


def _close(capsys, root, task_id):
    return run(capsys, root, "--task-id", task_id, "task-close", "--base-revision", "1")


def test_close_carries_identity_offer_once_for_a_new_note(workspace, capsys):
    task_id = start(workspace)["task_id"]
    note(capsys, workspace)
    code, closed = _close(capsys, workspace, task_id)
    assert code == 0 and closed["ok"] and "1 user statement" in closed["identity_offer"] and "identity-suggest" in closed["identity_offer"]
    task_id = start(workspace)["task_id"]
    code, again = _close(capsys, workspace, task_id)
    assert code == 0 and "identity_offer" not in again
    note(capsys, workspace, {"quote": "We will never host user data."})
    task_id = start(workspace)["task_id"]
    assert "identity_offer" in _close(capsys, workspace, task_id)[1]


def test_close_has_no_offer_without_notes_or_when_off(workspace, capsys):
    task_id = start(workspace)["task_id"]
    assert "identity_offer" not in _close(capsys, workspace, task_id)[1]
    note(capsys, workspace)
    run(capsys, workspace, "identity-suggest", "--role", "controller", "--off", "--scope", "project")
    task_id = start(workspace)["task_id"]
    assert "identity_offer" not in _close(capsys, workspace, task_id)[1]


def test_session_scope_off_reaches_the_close_offer_without_a_flag(workspace, capsys):
    task_id = start(workspace)["task_id"]  # task-start records the Controller session "first"
    note(capsys, workspace)
    code, off = run(capsys, workspace, "--task-id", task_id, "identity-suggest", "--role", "controller", "--off", "--scope", "session")
    assert code == 0 and off["ok"], off
    assert run(capsys, workspace, "--task-id", task_id, "identity-status")[1]["suggestions"] == {"enabled": False, "source": "session"}
    code, closed = _close(capsys, workspace, task_id)
    assert code == 0 and closed["ok"] and "identity_offer" not in closed


@pytest.mark.parametrize("command", [
    "thaliris-core identity-offer", "thaliris-core identity-note --list", "thaliris-core identity-suggest --off --scope project",
    "python -m thaliris identity-offer"])
def test_children_are_refused_raw_core_identity_state_commands(workspace, command):
    start(workspace)
    assert "deny" in child_call(workspace, command)


def test_offer_failure_leaves_close_result_unchanged(workspace, capsys, monkeypatch):
    from thaliris import identity_basis
    def boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(identity_basis, "identity_offer", boom)
    task_id = start(workspace)["task_id"]
    code, closed = _close(capsys, workspace, task_id)
    assert code == 0 and closed["ok"] and "identity_offer" not in closed
