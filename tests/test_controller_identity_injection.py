"""Controller identity injection: piped stdin input, and cause-specific refusals.

Field evidence: after a Codex restart the Host kept the Thaliris hooks disabled
until their trust was re-recorded, so no PreToolUse hook attached
``--controller-session-id-hash``; an agent read the uncoded refusal as a lost
Controller association. Separately, ``'<json>' | & '<runner>' ... --input -``
was not recognized, so the identity was never injected.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from thaliris import core
from thaliris_codex import cli, codex_adapter, lifecycle
from tests.test_nested_scanner import active  # noqa: F401

OWNER = hashlib.sha256(b"root-session").hexdigest()
SELECTION = {"requirements": [{"id": "R1", "workchain_ref": "opaque"}], "next_dispatch": {"role": "investigator", "expected_agent_type": "thaliris-investigator",
                               "candidate": "C1", "requirement_refs": ["R1"]}}


def bash(command: str, *, shell: str | None = None, session: str = "root-session") -> dict:
    tool_input = {"command": command}
    if shell is not None:
        tool_input["shell"] = shell
    return {"session_id": session, "turn_id": "root-turn", "tool_name": "Bash", "tool_input": tool_input}


def pre(root: Path, payload: dict) -> str:
    return lifecycle.handle_hook(root, "PreToolUse", payload, lifecycle.MANAGED_HOOK_ABI)


def register_command(root: Path, *, feed: str = "'{\"requirements\":[]}' | ") -> str:
    task_id = core.task_show(root)["state"]["task_id"]
    return f"{feed}& 'thaliris' --task-id {task_id} task-evidence-register --role controller --base-revision 1 --input -"


def injected(output: str) -> str:
    value = json.loads(output)["hookSpecificOutput"]
    assert value["permissionDecision"] == "allow", value
    return value["updatedInput"]["command"]


# --- absent identity is not an ownership failure ------------------------

def test_absent_controller_hash_has_its_own_code_and_recovery(active, tmp_path):
    source = tmp_path / "selection.json"
    source.write_text(json.dumps(SELECTION), encoding="utf-8")
    revision = core.task_show(active)["state"]["revision"]
    with pytest.raises(core.ThalirisError) as absent:
        codex_adapter.task_evidence_register(active, "controller", revision, str(source), None)
    assert absent.value.code == "THALIRIS_CONTROLLER_IDENTITY_NOT_INJECTED"
    assert "PreToolUse hook did not attach the Controller identity" in str(absent.value)
    assert "restart Codex once" in absent.value.recovery and "standalone" in absent.value.recovery
    assert absent.value.details["controller_session_id_hash"] == "ABSENT"
    assert absent.value.details["host_hook_trust"]["status"] == "NOT_REGISTERED"
    # The ledger owner is still the original Controller.
    assert lifecycle.active_controller_owner(active, core.task_show(active)["state"]["task_id"]) == OWNER
    with pytest.raises(core.ThalirisError) as wrong:
        codex_adapter.task_evidence_register(active, "controller", revision, str(source), "0" * 64)
    assert wrong.value.code == "THALIRIS_CONTROLLER_NOT_OWNER"
    assert wrong.value.details == {"controller_session_id_hash": "PRESENT", "owner": "DIFFERENT"}
    # The owner still succeeds.
    result = codex_adapter.task_evidence_register(active, "controller", revision, str(source), OWNER)
    assert result["ok"] is not False


def test_controller_local_observation_distinguishes_absent_from_wrong(active, monkeypatch):
    body = json.dumps({"base_revision": core.task_show(active)["state"]["revision"], "summary": "fact"})
    with pytest.raises(core.ThalirisError) as absent:
        codex_adapter.task_observe(active, "controller", None, None, observation_json=body, controller_session_id_hash=None)
    assert absent.value.code == "THALIRIS_CONTROLLER_IDENTITY_NOT_INJECTED"
    monkeypatch.setattr(lifecycle, "_session_fenced", lambda root, actor: True)
    with pytest.raises(core.ThalirisError) as fenced:
        codex_adapter.task_observe(active, "controller", None, None, observation_json=body, controller_session_id_hash=OWNER)
    assert fenced.value.code == "THALIRIS_CONTROLLER_NOT_OWNER" and fenced.value.details["owner"] == "FENCED"


# --- hook trust diagnostics ---------------------------------------------

def _install_hooks(home: Path) -> None:
    merged, _, manual = codex_adapter.merge_host_hooks({"hooks": {}}, home, home / "thaliris.exe", "a" * 64, "b" * 64)
    assert not manual
    (home / "hooks.json").write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def test_hook_trust_state_reports_changed_hooks_and_missing_trust(tmp_path, monkeypatch):
    home = tmp_path / "host"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert codex_adapter.host_hook_trust_state()["status"] == "NOT_REGISTERED"
    _install_hooks(home)
    assert codex_adapter.host_hook_trust_state()["matches_installed_hooks"] == "UNKNOWN"
    keys = {f"{home / 'hooks.json'}:{event}:0:0": f"sha256:{event}" for event in lifecycle.HOOK_EVENTS}
    codex_adapter.write_hook_trust_record(home, keys)
    lines = ["[hooks.state]"] + [f'"{key.replace(chr(92), chr(92) * 2)}" = {{ trusted_hash = "{value}" }}' for key, value in keys.items()]
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert codex_adapter.host_hook_trust_state()["status"] == "MATCH"
    # Trust removed or replaced in config.toml.
    (home / "config.toml").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    assert codex_adapter.host_hook_trust_state()["status"] == "TRUST_CHANGED_OR_DISABLED"
    # hooks.json restored with different Thaliris entries than were trusted.
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    data = json.loads((home / "hooks.json").read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 30
    (home / "hooks.json").write_text(json.dumps(data), encoding="utf-8")
    state = codex_adapter.host_hook_trust_state()
    assert state["status"] == "HOOKS_CHANGED_SINCE_TRUST" and "restart Codex once" in state["recovery"]
    codex_adapter.remove_hook_trust_record(home)
    assert not (home / codex_adapter.HOOK_TRUST_RECORD_NAME).exists()


def test_task_status_and_doctor_surface_hook_trust(active):
    status = cli._task_status(active, suppress_protocol_notice=True)
    assert status["Task Authority"]["host_hook_trust"]["status"] == "NOT_REGISTERED"
    assert codex_adapter.doctor(active)["host_hook_trust"]["status"] == "NOT_REGISTERED"


# --- piped stdin input ---------------------------------------------------

def test_piped_literal_into_one_runner_call_receives_the_identity(active):
    command = injected(pre(active, bash(register_command(active), shell="powershell")))
    assert command.endswith(f"--input - --controller-session-id-hash {OWNER}")
    assert command.startswith("'{\"requirements\":[]}' | & 'thaliris'")
    # Bash form: a literal needs echo/printf (a bare word would run a program).
    task_id = core.task_show(active)["state"]["task_id"]
    bash_form = f"echo '{{}}' | thaliris --task-id {task_id} task-observe --role controller --input -"
    assert injected(pre(active, bash(bash_form, shell="bash"))).endswith(f"--controller-session-id-hash {OWNER}")
    assert lifecycle._context_operation(bash(register_command(active), shell="powershell")) == "task-evidence-register"


@pytest.mark.parametrize("command", [
    "Get-Content selection.json | & 'thaliris' {tail}",                       # producer is a command, not data
    "'{{}}' | & 'thaliris' {tail}; Remove-Item marker.txt",                  # second command
    "'{{}}' | & 'thaliris' {tail} | Out-File result.txt",                     # second pipe stage
    "'{{}}' | & 'thaliris' {tail} > result.txt",                              # redirection
    "& 'thaliris' task-status | & 'thaliris' {tail}",                         # another runner call feeds stdin
    "'{{}}' && & 'thaliris' {tail}",                                          # not a pipe
    "\"$env:SELECTION\" | & 'thaliris' {tail}",                               # expansion in the producer
])
def test_ambiguous_compound_runner_calls_are_refused_by_name(active, command):
    task_id = core.task_show(active)["state"]["task_id"]
    tail = f"--task-id {task_id} task-evidence-register --role controller --base-revision 1 --input -"
    output = pre(active, bash(command.format(tail=tail), shell="powershell"))
    decision = json.loads(output)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "THALIRIS_CONTROLLER_IDENTITY_NOT_INJECTED" in decision["permissionDecisionReason"]
    assert "standalone runner command" in decision["permissionDecisionReason"]
    assert "updatedInput" not in decision


def test_bare_literal_producer_is_not_data_in_bash(active):
    task_id = core.task_show(active)["state"]["task_id"]
    command = f"'{{}}' | thaliris --task-id {task_id} task-observe --role controller --input -"
    assert lifecycle._context_operation(bash(command, shell="bash")) is None
    assert "THALIRIS_CONTROLLER_IDENTITY_NOT_INJECTED" in pre(active, bash(command, shell="bash"))


def test_piped_host_maintenance_is_never_recognized():
    command = "'{}' | & 'thaliris' codex-install --maintenance-contract c.json"
    assert lifecycle._context_operation(bash(command, shell="powershell")) is None
