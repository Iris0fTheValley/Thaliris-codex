from __future__ import annotations
from tests.host_maintenance_test_support import authorized_host_install, authorized_host_uninstall, attest_prior_authorized_bytes

import tomllib

from tests.support.history import historical_blob

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import pytest

from thaliris import core
from thaliris_codex import cli, codex_adapter, controller_instructions, roles
from thaliris_codex import runtime_identity
from thaliris_codex.lifecycle import handle_hook, hook_spec
import thaliris_codex.lifecycle as lifecycle_module


@pytest.fixture(autouse=True)
def hypothetical_controller_contract(monkeypatch):
    """Synthetic lifecycle unit seam, not an observed Host actor guarantee.

    The current Host actor UNKNOWN cases live in test_drift_recovery.py without
    this seam. These legacy mechanics test a hypothetical certified Controller.
    """
    original = lifecycle_module._controller_actor_assurance
    monkeypatch.setattr(lifecycle_module, "_controller_actor_assurance", lambda payload:
                        "CONTROLLER" if original(payload) == "UNKNOWN" else original(payload))


def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    codex_adapter.init(tmp_path)
    return tmp_path


def test_project_init_does_not_re_attest_or_restart_for_host_hook_state(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    runtime = root / ".context" / "audit" / "stale-session" / "runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps({
        "managed_hook_spec_hash": "stale-hook-spec",
        "adapter_protocol_version": "stale-protocol",
    }), encoding="utf-8")
    monkeypatch.setattr(
        lifecycle_module,
        "managed_executable_health",
        lambda: {
            "canonical_executable_available": "YES",
            "canonical_executable_identity": "TEST_PINNED",
        },
    )

    result = codex_adapter.init(root)

    assert result["changed"] is False
    assert result["hook_definition_changed"] is False
    assert result["canonical_executable_available"] == "YES"
    assert result["hook_re_attestation_required"] is False
    assert result["session_restart_required"] is False
    assert result["hook_trust_required"] is False


def test_project_init_does_not_require_a_host_hook_executable_refresh(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    for name in (
        "THALIRIS_EXECUTABLE",
        "THALIRIS_EXECUTABLE_SHA256",
        "THALIRIS_CONTEXT_EXECUTABLE",
        "THALIRIS_CONTEXT_EXECUTABLE_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lifecycle_module.shutil, "which", lambda command: None)

    result = codex_adapter.init(root)

    assert result["changed"] is False
    assert result["canonical_executable_available"] == "NO"
    assert result["canonical_executable_identity"] == "UNAVAILABLE"
    assert "canonical_executable_unavailable" not in result["manual_action_required"]
    assert result["session_restart_required"] is False
    assert result["hook_trust_required"] is False


def test_uninitialized_task_start_reports_bootstrap_unknown_restart(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = codex_adapter.task_start(tmp_path, "bootstrap", None, None)
    assert result["status"] == "BOOTSTRAP_REQUIRED"
    assert result["bootstrap"]["session_restart_required"] == "UNKNOWN"
    assert result["bootstrap"]["same_session_task_start"] == "UNKNOWN"


def test_init_does_not_install_project_role_identities_or_durable_fence(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    first = codex_adapter.init(tmp_path)
    assert first["session_restart_required"] is False
    assert first["role_catalog_changed"] is False
    assert first["new_role_profile_files"] == []
    assert first["agent_profile_changed"] is False
    assert not (tmp_path / ".codex" / "agents").exists()
    assert (tmp_path / ".codex" / "thaliris.json").read_bytes() == b'{"format":"thaliris-project-activation-v1"}\n'
    assert not (tmp_path / ".codex" / "hooks.json").exists()
    assert not (tmp_path / ".context" / "audit" / "bootstrap-restart.json").exists()
    assert not (tmp_path / ".context" / "audit" / "role-catalog-change.json").exists()

    second = codex_adapter.init(tmp_path)
    assert second["changed"] is False
    assert second["session_restart_required"] is False
    assert not (tmp_path / ".context" / "audit" / "bootstrap-restart.json").exists()


def test_task_start_blocks_roles_added_after_current_session_start(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    codex_adapter.audit_hook(tmp_path, "SessionStart", {"session_id": "same-session", "source": "startup", "cwd": str(tmp_path)})
    init = codex_adapter.init(tmp_path)
    assert init["role_catalog_changed"] is False
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "thaliris-implementer.toml").write_bytes(
        codex_adapter._agent_profile("thaliris-implementer", "implementer", "gpt-6-luna", "xhigh")
    )
    digest = init["controller_bridge_sha256"]
    pre = {"session_id": "same-session", "turn_id": "turn", "tool_name": "Bash", "tool_input": {"command": f"thaliris task-start goal --controller-bridge-sha256 {digest}"}}
    rewritten = json.loads(codex_adapter.audit_hook(tmp_path, "PreToolUse", pre, lifecycle_module.MANAGED_HOOK_ABI))
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", rewritten["hookSpecificOutput"]["updatedInput"]["command"]).group(1)
    result = codex_adapter.task_start(tmp_path, "goal", None, None, token, digest)
    assert result["status"] == "NEW_ROLE_CATALOG_IDENTITY_NOT_ACTIVE"
    assert result["new_role_profile_files"] == [".codex/agents/thaliris-implementer.toml"]
    assert not (tmp_path / ".context" / "state.json").exists()


def test_session_start_records_project_and_host_file_snapshot_without_catalog_evidence(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    profile = tmp_path / ".codex" / "agents" / "thaliris-implementer.toml"
    profile.parent.mkdir(parents=True)
    profile.write_bytes(codex_adapter._agent_profile("thaliris-implementer", "implementer", "gpt-6-luna", "xhigh"))
    host_profile = host_home / "agents" / "thaliris-investigator.toml"
    host_profile.parent.mkdir(parents=True)
    host_profile.write_bytes(codex_adapter._agent_profile("thaliris-investigator", "investigator", "gpt-6-luna", "xhigh"))
    codex_adapter.audit_hook(tmp_path, "SessionStart", {"session_id": "snapshot-session", "source": "startup", "cwd": str(tmp_path)})
    session_hash = hashlib.sha256(b"snapshot-session").hexdigest()
    runtime = json.loads((tmp_path / ".context" / "audit" / session_hash[:24] / "runtime.json").read_text(encoding="utf-8"))
    assert runtime["profile_files_present_at_session_start"] == {
        "configuration_sha256": {
            str(tmp_path / ".codex" / "config.toml"): "ABSENT",
            str(host_home.resolve() / "config.toml"): "ABSENT",
        },
        "project": {"directory": ".codex/agents", "files": ["thaliris-implementer.toml"]},
        "user_host": {
            "directory": str(host_home.resolve() / "agents"),
            "files": ["thaliris-investigator.toml"],
            "sha256": {"thaliris-investigator.toml": hashlib.sha256(host_profile.read_bytes()).hexdigest()},
        },
    }
    assert "native_role_profile_names_at_start" not in runtime
    assert runtime["host_role_catalog_status"] == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN
    assert lifecycle_module.role_catalog_session_status(tmp_path, session_hash) == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN


def test_role_content_update_by_existing_filename_does_not_look_like_new_identity(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    profile = tmp_path / ".codex" / "agents" / "thaliris-implementer.toml"
    profile.parent.mkdir(parents=True)
    profile.write_bytes(codex_adapter._agent_profile("thaliris-implementer", "implementer", "gpt-6-luna", "xhigh"))
    codex_adapter.audit_hook(tmp_path, "SessionStart", {"session_id": "content-session", "source": "startup", "cwd": str(tmp_path)})
    profile.write_bytes(profile.read_bytes() + b"\n# updated content\n")
    session_hash = hashlib.sha256(b"content-session").hexdigest()
    assert lifecycle_module.new_role_profile_files(tmp_path, session_hash) == []
    assert lifecycle_module.role_catalog_session_status(tmp_path, session_hash) == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN


def test_host_profiles_added_after_session_start_are_reported(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    codex_adapter.audit_hook(tmp_path, "SessionStart", {"session_id": "host-late-session", "source": "startup", "cwd": str(tmp_path)})
    installed = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert installed["changed"] is True
    session_hash = hashlib.sha256(b"host-late-session").hexdigest()
    expected = sorted(str(host_home.resolve() / "agents" / name) for name in codex_adapter._AGENT_PROFILES)
    assert lifecycle_module.new_role_profile_files(tmp_path, session_hash) == expected
    assert lifecycle_module.role_catalog_session_status(tmp_path, session_hash) == lifecycle_module.NEW_ROLE_CATALOG_IDENTITY_NOT_ACTIVE


def test_missing_profile_snapshot_and_forged_catalog_field_stay_unknown(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    codex_adapter.audit_hook(tmp_path, "SessionStart", {"session_id": "unknown-session", "source": "startup", "cwd": str(tmp_path)})
    session_hash = hashlib.sha256(b"unknown-session").hexdigest()
    runtime_path = tmp_path / ".context" / "audit" / session_hash[:24] / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["host_role_catalog_status"] = lifecycle_module.HOST_ROLE_CATALOG_OBSERVED
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    assert lifecycle_module.role_catalog_session_status(tmp_path, session_hash) == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN
    runtime.pop("profile_files_present_at_session_start")
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    assert lifecycle_module.new_role_profile_files(tmp_path, session_hash) is None
    assert lifecycle_module.role_catalog_session_status(tmp_path, session_hash) == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN


def test_task_start_blocks_host_role_added_after_current_session_start(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    host_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(host_home))
    codex_adapter.audit_hook(tmp_path, "SessionStart", {"session_id": "late-host-session", "source": "startup", "cwd": str(tmp_path)})
    init = codex_adapter.init(tmp_path)
    authorized_host_install(tmp_path, pinned_test_thaliris)
    digest = init["controller_bridge_sha256"]
    pre = {"session_id": "late-host-session", "turn_id": "turn", "tool_name": "Bash", "tool_input": {"command": f"thaliris task-start goal --controller-bridge-sha256 {digest}"}}
    rewritten = json.loads(codex_adapter.audit_hook(tmp_path, "PreToolUse", pre, lifecycle_module.MANAGED_HOOK_ABI))
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", rewritten["hookSpecificOutput"]["updatedInput"]["command"]).group(1)
    result = codex_adapter.task_start(tmp_path, "goal", None, None, token, digest)
    assert result["status"] == lifecycle_module.NEW_ROLE_CATALOG_IDENTITY_NOT_ACTIVE
    assert result["new_role_profile_files"] == sorted(str(host_home.resolve() / "agents" / name) for name in codex_adapter._AGENT_PROFILES)
    assert not (tmp_path / ".context" / "state.json").exists()


def test_codex_install_is_idempotent_and_preserves_non_owned_collisions(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    user_handler = {"type": "command", "command": "user-owned-handler", "timeout": 60}
    hooks_path = home / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [user_handler]}]}}), encoding="utf-8")
    first = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert first["ok"] is True
    assert first["changed"] is True
    assert {f"agents/{name}" for name in codex_adapter._AGENT_PROFILES} <= set(first["files"])
    assert {"hooks.json", lifecycle_module.HOST_HOOK_SCRIPT_NAME} <= set(first["files"])
    assert first["host_role_catalog_status"] == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN
    assert first["host_hook_registration_present"] == "YES"
    assert first["host_setup_requires_session_start"] is True
    installed_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert user_handler in installed_hooks["hooks"]["UserPromptSubmit"][0]["hooks"]
    assert codex_adapter._project_definition_facts(repo(tmp_path / "project"))["host_hook_registration_present"] == "YES"
    second = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert second["changed"] is False
    assert second["host_setup_requires_session_start"] is False
    collision = home / "agents" / "thaliris-implementer.toml"
    collision.write_text("user-owned = true\n", encoding="utf-8")
    before_collision = {path.relative_to(home).as_posix(): path.read_bytes() for path in home.rglob("*") if path.is_file()}
    third = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert third["ok"] is False
    assert third["changed"] is False
    assert any(str(collision) in item for item in third["manual_action_required"])
    assert {path.relative_to(home).as_posix(): path.read_bytes() for path in home.rglob("*") if path.is_file()} == before_collision
    assert collision.read_text(encoding="utf-8") == "user-owned = true\n"


def test_codex_install_updates_and_uninstall_removes_only_global_owned_span(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    executable, digest = pinned_test_thaliris
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    original = b"# User instructions\r\nKeep this text and its bytes.\r\n\xff"
    global_agents = home / "AGENTS.md"
    global_agents.write_bytes(original)

    first = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert first["ok"] is True
    assert first["global_instruction_ready"] == "YES"
    assert "AGENTS.md" in first["files"]
    assert first["project_files_touched"] == []
    expected = codex_adapter._global_agents_block(executable, digest)
    assert global_agents.read_bytes() == expected + original
    assert expected.count(b"--root <repo> controller-instructions") == 1
    assert expected.count(b"--root <repo> codex-bootstrap") == 1
    assert str(home / lifecycle_module.HOST_RUN_SCRIPT_NAME).encode() in expected
    assert str(executable).encode() not in expected and digest.encode() not in expected
    controller_text = controller_instructions.render().encode()
    assert b"authority-contract" in controller_text
    assert b"task_start_receipt" not in controller_text and b"--bootstrap-receipt" not in controller_text
    assert b"--controller-bridge-sha256" not in expected
    assert b"bootstrap-check" not in expected and b" --root <repo> init" not in expected
    assert b"Get-FileHash" not in expected
    normalized_expected = " ".join(expected.decode().lower().split())
    for concept in ("read-only", "managed children", "authority", "installed pinned runner"):
        assert concept in normalized_expected
    normalized_controller = " ".join(controller_text.decode().lower().split())
    for detail in ("host root identity remains unknown", "task-recover-state", "task-recover-authority",
                   "fences", "global integration", "project router"):
        assert detail in normalized_controller
        assert detail.encode() not in expected.lower()
    assert "focused-test pass" not in normalized_expected
    assert "smallest relevant tests" not in normalized_expected

    second = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert second["changed"] is False
    assert global_agents.read_bytes() == expected + original

    old_owned = b"<!-- thaliris:global:begin -->\nold startup\n<!-- thaliris:global:end -->\n"
    global_agents.write_bytes(b"before\r\n" + old_owned + b"after\r\n\xff")
    attest_prior_authorized_bytes(home, {"AGENTS.md#global": old_owned})
    refreshed = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert refreshed["changed"] is True
    assert refreshed["host_setup_requires_session_start"] is True
    assert global_agents.read_bytes() == b"before\r\n" + expected + b"after\r\n\xff"

    removed = authorized_host_uninstall(tmp_path, pinned_test_thaliris)
    assert "AGENTS.md" in removed["files"]
    assert global_agents.read_bytes() == b"before\r\nafter\r\n\xff"


def test_codex_install_upgrades_previous_official_global_block(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    executable, digest = pinned_test_thaliris
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    previous_official = f"""<!-- thaliris:global:begin -->
## Thaliris project startup

For substantive work that creates or changes files in a Git repository,
including a README, unless the user explicitly opts out, check the repository root for
`.codex/thaliris.json` and the effective root AGENTS instruction for the
`<!-- thaliris:begin -->` project block. If readiness is not already confirmed,
run a trusted direct `--root <repo> bootstrap-check` once, including when both
project markers are absent. If it reports either project definition or activation
marker missing, run trusted direct `--root <repo> init` and read its result.
Do not repeat bootstrap for confirmed readiness or run `init` during an ACTIVE
managed task. Chatting, informational questions, read-only work, and non-Git
directories do not call for proactive project bootstrap.

Installed direct executable: `{executable}`
Expected SHA-256: `{digest}`
Check the executable's current SHA-256 against this exact pin before use.
Invoke that absolute executable directly for Thaliris commands; a different
`thaliris` found on PATH is not evidence that it has the installed ABI.

Read the canonical managed instruction text and SHA-256 from `init` or
`bootstrap-check`, then acknowledge that digest with
`--controller-bridge-sha256` in `task-start` in the same session. Follow the
effective project instruction for task routing. A CLI result does not prove
Host instruction activation or a loaded current-session hook.
<!-- thaliris:global:end -->
""".encode("utf-8")
    user_prefix = b"# User rules\r\nKeep prefix.\r\n"
    user_suffix = b"Keep suffix.\r\n\xff"
    global_agents = home / "AGENTS.md"
    prior_bytes = user_prefix + previous_official + user_suffix
    global_agents.write_bytes(prior_bytes)
    start, end = codex_adapter._global_agents_span(prior_bytes)
    legacy_owned_bytes = {"AGENTS.md#global": hashlib.sha256(prior_bytes[start:end]).hexdigest()}

    installed = authorized_host_install(
        tmp_path, pinned_test_thaliris, _legacy_owned_bytes=legacy_owned_bytes
    )

    assert installed["ok"] is True
    assert global_agents.read_bytes() == (
        user_prefix + codex_adapter._global_agents_block(executable, digest) + user_suffix
    )


def test_codex_uninstall_removes_new_global_instruction_file(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    authorized_host_install(tmp_path, pinned_test_thaliris)
    global_agents = home / "AGENTS.md"
    assert global_agents.read_bytes() == codex_adapter._global_agents_block(*pinned_test_thaliris)
    removed = authorized_host_uninstall(tmp_path, pinned_test_thaliris)
    assert "AGENTS.md" in removed["files"]
    assert not global_agents.exists()


@pytest.mark.parametrize("original", [
    b"<!-- thaliris:global:begin -->\nbroken",
    b"<!-- thaliris:global:end -->\n",
    b"<!-- thaliris:global:begin -->\none\n<!-- thaliris:global:end -->\n<!-- thaliris:global:begin -->\ntwo\n<!-- thaliris:global:end -->\n",
    b"<!-- thaliris:begin -->\nproject content\n<!-- thaliris:end -->\n",
])
def test_codex_install_rejects_ambiguous_global_markers(tmp_path: Path, monkeypatch, pinned_test_thaliris, original: bytes) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    global_agents = home / "AGENTS.md"
    global_agents.write_bytes(original)
    result = authorized_host_install(tmp_path, pinned_test_thaliris)
    assert result["ok"] is False
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["manual_action_required"]
    assert global_agents.read_bytes() == original
    removed = authorized_host_uninstall(tmp_path, pinned_test_thaliris)
    assert removed["changed"] is False
    assert global_agents.read_bytes() == original


def test_codex_install_migrates_exact_legacy_host_hook_and_uninstall_preserves_user_data(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    user_handler = {"type": "command", "command": "user-hook", "timeout": 60}
    legacy_handler = {
        "type": "command",
        "command": "thaliris audit-hook PreToolUse --managed-hook-abi thaliris-hook-abi-9",
        "timeout": 60,
    }
    hooks_path = home / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    original = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [legacy_handler, user_handler]}]}}
    hooks_path.write_text(json.dumps(original), encoding="utf-8")

    installed = authorized_host_install(
        tmp_path, pinned_test_thaliris,
        _legacy_owned_bytes={"hooks.json": hashlib.sha256(hooks_path.read_bytes()).hexdigest()},
    )

    assert installed["host_hook_registration_present"] == "YES"
    merged = json.loads(hooks_path.read_text(encoding="utf-8"))
    pre_handlers = [handler for group in merged["hooks"]["PreToolUse"] for handler in group["hooks"]]
    assert legacy_handler not in pre_handlers
    assert user_handler in pre_handlers
    assert sum(lifecycle_module._host_hook_command_is_managed(handler, "PreToolUse", home) for handler in pre_handlers) == 1

    user_profile = home / "agents" / "thaliris-investigator.toml"
    user_profile.write_text("user-owned = true\n", encoding="utf-8")
    removed = authorized_host_uninstall(tmp_path, pinned_test_thaliris)

    assert removed["changed"] is True
    assert removed["project_files_touched"] == []
    assert not (home / lifecycle_module.HOST_HOOK_SCRIPT_NAME).exists()
    assert user_profile.read_text(encoding="utf-8") == "user-owned = true\n"
    remaining = json.loads(hooks_path.read_text(encoding="utf-8"))
    remaining_handlers = [handler for entries in remaining["hooks"].values() for group in entries for handler in group.get("hooks", [])]
    assert remaining_handlers == [user_handler]


def test_codex_install_user_hook_collision_is_manual_and_untouched(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    script = home / lifecycle_module.HOST_HOOK_SCRIPT_NAME
    script.parent.mkdir(parents=True)
    script.write_text("user-owned script\n", encoding="utf-8")
    hooks_path = home / "hooks.json"
    original_hooks = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "keep", "timeout": 60}]}]}}
    hooks_path.write_text(json.dumps(original_hooks), encoding="utf-8")

    before = {path.relative_to(home).as_posix(): path.read_bytes() for path in home.rglob("*") if path.is_file()}
    result = authorized_host_install(tmp_path, pinned_test_thaliris)

    assert result["ok"] is False
    assert result["changed"] is False
    assert any(str(script) in item for item in result["manual_action_required"])
    assert {path.relative_to(home).as_posix(): path.read_bytes() for path in home.rglob("*") if path.is_file()} == before
    assert script.read_text(encoding="utf-8") == "user-owned script\n"
    assert json.loads(hooks_path.read_text(encoding="utf-8")) == original_hooks


def test_codex_install_rejects_changed_runtime_at_same_path(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    executable, old_digest = pinned_test_thaliris
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    authorized_host_install(tmp_path, pinned_test_thaliris)
    executable.write_bytes(b"updated executable at the same path")
    new_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    monkeypatch.setattr(
        codex_adapter,
        "_host_install_executable",
        lambda _home, _path, _sha: (executable, new_digest, None),
    )

    before = {path.relative_to(home).as_posix(): path.read_bytes() for path in home.rglob("*") if path.is_file()}
    result = authorized_host_install(tmp_path, pinned_test_thaliris)

    assert result["ok"] is False
    assert result["changed"] is False
    assert result["manual_action_required"]
    assert {path.relative_to(home).as_posix(): path.read_bytes() for path in home.rglob("*") if path.is_file()} == before
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == new_digest


def test_codex_install_migrates_exact_old_trampoline_bytes(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    authorized_host_install(tmp_path, pinned_test_thaliris)
    script = home / lifecycle_module.HOST_HOOK_SCRIPT_NAME
    old_script = lifecycle_module._legacy_host_hook_script_bytes()
    script.write_bytes(old_script)
    attest_prior_authorized_bytes(home, {lifecycle_module.HOST_HOOK_SCRIPT_NAME: old_script})

    result = authorized_host_install(tmp_path, pinned_test_thaliris)

    assert result["changed"] is True
    assert result["manual_action_required"] == []
    assert script.read_bytes() == lifecycle_module.host_hook_script_bytes()


def test_project_init_after_host_install_uses_only_activation_marker(tmp_path: Path, monkeypatch, pinned_test_thaliris) -> None:
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    authorized_host_install(tmp_path, pinned_test_thaliris)
    root = repo(tmp_path / "zero-state-project")

    facts = codex_adapter.bootstrap_check(root)

    assert facts["project_definition_present"] == "YES"
    assert facts["project_activation_marker_present"] == "YES"
    assert facts["host_hook_registration_present"] == "YES"
    assert facts["host_profile_definition_present"] == "YES"
    assert facts["host_role_catalog_status"] == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN
    assert facts["legacy_project_hook_registration_present"] == "NO"
    assert not (root / ".codex" / "hooks.json").exists()
    assert facts.get("host_session_load_status") is None


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows Host trampoline")
def test_global_trampoline_is_transparent_without_project_marker(tmp_path: Path) -> None:
    script = tmp_path / "host home" / lifecycle_module.HOST_HOOK_SCRIPT_NAME
    script.parent.mkdir(parents=True)
    script.write_bytes(lifecycle_module.host_hook_script_bytes())
    from thaliris_codex import host_preflight
    (script.parent / host_preflight.NAME).write_bytes(host_preflight.script_bytes())
    project = tmp_path / "ordinary non-Thaliris repository"
    deep = project / "nested" / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    absent_exe = tmp_path / "must-not-launch.exe"
    before = sorted(str(path.relative_to(project)) for path in project.rglob("*"))

    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(script), str(absent_exe), "0" * 64, "PreToolUse", lifecycle_module.MANAGED_HOOK_ABI],
        cwd=deep,
        input=b"{}",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""
    assert sorted(str(path.relative_to(project)) for path in project.rglob("*")) == before
    assert not (project / ".context").exists()


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows Host trampoline")
def test_global_trampoline_finds_repo_marker_from_nested_cwd(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "host home" / lifecycle_module.HOST_HOOK_SCRIPT_NAME
    script.parent.mkdir(parents=True)
    script.write_bytes(lifecycle_module.host_hook_script_bytes())
    from thaliris_codex import host_preflight
    (script.parent / host_preflight.NAME).write_bytes(host_preflight.script_bytes())
    project = tmp_path / "activated project"
    (project / ".codex").mkdir(parents=True)
    (project / ".codex" / "thaliris.json").write_bytes(
        b'{"format":"thaliris-project-activation-v1"}\n'
    )
    deep = project / "nested" / "a" / "b"
    deep.mkdir(parents=True)
    dispatched = tmp_path / "dispatch.log"
    venv = tmp_path / "fake runtime"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = test\ninclude-system-site-packages = false\n", encoding="utf-8")
    package = venv / "Lib" / "site-packages" / "thaliris_codex"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text("def main(): pass\n", encoding="utf-8")
    fake_executable = venv / "Scripts" / "fake thaliris.cmd"
    fake_executable.write_text(
        '@echo off\r\n> "%THALIRIS_TEST_DISPATCH_FILE%" echo %*\r\n',
        encoding="ascii",
    )
    manifest = runtime_identity.manifest_bytes(fake_executable)
    (script.parent / runtime_identity.MANIFEST_NAME).write_bytes(manifest)
    identity = runtime_identity.manifest_identity(manifest)
    monkeypatch.setenv("THALIRIS_TEST_DISPATCH_FILE", str(dispatched))

    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(script), str(fake_executable), hashlib.sha256(fake_executable.read_bytes()).hexdigest(), identity, "PreToolUse", lifecycle_module.MANAGED_HOOK_ABI],
        cwd=deep,
        input=b"{}",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout == b""
    if result.stderr:
        # Windows PowerShell may report first-use module preparation on its
        # progress stream even with a successful pinned dispatch.
        import xml.etree.ElementTree as ET
        assert result.stderr.startswith(b"#< CLIXML\r\n")
        records = ET.fromstring(result.stderr.split(b"\n", 1)[1])
        assert len(records) and all(item.get("S") == "progress" for item in records)
        assert all(item.text == "Preparing modules for first use." for item in records.iter()
                   if item.tag.endswith("}AV"))
    assert dispatched.read_text(encoding="ascii").strip() == (
        f"audit-hook PreToolUse --managed-hook-abi {lifecycle_module.MANAGED_HOOK_ABI}"
    )
    assert not (project / ".context").exists()

    dispatched.unlink()
    (package / "cli.py").write_text("changed package code\n", encoding="utf-8")
    rejected = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(script), str(fake_executable), hashlib.sha256(fake_executable.read_bytes()).hexdigest(), identity, "PreToolUse", lifecycle_module.MANAGED_HOOK_ABI],
        cwd=deep, input=b'{"tool_name":"Bash","tool_input":{"command":"thaliris task-start changed"}}', capture_output=True, check=False, timeout=10,
    )
    assert rejected.returncode == 0
    assert json.loads(rejected.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not dispatched.exists()

    (package / "cli.py").write_text("def main(): pass\n", encoding="utf-8")
    (script.parent / runtime_identity.MANIFEST_NAME).write_bytes(manifest + b" ")
    mismatched = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(script), str(fake_executable), hashlib.sha256(fake_executable.read_bytes()).hexdigest(), identity, "PreToolUse", lifecycle_module.MANAGED_HOOK_ABI],
        cwd=deep, input=b'{"tool_name":"Bash","tool_input":{"command":"thaliris task-start changed"}}', capture_output=True, check=False, timeout=10,
    )
    assert mismatched.returncode == 0
    assert json.loads(mismatched.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not dispatched.exists()


def test_initialized_task_start_reports_unavailable_trusted_executable(tmp_path: Path, monkeypatch) -> None:
    for name in ("THALIRIS_EXECUTABLE", "THALIRIS_EXECUTABLE_SHA256", "THALIRIS_CONTEXT_EXECUTABLE", "THALIRIS_CONTEXT_EXECUTABLE_SHA256"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lifecycle_module.shutil, "which", lambda command: None)
    root = repo(tmp_path)
    digest = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    payload = {"session_id": "exec-s1", "turn_id": "exec-turn", "tool_name": "Bash", "tool_input": {"command": f"thaliris task-start x --controller-bridge-sha256 {digest}"}}
    rewritten = json.loads(codex_adapter.audit_hook(root, "PreToolUse", payload, lifecycle_module.MANAGED_HOOK_ABI))
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", rewritten["hookSpecificOutput"]["updatedInput"]["command"]).group(1)
    result = codex_adapter.task_start(root, "x", None, None, token, digest)
    assert result["status"] == "BOOTSTRAP_REQUIRED"
    assert result["bootstrap"]["canonical_executable_available"] == "NO"


def test_user_profile_is_preserved_and_not_a_definition(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    codex_adapter.init(tmp_path)
    profile = tmp_path / ".codex" / "agents" / "thaliris-implementer.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("user-owned = true\n", encoding="utf-8")
    result = codex_adapter.init(tmp_path)
    assert profile.read_text(encoding="utf-8") == "user-owned = true\n"
    assert result["project_local_profile_files_present"] == "YES"
    assert result["host_profile_definition_present"] == "NO"
    assert result["host_role_catalog_status"] == lifecycle_module.HOST_ROLE_CATALOG_UNKNOWN
    assert "profile_definition_present" not in result
    assert result["project_definition_present"] == "YES"


def test_mutated_managed_instruction_is_user_owned_and_preserved(tmp_path: Path) -> None:
    root = repo(tmp_path)
    instruction = root / "AGENTS.md"
    original = instruction.read_bytes()
    marker = codex_adapter.MANAGED_START.encode("utf-8")
    offset = original.index(marker) + len(marker)
    instruction.write_bytes(original[:offset] + b"\n# mutated\n" + original[offset:])

    facts = codex_adapter._project_definition_facts(root)
    assert facts["instruction_definition_present"] == "NO"
    assert facts["project_definition_present"] == "NO"
    assert codex_adapter.task_start(root, "bootstrap", None, None)["status"] == "BOOTSTRAP_REQUIRED"

    repaired = codex_adapter.init(root)
    assert repaired["instruction_definition_present"] == "NO"
    assert repaired["project_definition_present"] == "NO"
    assert "AGENTS.md" in repaired["manual_action_required"]
    assert instruction.read_bytes() == original[:offset] + b"\n# mutated\n" + original[offset:]

    second = codex_adapter.init(root)
    assert second["changed"] is False
    assert second["session_restart_required"] is False


def test_explicit_managed_instruction_migration_replaces_only_confirmed_span(tmp_path: Path) -> None:
    root = repo(tmp_path)
    path = root / "AGENTS.md"
    prefix = "# User-owned project notes\n\n"
    suffix = "\n\n## User-owned footer\nKeep this text.\n"
    stale = codex_adapter.render_managed().replace(
        codex_adapter.MANAGED_END,
        "User-owned stale routing advice\n" + codex_adapter.MANAGED_END,
        1,
    )
    path.write_text(prefix + stale.removesuffix("\n") + suffix, encoding="utf-8")
    start = (prefix + stale).index(codex_adapter.MANAGED_START)
    end = (prefix + stale).index(codex_adapter.MANAGED_END, start) + len(codex_adapter.MANAGED_END)
    stale_span = (prefix + stale)[start:end]
    digest = hashlib.sha256(stale_span.encode("utf-8")).hexdigest()

    blocked = codex_adapter.init(root)
    assert blocked["changed"] is False
    assert blocked["definition_recovery_status"] == "EXPLICIT_CONFIRMATION_REQUIRED"
    assert blocked["instruction_definition_present"] == "NO"
    assert blocked["managed_instruction_sha256"] == digest
    assert "AGENTS.md" in blocked["manual_action_required"]
    assert path.read_text(encoding="utf-8") == prefix + stale.removesuffix("\n") + suffix
    check = codex_adapter.bootstrap_check(root)
    assert check["definition_recovery_status"] == "EXPLICIT_CONFIRMATION_REQUIRED"
    assert check["managed_instruction_recovery_action"] == f"thaliris init --accept-managed-instruction-sha256 {digest}"

    wrong = "0" * 64 if digest != "0" * 64 else "1" * 64
    refused = codex_adapter.init(root, accept_managed_instruction_sha256=wrong)
    assert refused["instruction_definition_present"] == "NO"
    assert "AGENTS.md" in refused["manual_action_required"]

    accepted = codex_adapter.init(root, accept_managed_instruction_sha256=digest)
    assert accepted["changed"] is True
    assert accepted["definition_recovery_status"] == "READY"
    assert accepted["instruction_definition_present"] == "YES"
    assert path.read_text(encoding="utf-8") == prefix + codex_adapter.render_managed().removesuffix("\n") + suffix


def _attested_recovery_command(root: Path, command: str) -> tuple[str, str]:
    response = json.loads(handle_hook(
        root,
        "PreToolUse",
        hook_payload(tool_name="Bash", tool_input={"command": command}),
        lifecycle_module.MANAGED_HOOK_ABI,
    ))
    rewritten = response["hookSpecificOutput"]["updatedInput"]["command"]
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", rewritten)
    assert token is not None
    return rewritten, token.group(1)


@pytest.mark.parametrize("incompatible", [False, True])
@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_task_abandon_help_is_read_only_and_does_not_issue_proof(
    tmp_path: Path, capsys, incompatible: bool, help_flag: str,
) -> None:
    root = repo(tmp_path)
    legacy_state_path = root / ".context" / "state.json"
    if incompatible:
        old_state = {
            "schema_version": 1,
            "revision": 1,
            "task_id": "7e500c6a-6aec-4e22-94b0-42cc6a5459ef",
            "status": "ACTIVE",
            "goal": "old state remains unchanged",
            "active_work": [],
            "pending_results": [],
        }
        legacy_state_path.write_text(json.dumps(old_state), encoding="utf-8")
        core.select_task(root, old_state["task_id"])
        state_path = core._state_path(root, old_state["task_id"])
    else:
        started = core.task_start(root, "active state remains unchanged", None, None)
        core.select_task(root, started["task_id"])
        state_path = core._state_path(root, started["task_id"])
    original_state = state_path.read_bytes()
    command = (
        f'thaliris task-abandon {help_flag} --reason "quoted >, <, and ; stay text" '
        f"--hook-attestation v1.{('0' * 64)}.{('A' * 24)}"
    )
    payload = hook_payload(tool_name="Bash", tool_input={"command": command})

    assert lifecycle_module._context_operation(payload) is None
    assert lifecycle_module._context_help_requested(payload)
    assert handle_hook(root, "PreToolUse", payload, lifecycle_module.MANAGED_HOOK_ABI) == ""
    with pytest.raises(SystemExit) as help_exit:
        cli.main(["--root", str(root), "task-abandon", help_flag, "--hook-attestation", "unused"])

    assert help_exit.value.code == 0
    assert "usage: thaliris task-abandon" in capsys.readouterr().out
    assert state_path.read_bytes() == original_state
    attestation_dir = root / ".context" / "audit" / "task-start-attestations"
    assert not attestation_dir.exists() or not list(attestation_dir.glob("*.json"))


@pytest.mark.parametrize("redirection", [">", ">>", "2>", "2>>", "<", "<<<"])
def test_task_abandon_help_with_shell_redirection_is_denied_before_state_changes(
    tmp_path: Path, redirection: str,
) -> None:
    root = repo(tmp_path)
    started = core.task_start(root, "active state survives redirected help", None, None)
    core.select_task(root, started["task_id"])
    state_path = core._state_path(root, started["task_id"])
    state_target = state_path.relative_to(root).as_posix()
    original_state = state_path.read_bytes()
    command = f"thaliris task-abandon --help {redirection} {state_target}"
    payload = hook_payload(tool_name="Bash", tool_input={"command": command})

    assert not lifecycle_module._context_help_requested(payload)
    denied = json.loads(handle_hook(root, "PreToolUse", payload, lifecycle_module.MANAGED_HOOK_ABI))

    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert state_path.read_bytes() == original_state


@pytest.mark.parametrize("expression", [
    "@(Remove-Item .context/state.json)",
    "@{x=Remove-Item .context/state.json}",
    "(Remove-Item .context/state.json)",
    "$(Remove-Item .context/state.json)",
    "`x`",
])
def test_task_abandon_help_rejects_unquoted_shell_expressions(
    tmp_path: Path, expression: str,
) -> None:
    root = repo(tmp_path)
    started = core.task_start(root, "active state survives shell expression help", None, None)
    core.select_task(root, started["task_id"])
    state_path = core._state_path(root, started["task_id"])
    state_target = state_path.relative_to(root).as_posix()
    original_state = state_path.read_bytes()
    command = f"& 'thaliris.exe' task-abandon --help {expression.replace('.context/state.json', state_target)}"
    payload = hook_payload(tool_name="Bash", tool_input={"command": command})

    assert lifecycle_module._context_help_status(payload) == (True, True)
    assert not lifecycle_module._context_help_requested(payload)
    denied = json.loads(handle_hook(root, "PreToolUse", payload, lifecycle_module.MANAGED_HOOK_ABI))

    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "THALIRIS_UNSAFE_HELP_SYNTAX" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert state_path.read_bytes() == original_state
    attestation_dir = root / ".context" / "audit" / "task-start-attestations"
    assert not attestation_dir.exists() or not list(attestation_dir.glob("*.json"))


def test_top_level_help_rejects_unquoted_powershell_hashtable_expression(tmp_path: Path) -> None:
    root = repo(tmp_path)
    started = core.task_start(root, "active state survives hashtable help expression", None, None)
    core.select_task(root, started["task_id"])
    state_path = core._state_path(root, started["task_id"])
    state_target = state_path.relative_to(root).as_posix()
    original_state = state_path.read_bytes()
    command = f"thaliris.exe --help @{{x=Remove-Item {state_target}}}"
    payload = hook_payload(tool_name="Bash", tool_input={"command": command})

    assert lifecycle_module._context_help_status(payload) == (True, True)
    denied = json.loads(handle_hook(root, "PreToolUse", payload, lifecycle_module.MANAGED_HOOK_ABI))

    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "THALIRIS_UNSAFE_HELP_SYNTAX" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert state_path.read_bytes() == original_state
    attestation_dir = root / ".context" / "audit" / "task-start-attestations"
    assert not attestation_dir.exists() or not list(attestation_dir.glob("*.json"))


def test_invalid_state_admission_requires_confirmed_recovery(tmp_path: Path, monkeypatch, capsys) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(lifecycle_module, "managed_executable_health", lambda: {"canonical_executable_available": "YES"})
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    state = {
        "schema_version": 1,
        "revision": 2,
        "task_id": "7e500c6a-6aec-4e22-94b0-42cc6a5459ef",
        "status": "ACTIVE",
        "goal": "old state remains archived evidence",
        "current_milestone": None,
        "active_work": [],
        "pending_results": [],
        "architectural_intent": None,
    }
    state_path = root / ".context" / "state.json"
    old_task_id = state["task_id"]
    old_bytes = json.dumps(state, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    state_path.write_bytes(old_bytes)
    digest = hashlib.sha256(old_bytes).hexdigest()
    bridge = codex_adapter._controller_bridge()["controller_bridge_sha256"]

    start_command = f"thaliris task-start new-goal --controller-bridge-sha256 {bridge}"
    start_admitted = json.loads(handle_hook(
        root,
        "PreToolUse",
        hook_payload(tool_name="Bash", tool_input={"command": start_command}),
        lifecycle_module.MANAGED_HOOK_ABI,
    ))
    assert start_admitted["hookSpecificOutput"]["permissionDecision"] == "allow"
    new_task = core.task_start(root, "new-goal", None, None)
    assert new_task["task_id"] != old_task_id
    new_state_path = core._state_path(root, new_task["task_id"])
    assert new_state_path.is_file()
    assert state_path.read_bytes() == old_bytes

    core.select_task(root, old_task_id)

    no_confirm_command = f"thaliris --task-id {old_task_id} task-recover-state --expected-sha256 {digest} --controller-bridge-sha256 {bridge}"
    no_confirm_denied = json.loads(handle_hook(
        root,
        "PreToolUse",
        hook_payload(tool_name="Bash", tool_input={"command": no_confirm_command}),
        lifecycle_module.MANAGED_HOOK_ABI,
    ))
    assert no_confirm_denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "INVALID_STATE" in no_confirm_denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert state_path.read_bytes() == old_bytes

    wrong_digest = "0" * 64 if digest != "0" * 64 else "1" * 64
    wrong_command = f"thaliris --task-id {old_task_id} task-recover-state --expected-sha256 {wrong_digest} --abandon-active --controller-bridge-sha256 {bridge}"
    wrong_denied = json.loads(handle_hook(
        root,
        "PreToolUse",
        hook_payload(tool_name="Bash", tool_input={"command": wrong_command}),
        lifecycle_module.MANAGED_HOOK_ABI,
    ))
    assert wrong_denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "INVALID_STATE" in wrong_denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert state_path.read_bytes() == old_bytes

    command = f"thaliris --task-id {old_task_id} task-recover-state --expected-sha256 {digest} --abandon-active --controller-bridge-sha256 {bridge}"
    _, token = _attested_recovery_command(root, command)
    assert cli.main([
        "--root", str(root), "--task-id", old_task_id, "task-recover-state", "--expected-sha256", digest,
        "--abandon-active", "--hook-attestation", token,
        "--controller-bridge-sha256", bridge,
    ]) == 0
    recovered = json.loads(capsys.readouterr().out)
    archive = root / recovered["preserved_state_location"]
    assert recovered["status"] == "STATE_ARCHIVED_FOR_RECOVERY"
    assert recovered["from_version"] == 1
    assert recovered["to_version"] == core._STATE_SCHEMA_VERSION
    assert recovered["state_sha256"] == digest
    assert archive.read_bytes() == old_bytes
    assert not state_path.exists()
    fresh = core.task_start(root, "new current-schema task", None, None)
    assert fresh["status"] == "ACTIVE"
    current = json.loads(core._state_path(root, fresh["task_id"]).read_text(encoding="utf-8"))
    assert current["schema_version"] == core._STATE_SCHEMA_VERSION


def test_state_recovery_blocks_when_lifecycle_authority_is_not_terminal(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(lifecycle_module, "managed_executable_health", lambda: {"canonical_executable_available": "YES"})
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    task_id = "a8d2185f-a0de-44f6-a4cc-697b07eb3038"
    state = {"schema_version": 1, "revision": 1, "task_id": task_id, "status": "ACTIVE", "goal": "old", "active_work": [], "pending_results": []}
    state_path = root / ".context" / "state.json"
    old_bytes = json.dumps(state).encode("utf-8")
    state_path.write_bytes(old_bytes)
    core.select_task(root, task_id)
    lifecycle_path = lifecycle_module._lifecycle_path(root, task_id)
    lifecycle_path.parent.mkdir(parents=True)
    lifecycle_path.write_text(json.dumps({
        "version": lifecycle_module.LIFECYCLE_STATE_VERSION,
        "task_id_hash": lifecycle_module._task_key(task_id),
        "children": [{"terminal_state": "RUNNING"}],
        "pending_authorized_spawn": None,
        "sequence": 1,
    }), encoding="utf-8")
    digest = hashlib.sha256(old_bytes).hexdigest()
    bridge = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    command = f"thaliris --task-id {task_id} task-recover-state --expected-sha256 {digest} --abandon-active --controller-bridge-sha256 {bridge}"
    denied = json.loads(handle_hook(
        root,
        "PreToolUse",
        hook_payload(tool_name="Bash", tool_input={"command": command}),
        lifecycle_module.MANAGED_HOOK_ABI,
    ))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "INVALID_STATE" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert state_path.read_bytes() == old_bytes


@pytest.mark.parametrize("lifecycle_state", ["unreadable", "pending", "nonterminal"])
def test_state_recovery_refuses_unresolved_lifecycle_authority(tmp_path: Path, lifecycle_state: str) -> None:
    root = repo(tmp_path)
    task_id = "a8d2185f-a0de-44f6-a4cc-697b07eb3038"
    state = {
        "schema_version": 1,
        "revision": 1,
        "task_id": task_id,
        "status": "ACTIVE",
        "goal": "old",
        "active_work": [],
        "pending_results": [],
    }
    state_path = root / ".context" / "state.json"
    old_bytes = json.dumps(state).encode("utf-8")
    state_path.write_bytes(old_bytes)
    core.select_task(root, task_id)
    path = lifecycle_module._lifecycle_path(root, task_id)
    path.parent.mkdir(parents=True)
    if lifecycle_state == "unreadable":
        path.write_text("{malformed", encoding="utf-8")
    else:
        record = {
            "version": lifecycle_module.LIFECYCLE_STATE_VERSION,
            "task_id_hash": lifecycle_module._task_key(task_id),
            "children": [] if lifecycle_state == "pending" else [{"terminal_state": "RUNNING"}],
            "pending_authorized_spawn": {"unresolved": True} if lifecycle_state == "pending" else None,
            "sequence": 1,
        }
        path.write_text(json.dumps(record), encoding="utf-8")
    digest = hashlib.sha256(old_bytes).hexdigest()
    bridge = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    command = f"thaliris --task-id {task_id} task-recover-state --expected-sha256 {digest} --abandon-active --controller-bridge-sha256 {bridge}"
    denied = json.loads(handle_hook(
        root,
        "PreToolUse",
        hook_payload(tool_name="Bash", tool_input={"command": command}),
        lifecycle_module.MANAGED_HOOK_ABI,
    ))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "INVALID_STATE" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert state_path.read_bytes() == old_bytes


def test_mixed_user_line_endings_do_not_invalidate_unchanged_managed_instruction(tmp_path: Path) -> None:
    root = repo(tmp_path)
    instruction = root / "AGENTS.md"
    managed = instruction.read_text(encoding="utf-8")
    start = managed.index(codex_adapter.MANAGED_START)
    end = managed.index(codex_adapter.MANAGED_END) + len(codex_adapter.MANAGED_END)
    instruction.write_bytes(
        b"user-owned header\r\n"
        + managed[start:end].encode("utf-8")
        + b"\r\nuser-owned footer\r\n"
    )

    facts = codex_adapter._project_definition_facts(root)
    assert facts["instruction_definition_present"] == "YES"
    assert facts["project_definition_present"] == "YES"
    result = codex_adapter.init(root)
    assert result["changed"] is False
    assert result["session_restart_required"] is False


def test_exact_historical_managed_instruction_migrates(tmp_path: Path) -> None:
    root = repo(tmp_path)
    old = historical_blob('3485ec4:AGENTS.md')
    start = old.index(codex_adapter.MANAGED_START.encode("utf-8"))
    end = old.index(codex_adapter.MANAGED_END.encode("utf-8"), start) + len(codex_adapter.MANAGED_END)
    historical_block = old[start:end]
    assert hashlib.sha256(historical_block).hexdigest() == "d249d418ccf38ca3f159065715c3930d492682e93402025d067e99e2225b91fd"
    (root / "AGENTS.md").write_bytes(historical_block + b"\nuser text\n")
    result = codex_adapter.init(root)
    assert "AGENTS.md" in result["files"]
    assert "AGENTS.md" not in result["manual_action_required"]
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == codex_adapter.render_managed() + "user text\n"


def test_11e0cc9_generated_managed_instruction_upgrades_without_claiming_user_edits(tmp_path: Path) -> None:
    root = repo(tmp_path)
    published = historical_blob('11e0cc9:AGENTS.md')
    start = published.index(codex_adapter.MANAGED_START.encode("utf-8"))
    end = published.index(codex_adapter.MANAGED_END.encode("utf-8"), start) + len(codex_adapter.MANAGED_END)
    historical_block = published[start:end]
    assert hashlib.sha256(historical_block).hexdigest() == "3c1e3475797d0c9270d9adafa210492b8b305748f5e7bd7fc9411752f74d959d"
    instruction = root / "AGENTS.md"
    instruction.write_bytes(b"user prefix\n" + historical_block + b"\nuser suffix\n")
    assert codex_adapter._managed_agents_state(instruction.read_text(encoding="utf-8")) == "legacy"

    result = codex_adapter.init(root)
    assert "AGENTS.md" in result["files"]
    assert "AGENTS.md" not in result["manual_action_required"]
    assert instruction.read_bytes() == b"user prefix\n" + codex_adapter.render_managed().encode("utf-8") + b"user suffix\n"

    instruction.write_bytes(b"user prefix\n" + historical_block.replace(b"Startup contract:", b"Edited startup contract:", 1) + b"\nuser suffix\n")
    before = instruction.read_bytes()
    assert codex_adapter._managed_agents_state(instruction.read_text(encoding="utf-8")) == "user"
    result = codex_adapter.init(root)
    assert "AGENTS.md" in result["manual_action_required"]
    assert instruction.read_bytes() == before


def _owned_task_start(root: Path, *args: object, session: str = "controller-session") -> dict[str, object]:
    started = core.task_start(root, *args)
    lifecycle_module.record_task_start_owner(root, started["task_id"], hashlib.sha256(session.encode("utf-8")).hexdigest())
    return started


def test_8a3fe930_managed_block_and_role_pack_upgrade_only_exact_bytes(tmp_path: Path) -> None:
    root = repo(tmp_path)
    old = historical_blob('8a3fe930:AGENTS.md')
    start = old.index(codex_adapter.MANAGED_START.encode("utf-8"))
    end = old.index(codex_adapter.MANAGED_END.encode("utf-8"), start) + len(codex_adapter.MANAGED_END)
    block = old[start:end]
    pack = historical_blob('8a3fe930:docs/thaliris-role-packs.md')
    assert hashlib.sha256(block).hexdigest() == "96102e74cd2812e2f06382173807939c79e856371180f94c1413ba8e26e8facb"
    assert hashlib.sha256(pack).hexdigest() == "4ee70a3c36b2c76d74c03179359181dfd34c96bbfae5bf1e5e7ee1c71b6f13d7"
    instruction = root / "AGENTS.md"
    role_pack = root / "docs" / "thaliris-role-packs.md"
    instruction.write_bytes(block + b"\nuser text\n")
    role_pack.write_bytes(pack)
    assert codex_adapter._managed_agents_state(instruction.read_text(encoding="utf-8")) == "legacy"
    assert codex_adapter._role_pack_state(role_pack.read_bytes()) == "legacy"

    result = codex_adapter.init(root)
    assert {"AGENTS.md", "docs/thaliris-role-packs.md"} <= set(result["files"])
    assert instruction.read_text(encoding="utf-8") == codex_adapter.render_managed() + "user text\n"
    assert role_pack.read_bytes() == codex_adapter.render_role_packs().encode("utf-8")

    edited_block = block.replace(b"Codex is the runtime.", b"Codex is the edited runtime.")
    assert edited_block != block
    instruction.write_bytes(edited_block + b"\nuser text\n")
    edited_pack = pack + b"\nuser edit\n"
    role_pack.write_bytes(edited_pack)
    assert codex_adapter._managed_agents_state(instruction.read_text(encoding="utf-8")) == "user"
    assert codex_adapter._role_pack_state(role_pack.read_bytes()) == "user"

    guarded = codex_adapter.init(root)
    assert instruction.read_bytes() == edited_block + b"\nuser text\n"
    assert role_pack.read_bytes() == edited_pack
    assert guarded["manual_action_required"] == ["AGENTS.md"]
    assert guarded["preserved_manual_followup"] == ["docs/thaliris-role-packs.md"]


def hook_payload(**values: object) -> dict[str, object]:
    # Managed lifecycle tests exercise the concrete named profile.  Ordinary
    # worker remains covered separately in the NO_TASK transparency test.
    tool_input = values.get("tool_input")
    if isinstance(tool_input, dict) and tool_input.get("agent_type") == "worker":
        values["tool_input"] = {**tool_input, "agent_type": "thaliris-implementer"}
    if values.get("agent_type") == "worker":
        values["agent_type"] = "thaliris-implementer"
    return {"session_id": "controller-session", "turn_id": "controller-turn", **values}


def lifecycle(root: Path) -> dict[str, object]:
    path = next((root / ".context" / "audit" / "lifecycle").glob("*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def spawn_start(root: Path, agent_id: str, agent_type: str = "worker") -> None:
    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="spawn_agent",
        tool_input={"fork_turns": "none", "agent_type": agent_type, "message": f"task for {agent_id}"},
    )) == ""
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id=agent_id, agent_type=agent_type)) == ""


def spawn_start_with_host_task_name(root: Path, task_name: str, agent_id: str) -> None:
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "PostToolUse", {
        **spawn, "tool_response": json.dumps({"task_name": task_name}),
    }) == ""
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id=agent_id, agent_type="worker")) == ""


def stop(root: Path, agent_id: str, agent_type: str = "worker") -> None:
    assert handle_hook(root, "SubagentStop", hook_payload(agent_id=agent_id, agent_type=agent_type)) == ""


def reconcile(root: Path, agent_id: str, status: object) -> None:
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response={"agents": [{"agent_name": agent_id, "agent_status": status}]},
    )) == ""


def test_subagent_start_binds_explicit_handoff_without_injecting_projection(tmp_path: Path) -> None:
    root = repo(tmp_path)
    start_input = root.parent / "task-input.json"
    start_input.write_text(json.dumps({
        "records": [
            {"id": "old-unknown", "kind": "unknown", "text": "OLD_UNKNOWN"},
            {"id": "old-decision", "kind": "decision", "text": "OLD_DECISION"},
        ],
    }), encoding="utf-8")
    started = _owned_task_start(root, "single handoff", None, str(start_input))
    artifact = root / "private.md"
    artifact.write_text("ARTIFACT_PRIVATE_SENTINEL", encoding="utf-8")
    registered = core.task_artifact(
        root,
        started["revision"],
        "private-notes",
        "private.md",
        "private investigation notes",
        producer="implementer",
    )

    handoff = "SELECTED_FACT HANDOFF_SENTINEL; artifact pointer: private-notes"
    spawn = hook_payload(
        tool_name="spawn_agent",
        tool_input={"fork_turns": "none", "agent_type": "worker", "message": handoff},
    )
    assert handle_hook(root, "PreToolUse", spawn) == ""
    start_output = handle_hook(
        root,
        "SubagentStart",
        hook_payload(agent_id="child-one", agent_type="worker"),
    )

    # The native spawn message is already delivered by Codex. The adapter
    # must not return a second task-specific context payload.
    assert start_output == ""
    record = lifecycle(root)["children"][0]
    assert record["handoff_bound"] is True
    assert record["task_revision"] == registered["revision"]
    assert record["payload_hash"] == hashlib.sha256(handoff.encode("utf-8")).hexdigest()
    serialized = json.dumps(record)
    for unselected in ("OLD_UNKNOWN", "OLD_DECISION", "ARTIFACT_PRIVATE_SENTINEL"):
        assert unselected not in serialized
    start_handlers = hook_spec()["hooks"]["SubagentStart"][0]["hooks"]
    assert all("additionalContextLimit" not in handler for handler in start_handlers)


def test_session_start_points_to_root_navigation_without_injecting_map(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    (root / ".agent-memory" / "promoted").mkdir(parents=True, exist_ok=True)
    for index in range(100):
        (root / ".agent-memory" / "promoted" / f"doc-{index}.md").write_bytes(
            core._entry(f"Doc {index}", f"PRIVATE_BODY_{index}", evidence="NONE")
        )
    target = root / ".agent-memory" / "model-tree" / "deep" / "target.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(core._entry("Target", "DECISION_CHANGING_BODY", evidence="NONE"))
    (root / ".agent-memory" / "INDEX.md").write_bytes(core._entry(
        "Global map",
        "Implementation target: [Target](model-tree/deep/target.md)",
        evidence="NONE",
    ))

    def no_recursive_scan(*args, **kwargs):
        raise AssertionError("SessionStart catalog must not recursively scan durable documents")

    monkeypatch.setattr(Path, "rglob", no_recursive_scan)
    output = json.loads(handle_hook(root, "SessionStart", hook_payload(source="resume")))
    context = output["hookSpecificOutput"]["additionalContext"]
    assert len(context.encode("utf-8")) < 1024
    assert ".agent-memory/INDEX.md" in context
    assert ".milestones/INDEX.md" in context
    assert "explicitly read the root navigation" in context
    assert "model-tree/deep/target.md" not in context
    assert "PRIVATE_BODY" not in context
    assert "DECISION_CHANGING_BODY" not in context

    # The global map supplies the exact path, so one explicit retrieval call
    # returns the selected document without intermediate catalog traversal.
    fetched = core.document_get(root, [".agent-memory/model-tree/deep/target.md"])
    assert len(fetched["documents"]) == 1
    assert "DECISION_CHANGING_BODY" in fetched["documents"][0]["body"]

    child_output = handle_hook(root, "SubagentStart", hook_payload(
        source="resume", agent_id="unmanaged-child", agent_type="worker",
    ))
    assert child_output == ""


def test_generated_instruction_full_equality_and_working_copy_ownership(tmp_path: Path) -> None:
    root = repo(tmp_path)
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == codex_adapter.render_managed()
    repository = Path(__file__).resolve().parents[1]
    text = (repository / "AGENTS.md").read_text(encoding="utf-8")
    start = text.index(codex_adapter.MANAGED_START)
    end = text.index(codex_adapter.MANAGED_END, start) + len(codex_adapter.MANAGED_END)
    checked_in = text[start:end] + "\n"
    if checked_in != codex_adapter.MANAGED:
        assert codex_adapter._managed_agents_state(text) == "user"
        writes, manual = codex_adapter._install_plan(repository)
        assert "AGENTS.md" not in writes
        assert "AGENTS.md" in manual


@pytest.mark.parametrize("timeout", [10_000, 30_000, 60_000, 120_000, 3_600_000])
def test_wait_capacity_does_not_promote_caller_duration(tmp_path: Path, monkeypatch, timeout) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "wait mechanics", None, None)
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {
        "status": "PASS",
        "effective_max_wait_timeout_ms": 120_000,
    })
    original_input = {"timeout_ms": timeout, "reason": "wait for child", "future": {"keep": True}}
    wait = hook_payload(tool_name="wait_agent", tool_input=original_input)

    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""
    assert wait["tool_input"] == original_input

    spawn = hook_payload(
        tool_name="spawn_agent",
        tool_input={"fork_turns": "none", "agent_type": "worker", "message": "explicit task"},
    )
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""
    assert wait["tool_input"] == original_input
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="wait_agent", tool_input={"timeout_ms": 120_000},
        tool_response={"timed_out": True},
    )) == ""
    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""
    assert wait["tool_input"] == original_input


def test_completed_child_does_not_trigger_another_managed_wait(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "completed wait dependency", None, None)
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {
        "status": "PASS", "effective_max_wait_timeout_ms": 120_000,
    })
    task_name, agent_id = "/root/completed-child", "native-completed-child"
    spawn_start_with_host_task_name(root, task_name, agent_id)
    stop(root, agent_id)
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response=json.dumps({"agents": [
            {"agent_name": task_name, "agent_status": {"completed": "FINAL"}},
        ]}),
    )) == ""
    wait = hook_payload(tool_name="wait_agent", tool_input={"timeout_ms": 30_000})
    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""


def test_unavailable_effective_wait_maximum_preserves_legal_timeout(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "wait mechanics", None, None)
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {
        "status": "PASS", "release_hard_max_wait_timeout_ms": 3_600_000,
        "effective_max_wait_timeout_ms": "UNAVAILABLE",
    })
    spawn = hook_payload(tool_name="spawn_agent", tool_input={"fork_turns": "none", "agent_type": "worker", "message": "explicit task"})
    assert handle_hook(root, "PreToolUse", spawn) == ""
    wait = hook_payload(tool_name="wait_agent", tool_input={"timeout_ms": 30_000})
    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""


@pytest.mark.parametrize("host_status", ["UNKNOWN", "UNSUPPORTED"])
def test_unknown_or_unsupported_host_does_not_normalize_pending_wait(tmp_path: Path, monkeypatch, host_status: str) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "unknown wait host", None, None)
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {
        "status": host_status, "effective_max_wait_timeout_ms": "UNAVAILABLE",
    })
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "explicit task",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    wait = hook_payload(tool_name="wait_agent", tool_input={"timeout_ms": 30_000})
    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""


def test_no_task_does_not_normalize_wait_even_with_known_host(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {
        "status": "PASS", "effective_max_wait_timeout_ms": 3_600_000,
    })
    wait = hook_payload(tool_name="wait_agent", tool_input={"timeout_ms": 30_000})
    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""


def test_codex_01551_wait_capability_is_version_pinned(monkeypatch) -> None:
    class Version:
        returncode = 0
        stdout = "codex-cli 0.155.1\n"
        stderr = ""

    codex_adapter._host_wait_mode_cached.cache_clear()
    monkeypatch.setattr(codex_adapter.subprocess, "run", lambda *args, **kwargs: Version())
    capability = codex_adapter.host_explicit_blocking_wait("codex-0.155-test")
    assert capability == {
        "status": "PASS", "version": "0.155.1", "min_wait_timeout_ms": 10_000,
        "default_wait_timeout_ms": 30_000, "release_hard_max_wait_timeout_ms": 3_600_000,
        "effective_max_wait_timeout_ms": "UNAVAILABLE", "explicit_timeout_supported": True,
    }
    assert codex_adapter.native_child_completion_reenters_root("codex-0.155-test") == "UNSUPPORTED"
    codex_adapter._host_wait_mode_cached.cache_clear()


def test_exact_current_codex_alpha_wait_capability_is_source_pinned(monkeypatch) -> None:
    class Version:
        returncode = 0
        stdout = "codex-cli 0.155.0-alpha.9.2\n"
        stderr = ""

    codex_adapter._host_wait_mode_cached.cache_clear()
    monkeypatch.setattr(codex_adapter.subprocess, "run", lambda *args, **kwargs: Version())
    capability = codex_adapter.host_explicit_blocking_wait("codex-current-alpha-test")
    assert capability == {
        "status": "PASS", "version": "0.155.0-alpha.9.2", "min_wait_timeout_ms": 10_000,
        "default_wait_timeout_ms": 30_000, "release_hard_max_wait_timeout_ms": 3_600_000,
        "effective_max_wait_timeout_ms": "UNAVAILABLE", "explicit_timeout_supported": True,
    }
    assert codex_adapter.native_child_completion_reenters_root("codex-current-alpha-test") == "UNKNOWN"
    assert codex_adapter.selected_continuation_mode(Path("."), "codex-current-alpha-test") == "BLOCKING_WAIT"
    codex_adapter._host_wait_mode_cached.cache_clear()


def test_release_pinned_host_does_not_normalize_with_unknown_turn_cap(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "pinned blocking wait", None, None)

    monkeypatch.setattr(codex_adapter, "host_wait_mode", lambda _executable=None: {
        "status": "PASS", "version": "0.155.1", "min": 10_000,
        "default": 30_000, "max": 3_600_000,
        "explicit_timeout_supported": True,
        "native_completion_reenters_root": "UNSUPPORTED",
    })
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "explicit task",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    original_input = {"timeout_ms": 60_000, "future_argument": {"keep": True}}
    wait = hook_payload(tool_name="wait_agent", tool_input=original_input)

    assert codex_adapter.audit_hook(root, "PreToolUse", wait) == ""
    assert wait["tool_input"] == original_input


@pytest.mark.parametrize("version", ["0.153.4", "0.154.0"])
def test_historical_codex_wait_capabilities_remain_exactly_pinned(monkeypatch, version: str) -> None:
    class Version:
        returncode = 0
        stdout = f"codex-cli {version}\n"
        stderr = ""

    codex_adapter._host_wait_mode_cached.cache_clear()
    monkeypatch.setattr(codex_adapter.subprocess, "run", lambda *args, **kwargs: Version())
    capability = codex_adapter.host_explicit_blocking_wait("codex-pinned-test")
    assert capability["version"] == version
    assert capability["release_hard_max_wait_timeout_ms"] == 3_600_000
    assert capability["effective_max_wait_timeout_ms"] == "UNAVAILABLE"
    codex_adapter._host_wait_mode_cached.cache_clear()


@pytest.mark.parametrize("version", ["0.153.4", "0.154.0", "0.155.1"])
@pytest.mark.parametrize("suffix", ["-alpha", "-dev", "-nightly"])
def test_prerelease_codex_wait_capabilities_fail_closed(monkeypatch, version: str, suffix: str) -> None:
    class Version:
        returncode = 0
        stdout = f"codex-cli {version}{suffix}\n"
        stderr = ""

    codex_adapter._host_wait_mode_cached.cache_clear()
    monkeypatch.setattr(codex_adapter.subprocess, "run", lambda *args, **kwargs: Version())
    capability = codex_adapter.host_explicit_blocking_wait("codex-prerelease-test")
    assert capability["status"] != "PASS"
    assert capability["host"]["status"] != "PASS"
    codex_adapter._host_wait_mode_cached.cache_clear()


def test_future_codex_wait_capability_is_conservative(monkeypatch) -> None:
    class Version:
        returncode = 0
        stdout = "codex-cli 0.155.2\n"
        stderr = ""

    codex_adapter._host_wait_mode_cached.cache_clear()
    monkeypatch.setattr(codex_adapter.subprocess, "run", lambda *args, **kwargs: Version())
    capability = codex_adapter.host_explicit_blocking_wait("codex-future-test")
    assert capability["status"] == "UNKNOWN"
    assert codex_adapter.selected_continuation_mode(Path("."), "codex-future-test") == "UNAVAILABLE"
    codex_adapter._host_wait_mode_cached.cache_clear()


def test_production_hooks_record_hashes_without_model_audit_or_correction(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "telemetry only", None, None)
    prompt = "ROOT_PRIVATE_PROMPT"
    handoff = "CHILD_PRIVATE_HANDOFF"

    assert handle_hook(root, "UserPromptSubmit", hook_payload(prompt=prompt)) == ""
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="spawn_agent",
        tool_input={"fork_turns": "none", "agent_type": "worker", "message": handoff},
        tool_response={"success": True},
    )) == ""
    assert handle_hook(root, "Stop", hook_payload()) == ""

    runtime_path = next((root / ".context" / "audit").glob("*/runtime.json"))
    runtime_text = runtime_path.read_text(encoding="utf-8")
    runtime = json.loads(runtime_text)
    assert prompt not in runtime_text and handoff not in runtime_text
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() in runtime["root_prompt_hashes"]
    assert runtime["delegation_telemetry"][0]["payload_hash"] == hashlib.sha256(handoff.encode("utf-8")).hexdigest()

    source = Path(__import__("thaliris_codex.lifecycle", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    for removed in ("_invoke_fresh_auditor", "task_close_audit", "AUDITOR_INSTRUCTION"):
        assert removed not in source


def test_user_prompt_does_not_clear_pending_spawn_reservation(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "causal reservation", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    pending = lifecycle(root)["pending_authorized_spawn"]
    assert handle_hook(root, "UserPromptSubmit", hook_payload(prompt="new user input")) == ""
    assert lifecycle(root)["pending_authorized_spawn"] == pending


def test_active_controller_uses_only_the_mechanical_tool_allowlist(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "mechanical guard", None, None)
    assert hook_spec()["hooks"]["PreToolUse"][0]["matcher"] == "*"

    for payload in (
        hook_payload(tool_name="Bash", tool_input={"command": "rg -n architecture src"}),
        hook_payload(tool_name="Bash", tool_input={"command": "pytest -q"}),
        hook_payload(tool_name="apply_patch", tool_input={}),
        hook_payload(tool_name="mcp__example__read", tool_input={}),
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", payload))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="Bash", tool_input={"command": "thaliris task-status"},
    )) == ""
    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="Bash", tool_input={"command": "thaliris task-show"},
    )) == ""
    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="Bash", tool_input={"command": "thaliris task-get R1"},
    )) == ""
    denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(
        tool_name="Bash", tool_input={"command": r"C:\untrusted\thaliris.exe task-status"},
    )))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    for command in (
        "thaliris init",
        "thaliris uninstall",
        "thaliris rollback backup-id",
        "thaliris task-start another-task",
        "thaliris stale",
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(
            tool_name="Bash", tool_input={"command": command},
        )))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    for name in ("wait_agent", "list_agents", "interrupt_agent"):
        assert handle_hook(root, "PreToolUse", hook_payload(tool_name=name, tool_input={})) == ""
    for name in ("followup_task", "send_message", "send_input"):
        denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(tool_name=name, tool_input={"target": "old-child"})))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="spawn_agent",
        tool_input={"fork_turns": "none", "agent_type": "worker", "message": "fresh handoff"},
    )) == ""


@pytest.mark.parametrize("command", ["thaliris task-status", "thaliris.exe task-status", "thaliris.cmd task-status"])
def test_managed_control_accepts_only_direct_canonical_thaliris(tmp_path: Path, command: str) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "canonical executable", None, None)
    assert handle_hook(root, "PreToolUse", hook_payload(tool_name="Bash", tool_input={"command": command})) == ""
    for rejected in (
        "context task-status", "uv run thaliris task-status", "python -m thaliris task-status",
        "cmd /c thaliris task-status", "powershell thaliris task-status", "my-thaliris task-status",
        r"C:\untrusted\thaliris.exe task-status",
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(tool_name="Bash", tool_input={"command": rejected})))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny", rejected


def test_pinned_absolute_thaliris_is_accepted_but_legacy_handlers_only_migrate(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    executable = tmp_path / "trusted-thaliris.exe"
    executable.write_bytes(b"trusted executable bytes")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    monkeypatch.setenv("THALIRIS_EXECUTABLE", str(executable))
    monkeypatch.setenv("THALIRIS_EXECUTABLE_SHA256", digest)
    _owned_task_start(root, "pinned executable", None, None)
    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="Bash", tool_input={"command": f'"{executable}" task-status'},
    )) == ""
    legacy = {"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "context audit-hook SessionStart", "timeout": 60},
        {"type": "command", "command": "context audit-hook SessionStart --user-wrapper", "timeout": 60},
    ]}]}}
    merged, changed = lifecycle_module.merge_hooks(legacy)
    assert changed
    handlers = merged["hooks"]["SessionStart"]
    assert any(item == lifecycle_module.hook_spec()["hooks"]["SessionStart"][0] for item in handlers)
    assert any(item["hooks"][0]["command"].endswith("--user-wrapper") for item in handlers if item.get("hooks"))
    cleaned, removed = lifecycle_module.remove_hooks(legacy)
    assert removed
    assert cleaned["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith("--user-wrapper")


def test_pinned_executable_renders_hook_and_migrates_exact_legacy_shape(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "pinned tool.exe"
    executable.write_bytes(b"pinned bytes")
    monkeypatch.setenv("THALIRIS_EXECUTABLE", str(executable))
    monkeypatch.setenv("THALIRIS_EXECUTABLE_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest())
    command = lifecycle_module.hook_spec()["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert command.endswith(f" audit-hook SessionStart --managed-hook-abi {lifecycle_module.MANAGED_HOOK_ABI}")
    assert str(executable) in command
    legacy = {"hooks": {"SessionStart": [{"hooks": [{
        "type": "command", "command": f'"{executable}" audit-hook SessionStart', "timeout": 60,
    }]}]}}
    merged, changed = lifecycle_module.merge_hooks(legacy)
    assert changed
    handlers = [handler for entry in merged["hooks"]["SessionStart"] for handler in entry.get("hooks", [])]
    assert handlers == [lifecycle_module.hook_spec()["hooks"]["SessionStart"][0]["hooks"][0]]


def test_valid_pin_upgrades_each_canonical_handler_without_manual_cleanup(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "pinned tool.exe"
    executable.write_bytes(b"pinned bytes")
    monkeypatch.setenv("THALIRIS_EXECUTABLE", str(executable))
    monkeypatch.setenv("THALIRIS_EXECUTABLE_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest())
    legacy = {"hooks": {
        event: [{"hooks": [{"type": "command", "command": f"thaliris audit-hook {event}", "timeout": 60}]}]
        for event in lifecycle_module.HOOK_EVENTS
    }}

    merged, changed = lifecycle_module.merge_hooks(legacy)

    assert changed
    assert not lifecycle_module.legacy_managed_handler_cleanup_required(legacy)
    for event in lifecycle_module.HOOK_EVENTS:
        assert merged["hooks"][event] == lifecycle_module.hook_spec()["hooks"][event]


def test_valid_pin_bootstraps_without_path_resolution(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    executable_dir = tmp_path / "pinned tools"
    executable_dir.mkdir()
    executable = executable_dir / "thaliris.exe"
    executable.write_bytes(b"pinned bytes")
    monkeypatch.setenv("THALIRIS_EXECUTABLE", str(executable))
    monkeypatch.setenv("THALIRIS_EXECUTABLE_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest())
    monkeypatch.setattr(lifecycle_module.shutil, "which", lambda _name: None)
    result = codex_adapter.init(root)
    assert result["canonical_executable_available"] == "YES"
    assert "canonical_executable_unavailable" not in result["manual_action_required"]


def test_ambiguous_legacy_absolute_hook_requires_manual_cleanup(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    executable_dir = tmp_path / "pinned tools"
    executable_dir.mkdir()
    executable = executable_dir / "thaliris.exe"
    executable.write_bytes(b"pinned bytes")
    monkeypatch.setenv("THALIRIS_EXECUTABLE", str(executable))
    monkeypatch.setenv("THALIRIS_EXECUTABLE_SHA256", hashlib.sha256(executable.read_bytes()).hexdigest())
    hooks = {"hooks": {"SessionStart": [{"hooks": [{
        "type": "command", "command": f'"{executable}" audit-hook SessionStart --extra', "timeout": 60,
    }]}]}}
    (root / ".codex" / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
    result = codex_adapter.init(root)
    assert "legacy_project_hook_manual_cleanup_required" in result["manual_action_required"]
    installed = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    commands = [handler["command"] for entry in installed["hooks"]["SessionStart"] for handler in entry.get("hooks", [])]
    assert f'"{executable}" audit-hook SessionStart --extra' in commands


@pytest.mark.parametrize("command", [
    r'"C:\\old tools\\context.exe" audit-hook SessionStart --extra',
    r'"C:\\old tools\\thaliris.exe" audit-hook SessionStart --extra',
])
def test_recognizable_absolute_legacy_hook_with_spaces_requires_manual_cleanup(command: str) -> None:
    handler = {"type": "command", "command": command, "timeout": 60}
    assert lifecycle_module._ambiguous_legacy_managed_handler(handler, "SessionStart")


def test_unrelated_absolute_audit_hook_is_not_manual_cleanup() -> None:
    handler = {"type": "command", "command": r'"C:\\tools\\other.exe" audit-hook SessionStart', "timeout": 60}
    assert not lifecycle_module._ambiguous_legacy_managed_handler(handler, "SessionStart")


@pytest.mark.parametrize("command", [
    "context.cmd audit-hook SessionStart --extra",
    r'"C:\\old tools\\thaliris.cmd" audit-hook SessionStart --extra',
    r'cmd /c "C:\\old tools\\context.cmd audit-hook SessionStart"',
])
def test_non_executable_aliases_do_not_trigger_manual_cleanup(command: str) -> None:
    handler = {"type": "command", "command": command, "timeout": 60}
    assert not lifecycle_module._ambiguous_legacy_managed_handler(handler, "SessionStart")


@pytest.mark.parametrize("command", [
    r'cmd /c "C:\old\thaliris.exe audit-hook SessionStart"',
    "powershell -NoProfile -Command \"& 'C:\\old\\thaliris.exe' audit-hook SessionStart\"",
    "pwsh -c \"& 'C:\\old\\context.exe' audit-hook SessionStart\"",
])
def test_wrapped_legacy_hook_requires_manual_cleanup_without_migration(tmp_path: Path, command: str) -> None:
    root = repo(tmp_path)
    hooks = {"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": command, "timeout": 60},
    ]}]}}
    (root / ".codex" / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")

    result = codex_adapter.init(root)

    assert "legacy_project_hook_manual_cleanup_required" in result["manual_action_required"]
    installed = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    commands = [handler["command"] for entry in installed["hooks"]["SessionStart"] for handler in entry.get("hooks", [])]
    assert command in commands


@pytest.mark.parametrize("command", [
    'cmd /c "echo audit-hook SessionStart"',
    'powershell -Command "& \'C:\\old\\other.exe\' audit-hook SessionStart"',
    'pwsh -c "& \'C:\\old\\thaliris.exe\' audit-hook Stop"',
])
def test_wrapper_cleanup_signature_does_not_match_unrelated_commands(command: str) -> None:
    assert not lifecycle_module._wrapped_audit_hook_signature(command, "SessionStart")


def test_session_start_does_not_inject_large_root_map_or_document_body(tmp_path: Path) -> None:
    root = repo(tmp_path)
    target = root / ".agent-memory" / "selected.md"
    target.write_bytes(core._entry("Selected", "PRIVATE_DOCUMENT_BODY", evidence="NONE"))
    route = "[Selected](selected.md)\n\n" + ("model-authored-routing-hint " * 160)
    index = root / ".agent-memory" / "INDEX.md"
    index.write_bytes(core._entry("Global map", route, evidence="NONE"))
    assert core.DURABLE_INDEX_RECOMMENDED_BYTES < index.stat().st_size < core.DURABLE_INDEX_HARD_MAX_BYTES

    output = json.loads(handle_hook(root, "SessionStart", hook_payload(source="startup")))
    context = output["hookSpecificOutput"]["additionalContext"]
    assert ".agent-memory/INDEX.md" in context
    assert "model-authored-routing-hint" not in context
    assert "selected.md" not in context
    assert "PRIVATE_DOCUMENT_BODY" not in context


def test_task_start_recreates_missing_root_navigation_before_active(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".agent-memory" / "INDEX.md").unlink()
    (root / ".milestones" / "INDEX.md").unlink()
    started = _owned_task_start(root, "establish navigation", None, None)
    assert started["status"] == "ACTIVE"
    assert (root / ".agent-memory" / "INDEX.md").is_file()
    assert (root / ".milestones" / "INDEX.md").is_file()


def test_task_status_does_not_reread_navigation_automatically(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    calls: list[object] = []

    def fail_catalog(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("task status must not read durable navigation")

    monkeypatch.setattr(core, "catalog", fail_catalog)
    _owned_task_start(root, "no automatic navigation reread", None, None)
    core.task_status(root)
    assert calls == []


def test_no_task_is_transparent_to_ordinary_spawn(tmp_path: Path) -> None:
    root = repo(tmp_path)
    assert handle_hook(root, "PreToolUse", {
        "session_id": "controller-session", "turn_id": "controller-turn",
        "tool_name": "spawn_agent",
        "tool_input": {"agent_type": "worker", "message": "ordinary Codex child"},
    }) == ""
    assert not (root / ".context" / "audit" / "lifecycle").exists()


@pytest.mark.parametrize("agent_type", ("worker", "explorer"))
def test_no_task_child_worker_and_explorer_execution_is_transparent(tmp_path: Path, agent_type: str) -> None:
    root = repo(tmp_path)
    assert handle_hook(root, "PreToolUse", {
        "session_id": "ordinary-session", "turn_id": "ordinary-turn",
        "agent_id": f"ordinary-{agent_type}", "agent_type": agent_type,
        "tool_name": "Bash", "tool_input": {"command": "Set-Content ordinary.txt value"},
    }) == ""


@pytest.mark.parametrize("agent_type", ("worker", "explorer"))
def test_active_managed_spawn_rejects_ordinary_codex_agent_types(tmp_path: Path, agent_type: str) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "named roles only", None, None)
    payload = {
        "session_id": "controller-session", "turn_id": "controller-turn",
        "tool_name": "spawn_agent",
        "tool_input": {"fork_turns": "none", "agent_type": agent_type, "message": "handoff"},
    }
    assert "THALIRIS_MANAGED_AGENT_REQUIRED" in handle_hook(root, "PreToolUse", payload)


def test_active_spawn_rejects_conflicting_or_unsupported_native_type_fields(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "exact native role fields", None, None)
    for fields in (
        {"agent_type": "worker", "agentType": "thaliris-reviewer"},
        {"agent_type": "thaliris-implementer", "agentType": "thaliris-reviewer"},
        {"agent_type": "worker"},
        {"agentType": "explorer"},
        {"agent_type": "worker", "agentType": "explorer"},
        {"agent_type": "thaliris-implementer", "agentType": 1},
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", {
            "session_id": "controller-session", "turn_id": "controller-turn",
            "tool_name": "spawn_agent",
            "tool_input": {"fork_turns": "none", "message": "handoff", **fields},
        }))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "THALIRIS_MANAGED_AGENT_REQUIRED" in denied["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize(("agent_type", "command", "decision", "reason"), (
    ("worker", "Set-Content unbound.txt value", "allow", None),
    ("explorer", "Get-Content unbound.txt", "allow", None),
    ("explorer", "Set-Content unbound.txt value", "allow", None),
    ("thaliris-implementer", "Set-Content unbound.txt value", "allow", None),
    ("thaliris-verifier", "Set-Content unbound.txt value", "deny", "THALIRIS_READONLY_ACTOR"),
))
def test_active_unbound_native_children_use_ordinary_role_rules_without_managed_authority(
    tmp_path: Path, agent_type: str, command: str, decision: str, reason: str | None,
) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "unbound child", None, None)
    result = handle_hook(root, "PreToolUse", {
        "session_id": "unbound-session", "turn_id": "unbound-turn",
        "agent_id": f"unbound-{agent_type}", "agent_type": agent_type,
        "tool_name": "Bash", "tool_input": {"command": command},
    })
    if decision == "allow":
        assert result == ""
    else:
        denied = json.loads(result)
        assert denied["hookSpecificOutput"]["permissionDecision"] == decision
        assert reason in denied["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("agent_type", (
    "thaliris-investigator", "thaliris-implementer", "thaliris-reviewer",
    "thaliris-curator", "thaliris-reasoning-specialist", "thaliris-verifier",
))
def test_all_exact_bound_roles_pass_active_child_lifecycle(tmp_path: Path, agent_type: str) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "bound exact roles", None, None, session=f"{agent_type}-session")
    payload = {
        "session_id": f"{agent_type}-session", "turn_id": f"{agent_type}-turn",
        "tool_name": "spawn_agent",
        "tool_input": {"fork_turns": "none", "agent_type": agent_type, "message": "handoff"},
    }
    assert handle_hook(root, "PreToolUse", payload) == ""
    child = {
        "session_id": payload["session_id"], "turn_id": payload["turn_id"],
        "agent_id": f"{agent_type}-child", "agent_type": agent_type,
    }
    assert handle_hook(root, "SubagentStart", child) == ""
    assert handle_hook(root, "PreToolUse", {
        **child, "tool_name": "Bash", "tool_input": {"command": "Get-Content README.md"},
    }) == ""
    assert lifecycle(root)["children"][-1]["handoff_bound"] is True


def test_adapter_task_start_records_controller_actor(tmp_path: Path, monkeypatch) -> None:
    root = repo(tmp_path)
    initial = root.parent / "initial.json"
    initial.write_text(json.dumps({"records": [{"id": "R1", "kind": "note", "text": "initial"}]}), encoding="utf-8")
    monkeypatch.setattr(lifecycle_module, "consume_task_start_attestation", lambda *_args: None)
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "EVENT_DRIVEN")
    result = codex_adapter.task_start(root, "adapter actor", None, str(initial))
    assert result["status"] == "ACTIVE"
    assert core.task_show(root)["state"]["records"][0]["producer"] == "controller"


@pytest.mark.parametrize("agent_type", (
    "thaliris-investigator", "thaliris-curator", "thaliris-reasoning-specialist",
    "thaliris-implementer", "thaliris-verifier", "thaliris-reviewer",
))
def test_execution_role_extra_context_reads_are_telemetry_only(tmp_path: Path, agent_type: str) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "deviation telemetry", None, None)
    spawn_start(root, "reader-3", agent_type)
    child_read = hook_payload(
        agent_id="reader-3",
        agent_type=agent_type,
        tool_name="Bash",
        tool_input={"command": "thaliris task-show"},
    )
    assert handle_hook(root, "PreToolUse", child_read) == ""
    deviation = lifecycle(root)["protocol_deviations"][0]
    assert deviation["agent_id"] == "reader-3"
    assert deviation["agent_type"] == agent_type
    assert deviation["operation"] == "task-show"
    assert deviation["blocked"] is False

    assert "Protocol deviation" not in core.task_status(root)

    child_status = {**child_read, "tool_input": {"command": "thaliris task-status"}}
    rewrite = json.loads(handle_hook(root, "PreToolUse", child_status))
    assert rewrite["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert rewrite["hookSpecificOutput"]["updatedInput"]["command"].endswith("--suppress-protocol-notice")
    assert "Protocol deviation" not in cli._task_status(root, suppress_protocol_notice=True)
    assert "Protocol deviation" not in core.task_status(root)


def test_task_status_keeps_core_ledger_only_and_cli_consumes_one_shot_notice(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "cli notice", None, None)
    spawn_start(root, "reader", "thaliris-reviewer")
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="reader", agent_type="thaliris-reviewer", tool_name="Bash",
        tool_input={"command": "thaliris task-show"},
    )) == ""
    assert "Protocol deviation" not in core.task_status(root)
    assert "lifecycle" not in Path(core.__file__).read_text(encoding="utf-8")
    assert "Protocol deviation" not in cli._task_status(root, suppress_protocol_notice=True)
    assert "Protocol deviation" in cli._task_status(root, suppress_protocol_notice=False)
    assert "Protocol deviation" not in cli._task_status(root, suppress_protocol_notice=False)

@pytest.mark.parametrize(("agent_type", "expected_role"), (
    ("thaliris-reviewer", "reviewer"),
    ("thaliris-reasoning-specialist", "reasoning-specialist"),
    ("thaliris-curator", "curator"),
    ("thaliris-verifier", "verifier"),
))
def test_selected_roles_receive_one_bounded_aggregate_deviation_notice(
    tmp_path: Path, agent_type: str, expected_role: str,
) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "role-aware telemetry", None, None)
    spawn_start(root, "reader-1", agent_type)
    for operation in ("catalog", "document-get", "artifact-get"):
        assert handle_hook(root, "PreToolUse", hook_payload(
            agent_id="reader-1",
            agent_type=agent_type,
            tool_name="Bash",
            tool_input={"command": f"thaliris {operation} .agent-memory/INDEX.md"},
        )) == ""
    notice = cli._task_status(root, suppress_protocol_notice=False)["Protocol deviation"]
    assert "Protocol deviations (batched)" in notice
    assert f"{expected_role}=3" in notice
    assert ".agent-memory/INDEX.md" in notice
    assert len(notice.encode("utf-8")) < 1024
    assert "Protocol deviation" not in cli._task_status(root, suppress_protocol_notice=False)


def test_selected_role_records_actual_context_and_obvious_shell_durable_targets(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "actual durable targets", None, None)
    spawn_start(root, "reviewer-reader", "thaliris-reviewer")
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="reviewer-reader",
        agent_type="thaliris-reviewer",
        tool_name="Bash",
        tool_input={"command": "thaliris document-get .agent-memory/a.md .milestones/b.md"},
    )) == ""
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="reviewer-reader",
        agent_type="thaliris-reviewer",
        tool_name="Bash",
        tool_input={"command": "cat .agent-memory/reviews/old-review.md"},
    )) == ""
    state = lifecycle(root)
    targets = [item["target"] for item in state["protocol_deviations"]]
    assert targets == [
        ".agent-memory/a.md",
        ".milestones/b.md",
        ".agent-memory/reviews/old-review.md",
    ]
    notice = cli._task_status(root, suppress_protocol_notice=False)["Protocol deviation"]
    assert "reviewer=3" in notice
    assert ".agent-memory/a.md" in notice
    assert ".milestones/b.md" in notice
    assert ".agent-memory/reviews/old-review.md" in notice
    assert len(notice.encode("utf-8")) < 1024
    assert "Protocol deviation" not in cli._task_status(root, suppress_protocol_notice=False)


def test_investigator_obvious_shell_durable_read_is_telemetry_only(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "investigator durable read", None, None)
    spawn_start(root, "investigator-reader", "thaliris-investigator")
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="investigator-reader",
        agent_type="thaliris-investigator",
        tool_name="Bash",
        tool_input={"command": "rg needle .milestones/current/INDEX.md"},
    )) == ""
    state = lifecycle(root)
    assert state["protocol_deviations"][-1]["target"] == ".milestones/current/INDEX.md"
    assert state["protocol_deviations"][-1]["notice_delivered"] is True
    assert "Protocol deviation" not in core.task_status(root)


def test_reviewer_non_bash_durable_path_read_is_aggregated(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "reviewer durable read", None, None)
    spawn_start(root, "reviewer-reader", "thaliris-reviewer")
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="reviewer-reader",
        agent_type="thaliris-reviewer",
        tool_name="mcp__files__read",
        tool_input={"path": ".agent-memory/x.md"},
    )) == ""
    state = lifecycle(root)
    assert state["protocol_deviations"][-1]["target"] == ".agent-memory/x.md"
    assert state["protocol_deviations"][-1]["notice_delivered"] is False
    notice = cli._task_status(root, suppress_protocol_notice=False)["Protocol deviation"]
    assert "reviewer=1" in notice
    assert ".agent-memory/x.md" in notice


def test_investigator_non_bash_durable_path_read_is_telemetry_only(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "investigator durable read", None, None)
    spawn_start(root, "investigator-reader", "thaliris-investigator")
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="investigator-reader",
        agent_type="thaliris-investigator",
        tool_name="mcp__files__read",
        tool_input={"path": ".milestones/x.md"},
    )) == ""
    state = lifecycle(root)
    assert state["protocol_deviations"][-1]["target"] == ".milestones/x.md"
    assert state["protocol_deviations"][-1]["notice_delivered"] is True
    assert "Protocol deviation" not in cli._task_status(root, suppress_protocol_notice=False)


def test_one_generic_read_call_deduplicates_durable_targets(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "deduplicate durable read", None, None)
    spawn_start(root, "reviewer-reader", "thaliris-reviewer")
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="reviewer-reader",
        agent_type="thaliris-reviewer",
        tool_name="mcp__files__read",
        tool_input={"paths": [".agent-memory/x.md", ".agent-memory/x.md"]},
    )) == ""
    targets = [item["target"] for item in lifecycle(root)["protocol_deviations"]]
    assert targets == [".agent-memory/x.md"]


def test_protocol_deviation_ring_keeps_late_events_in_one_aggregate(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "deviation overflow", None, None)
    spawn_start(root, "reader", "thaliris-reviewer")
    for index in range(40):
        assert handle_hook(root, "PreToolUse", hook_payload(
            agent_id="reader",
            agent_type="thaliris-reviewer",
            tool_name="Bash",
        tool_input={"command": f"thaliris task-show --marker {index}"},
        )) == ""
    state = lifecycle(root)
    assert len(state["protocol_deviations"]) == 32
    assert state["protocol_deviation_overflow_count"] == 8
    assert state["protocol_deviation_counts"]["reviewer:allowed_read"] == 40
    notice = cli._task_status(root, suppress_protocol_notice=False)["Protocol deviation"]
    assert "reviewer=40" in notice
    assert "diagnostic ring overflow=8" in notice
    assert "Protocol deviation" not in cli._task_status(root, suppress_protocol_notice=False)


def test_child_control_state_mutation_is_blocked_and_recorded(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "child guard", None, None)
    spawn_start(root, "worker-1")
    mutation = hook_payload(
        agent_id="worker-1",
        agent_type="worker",
        tool_name="Bash",
        tool_input={"command": "thaliris task-update --role controller --base-revision 1 --input update.json"},
    )
    denied = json.loads(handle_hook(root, "PreToolUse", mutation))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    deviation = lifecycle(root)["protocol_deviations"][0]
    assert deviation["operation"] == "task-update"
    assert deviation["target"] == "thaliris task-update"
    assert deviation["blocked"] is True

    direct_write = hook_payload(
        agent_id="worker-1",
        agent_type="worker",
        tool_name="Bash",
        tool_input={"command": "Set-Content .context/state.json '{}'"},
    )
    denied = json.loads(handle_hook(root, "PreToolUse", direct_write))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert lifecycle(root)["protocol_deviations"][-1]["operation"] == "control-state-write"


def test_non_bash_control_state_mutation_tools_are_blocked_but_reads_and_repo_writes_are_allowed(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "non bash child guard", None, None)
    spawn_start(root, "worker-1")
    denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(
        agent_id="worker-1",
        agent_type="worker",
        tool_name="mcp__files__write",
        tool_input={"path": ".context/state.json", "content": "changed"},
    )))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert lifecycle(root)["protocol_deviations"][-1]["operation"] == "control-state-write"

    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="worker-1",
        agent_type="worker",
        tool_name="mcp__files__read",
        tool_input={"path": ".context/state.json"},
    )) == ""
    assert lifecycle(root)["protocol_deviations"][-1]["blocked"] is False

    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="worker-1",
        agent_type="worker",
        tool_name="mcp__files__write",
        tool_input={"path": "src/example.py", "content": "changed"},
    )) == ""


@pytest.mark.parametrize(("agent_type", "role", "model", "effort"), (
    ("thaliris-reviewer", "reviewer", "gpt-5.6-terra", "high"),
    ("thaliris-verifier", "verifier", "gpt-5.6-luna", "xhigh"),
))
def test_read_only_roles_make_no_native_sandbox_claim_and_obvious_writes_are_blocked(
    tmp_path: Path, agent_type: str, role: str, model: str, effort: str,
) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "read-only role guard", None, None)
    spawn_start(root, "read-only-1", agent_type)
    denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(
        agent_id="read-only-1",
        agent_type=agent_type,
        tool_name="apply_patch",
        tool_input={"patch": "*** Begin Patch\n*** Update File: src/a.py\n*** End Patch"},
    )))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    if role == "verifier":
        assert "THALIRIS_READONLY_ACTOR" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert handle_hook(root, "PreToolUse", hook_payload(
        agent_id="read-only-1",
        agent_type=agent_type,
        tool_name="mcp__files__read",
        tool_input={"path": ".agent-memory/read-only.md"},
    )) == ""
    profile = codex_adapter._agent_profile(agent_type, role, model, effort).decode()
    assert "sandbox_mode" not in profile


def test_task_start_requires_current_one_shot_hook_attestation(tmp_path: Path, monkeypatch, capsys) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(lifecycle_module, "managed_executable_health", lambda: {"canonical_executable_available": "YES", "canonical_executable_identity": "TEST"})
    codex_adapter.audit_hook(root, "SessionStart", {"session_id": "controller-session", "source": "startup", "cwd": str(root)})
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "native_child_completion_reenters_root", lambda: "UNSUPPORTED")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {"status": "PASS"})

    with pytest.raises(ValueError, match="MANAGED_CURRENT_SESSION_NOT_ATTESTED"):
        codex_adapter.task_start(root, "missing attestation", None, None)

    digest = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    pre = hook_payload(tool_name="Bash", tool_input={"command": f"thaliris task-start goal --controller-bridge-sha256 {digest}"})
    old_registration = json.loads(codex_adapter.audit_hook(root, "PreToolUse", pre))
    assert "MANAGED_CURRENT_SESSION_NOT_ATTESTED" in json.dumps(old_registration)
    old_abi_registration = json.loads(codex_adapter.audit_hook(root, "PreToolUse", pre, "thaliris-hook-abi-9"))
    assert "MANAGED_CURRENT_SESSION_NOT_ATTESTED" in json.dumps(old_abi_registration)
    rewritten = json.loads(codex_adapter.audit_hook(root, "PreToolUse", pre, lifecycle_module.MANAGED_HOOK_ABI))
    command = rewritten["hookSpecificOutput"]["updatedInput"]["command"]
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", command).group(1)
    assert cli.main(["--root", str(root), "task-start", "attested", "--controller-bridge-sha256", "0" * 64, "--hook-attestation", token]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "CONTROLLER_BRIDGE_REQUIRED"
    assert cli.main(["--root", str(root), "task-start", "attested", "--controller-bridge-sha256", digest, "--hook-attestation", token]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["status"] == "ACTIVE"
    assert started["managed_readiness"]["controller_activation_bridge"] == "ACTIVE"
    assert started["managed_readiness"]["host_instruction_activation"] == "UNKNOWN"
    with pytest.raises(ValueError, match="MANAGED_CURRENT_SESSION_NOT_ATTESTED"):
        codex_adapter.task_start(root, "reused", None, None, token, digest)


def test_powershell_call_operator_to_pinned_executable_mints_task_start_attestation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = repo(tmp_path / "repo")
    executable = tmp_path / "thaliris.exe"
    executable.write_bytes(b"exact test executable pin")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    monkeypatch.setenv(lifecycle_module.THALIRIS_EXECUTABLE_ENV, str(executable))
    monkeypatch.setenv(lifecycle_module.THALIRIS_EXECUTABLE_SHA256_ENV, executable_sha256)
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "native_child_completion_reenters_root", lambda: "UNSUPPORTED")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {"status": "PASS"})
    codex_adapter.audit_hook(
        root,
        "SessionStart",
        {"session_id": "powershell-session", "source": "startup", "cwd": str(root)},
    )

    digest = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    command = (
        f"& '{executable}' --root '{root}' task-start 'powershell direct route' "
        f"--controller-bridge-sha256 {digest}"
    )
    pre = hook_payload(
        session_id="powershell-session",
        tool_name="Bash",
        tool_input={"command": command},
    )
    rewritten = json.loads(
        codex_adapter.audit_hook(root, "PreToolUse", pre, lifecycle_module.MANAGED_HOOK_ABI)
    )
    updated_command = rewritten["hookSpecificOutput"]["updatedInput"]["command"]
    assert updated_command.startswith(command)
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", updated_command).group(1)

    assert cli.main(
        ["--root", str(root), "task-start", "powershell direct route", "--controller-bridge-sha256", digest, "--hook-attestation", token]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ACTIVE"


def test_direct_init_posttool_proof_admits_first_start_without_start_command_parsing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    executable = tmp_path / "thaliris.exe"
    executable.write_bytes(b"exact test executable pin")
    monkeypatch.setenv(lifecycle_module.THALIRIS_EXECUTABLE_ENV, str(executable))
    monkeypatch.setenv(lifecycle_module.THALIRIS_EXECUTABLE_SHA256_ENV, hashlib.sha256(executable.read_bytes()).hexdigest())
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    monkeypatch.setattr(codex_adapter, "native_child_completion_reenters_root", lambda: "UNSUPPORTED")
    monkeypatch.setattr(codex_adapter, "host_explicit_blocking_wait", lambda: {"status": "PASS"})
    codex_adapter.audit_hook(root, "SessionStart", {
        "session_id": "init-controller", "source": "startup", "cwd": str(root),
    })
    init_payload = hook_payload(
        session_id="init-controller", cwd=str(root), tool_name="functions.exec_command",
        tool_input={"cmd": f"& '{executable}' --root '{root}' init"},
    )
    assert codex_adapter.audit_hook(root, "PreToolUse", init_payload, lifecycle_module.MANAGED_HOOK_ABI) == ""
    initialized = codex_adapter.init(root)
    assert initialized["project_definition_present"] == "YES"
    post = json.loads(codex_adapter.audit_hook(root, "PostToolUse", {
        **init_payload, "tool_response": {"exit_code": 0, "output": json.dumps(initialized)},
    }, lifecycle_module.MANAGED_HOOK_ABI))
    specific = post["hookSpecificOutput"]
    assert specific["hookEventName"] == "PostToolUse"
    assert "updatedInput" not in specific
    token = re.search(r"--hook-attestation (v1\.[0-9a-f]{64}\.[A-Za-z0-9_-]{16,128})", specific["additionalContext"]).group(1)
    digest = initialized["controller_bridge_sha256"]
    start_command = f"powershell -NoProfile -Command \"& '{executable}' --root '{root}' task-start goal --controller-bridge-sha256 {digest} --hook-attestation {token}\""
    start_payload = hook_payload(session_id="init-controller", tool_name="functions.exec_command", tool_input={"cmd": start_command})
    assert lifecycle_module._context_operation(start_payload) is None
    assert codex_adapter.audit_hook(root, "PreToolUse", start_payload, lifecycle_module.MANAGED_HOOK_ABI) == ""
    assert cli.main(["--root", str(root), "task-start", "goal", "--controller-bridge-sha256", digest, "--hook-attestation", token]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["status"] == "ACTIVE"
    assert core.task_show(root)["state"]["schema_version"] == 7
    with pytest.raises(ValueError, match="MANAGED_CURRENT_SESSION_NOT_ATTESTED"):
        lifecycle_module.consume_task_start_attestation(root, token, digest)


def test_post_init_proof_requires_successful_direct_current_worktree_call(tmp_path: Path) -> None:
    root = repo(tmp_path / "repo")
    base = hook_payload(
        session_id="init-controller", cwd=str(root), tool_name="Bash",
        tool_input={"command": f"thaliris --root '{root}' init"},
        tool_response={"exit_code": 0},
    )
    for changes in (
        {"session_id": ""},
        {"tool_input": {"command": "thaliris init; Get-Date"}},
        {"tool_input": {"command": f"thaliris --root '{tmp_path}' init"}},
        {"tool_input": {"command": "Get-Date"}},
        {"tool_response": None},
        {"tool_response": {"exit_code": 1}},
        {"agent_id": "child", "agent_type": "thaliris-implementer"},
    ):
        assert codex_adapter.audit_hook(root, "PostToolUse", {**base, **changes}, lifecycle_module.MANAGED_HOOK_ABI) == ""
    assert codex_adapter.audit_hook(root, "PostToolUse", base, "thaliris-hook-abi-9") == ""


def test_unsupported_prerelease_after_valid_attestation_is_continuation_unavailable(tmp_path: Path, monkeypatch, capsys) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(lifecycle_module, "managed_executable_health", lambda: {"canonical_executable_available": "YES", "canonical_executable_identity": "TEST"})
    codex_adapter.audit_hook(root, "SessionStart", {"session_id": "controller-session", "source": "startup", "cwd": str(root)})

    class Version:
        returncode = 0
        stdout = "codex-cli 0.155.0-alpha.9.3\n"
        stderr = ""

    codex_adapter._host_wait_mode_cached.cache_clear()
    with monkeypatch.context() as isolated:
        isolated.setattr(codex_adapter.subprocess, "run", lambda *args, **kwargs: Version())
        assert codex_adapter.selected_continuation_mode(root) == "UNAVAILABLE"
    codex_adapter._host_wait_mode_cached.cache_clear()
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "UNAVAILABLE")
    digest = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    pre = hook_payload(tool_name="Bash", tool_input={"command": f"thaliris task-start goal --controller-bridge-sha256 {digest}"})
    command = json.loads(codex_adapter.audit_hook(root, "PreToolUse", pre, lifecycle_module.MANAGED_HOOK_ABI))["hookSpecificOutput"]["updatedInput"]["command"]
    token = re.search(r"--hook-attestation ([A-Za-z0-9._-]+)$", command).group(1)
    assert cli.main(["--root", str(root), "task-start", "attested", "--controller-bridge-sha256", digest, "--hook-attestation", token]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "MANAGED_CONTINUATION_UNAVAILABLE"
    codex_adapter._host_wait_mode_cached.cache_clear()


def test_doctor_separates_hook_spec_executable_and_attestation_facts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    root = repo(tmp_path)
    report = codex_adapter.doctor(root)
    host = report["host_capability"]
    assert host["installed_hook_spec"] == "UNAVAILABLE"
    assert host["canonical_executable_available"] in {"YES", "NO"}
    assert host["canonical_executable_identity"] in {"SHA256_PINNED", "PATH_UNPINNED", "UNAVAILABLE"}
    assert host["diagnostic_process_executable_resolution"] in {"SHA256_PINNED", "PATH_UNPINNED", "UNAVAILABLE"}
    assert host["active_codex_host_executable_observed"] == "UNKNOWN"
    assert report["verification_attestation"]["current_session_observed"] == "UNKNOWN"
    assert report["verification_attestation"]["task_start_attestation"] == "CURRENT_SESSION_REQUIRED"


def test_doctor_names_host_registration_separately_from_project_activation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    root = repo(tmp_path)

    report = codex_adapter.doctor(root)

    assert report["verification_attestation"]["host_hook_registration_present"] == "NO"
    assert "hook_definition_present" not in report["verification_attestation"]
    assert report["managed_readiness"]["HOST_HOOK_REGISTRATION_PRESENT"] == "NO"
    assert "CODEX_DEFINITION_PRESENT" not in report["managed_readiness"]
    assert report["managed_readiness"]["project_activation_marker_present"] == "YES"


def test_doctor_keeps_valid_runtime_and_host_executable_observations_distinct(tmp_path: Path) -> None:
    root = repo(tmp_path)
    runtime = root / ".context" / "audit" / "observed-session" / "runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps({
        "managed_hook_spec_hash": lifecycle_module.managed_hook_spec_hash(),
        "adapter_protocol_version": lifecycle_module.CODEX_ADAPTER_PROTOCOL_VERSION,
        "events_observed": {"PreToolUse": True},
    }), encoding="utf-8")

    host = codex_adapter.doctor(root)["host_capability"]

    assert host["hook_runtime_observed"] == "YES"
    assert host["active_codex_host_executable_observed"] == "UNKNOWN"


def test_invalid_task_state_denies_only_explicit_managed_mutations(tmp_path: Path) -> None:
    root = repo(tmp_path)
    started = _owned_task_start(root, "invalid state", None, None)
    state_path = core._state_path(root, started["task_id"])
    state_target = state_path.relative_to(root).as_posix()
    state_path.write_text("{broken", encoding="utf-8")
    assert lifecycle_module.managed_task_state(root) == ("INVALID_STATE", None)
    diagnostic = codex_adapter.doctor(root)
    assert diagnostic["managed_task_state"] == "INVALID_STATE"
    assert diagnostic["host_capability"]["reviewer_native_readonly_observed"] != "PASS"

    for payload in (
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris task-close --base-revision 1"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris task-promote --base-revision 1 records.json"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris task-update --base-revision 1 records.json"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris task-start --goal new"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris task-artifact --base-revision 1"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris recover-pending-spawn handoff"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris rollback"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris codex-install"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris codex-uninstall"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris uninstall"}),
        hook_payload(tool_name="Bash", tool_input={"command": f"Set-Content {state_target} '{{}}'"}),
        hook_payload(tool_name="functions.apply_patch", tool_input={"patch": f"*** Update File: {state_target}\n+{{}}"}),
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", payload))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        operation = lifecycle_module._context_call(payload)[0]
        if operation in {"codex-install", "codex-uninstall"}:
            expected_reason = "THALIRIS_HOST_MAINTENANCE_INTENT_REQUIRED"
        else:
            expected_reason = "CONTROL_STATE_DIRECT_WRITE" if lifecycle_module._control_state_target(payload) is not None else "INVALID_STATE"
        assert expected_reason in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="Bash", tool_input={"command": "thaliris init"},
    )) == ""
    for command in (
        "thaliris init; thaliris rollback fake",
        "Get-Content x; thaliris rollback fake",
        "Get-Date && thaliris task-close --base-revision 1",
        "Get-Date | thaliris task-update --base-revision 1 update.json",
        "Get-Date; & 'thaliris.exe' task-start goal",
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(
            tool_name="Bash", tool_input={"command": command},
        )))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        expected = ("THALIRIS_HOST_MAINTENANCE_INTENT_REQUIRED" if "codex-install" in command
                    else "INVALID_STATE")
        assert expected in denied["hookSpecificOutput"]["permissionDecisionReason"]
    for payload in (
        hook_payload(tool_name="Bash", tool_input={"command": "Get-Content C:/Users/example/.codex/sessions/rollout.jsonl"}),
        hook_payload(tool_name="thaliris-completely-unknown-mutate", tool_input={"command": "opaque"}),
        hook_payload(tool_name="spawn_agent", tool_input={"fork_turns": "none", "agent_type": "worker", "message": "work"}),
        hook_payload(tool_name="list_agents", tool_input={}),
        hook_payload(tool_name="send_message", tool_input={"target": "worker", "message": "status"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris doctor"}),
        hook_payload(tool_name="Bash", tool_input={"command": "thaliris task-status"}),
        hook_payload(tool_name="Bash", tool_input={"command": f"Get-Content {state_target}"}),
    ):
        assert handle_hook(root, "PreToolUse", payload) == ""


def test_invalid_state_keeps_unrelated_compound_commands_transparent(tmp_path: Path) -> None:
    root = repo(tmp_path)
    started = core.task_start(root, "invalid state", None, None)
    core.select_task(root, started["task_id"])
    core._state_path(root, started["task_id"]).write_text("{broken", encoding="utf-8")
    for command in (
        "Get-Date; Get-Content x",
        "Get-Content x; thaliris task-status",
        "thaliris doctor && Get-Date",
    ):
        assert handle_hook(root, "PreToolUse", hook_payload(
            tool_name="Bash", tool_input={"command": command},
        )) == ""


def test_invalid_v1_active_state_admits_init_then_exact_recovery(tmp_path: Path, monkeypatch, capsys) -> None:
    root = repo(tmp_path)
    monkeypatch.setattr(lifecycle_module, "managed_executable_health", lambda: {
        "canonical_executable_available": "YES",
        "canonical_executable_identity": "TEST",
    })
    monkeypatch.setattr(codex_adapter, "selected_continuation_mode", lambda _root: "BLOCKING_WAIT")
    state = {
        "schema_version": 1,
        "revision": 2,
        "task_id": "7e500c6a-6aec-4e22-94b0-42cc6a5459ef",
        "status": "ACTIVE",
        "goal": "old state remains archived evidence",
        "current_milestone": None,
        "active_work": [],
        "pending_results": [],
        "architectural_intent": None,
    }
    state_path = root / ".context" / "state.json"
    old_task_id = state["task_id"]
    old_bytes = json.dumps(state, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    state_path.write_bytes(old_bytes)
    core.select_task(root, old_task_id)

    instruction = root / "AGENTS.md"
    stale_text = instruction.read_text(encoding="utf-8").replace(
        "If either is absent, invoke",
        "If either is absent, invoke stale bootstrap advice via",
        1,
    )
    instruction.write_text(stale_text, encoding="utf-8")
    (root / ".codex" / "thaliris.json").unlink()
    facts = codex_adapter._project_definition_facts(root)
    instruction_sha256 = facts["managed_instruction_sha256"]
    assert facts["project_definition_present"] == "NO"
    assert isinstance(instruction_sha256, str) and instruction_sha256 != "UNKNOWN"

    init_command = f"thaliris init --accept-managed-instruction-sha256 {instruction_sha256}"
    assert handle_hook(
        root,
        "PreToolUse",
        hook_payload(tool_name="Bash", tool_input={"command": init_command}),
    ) == ""
    assert codex_adapter.init(root, accept_managed_instruction_sha256=instruction_sha256)["project_definition_present"] == "YES"
    assert state_path.read_bytes() == old_bytes

    for command in (
        f"thaliris --task-id {old_task_id} task-close --base-revision 1",
        f"thaliris --task-id {old_task_id} task-update --base-revision 1 old.json",
        f"thaliris --task-id {old_task_id} task-artifact --base-revision 1",
        f"thaliris --task-id {old_task_id} task-promote --base-revision 1 old.json",
        f"thaliris --task-id {old_task_id} recover-pending-spawn handoff",
        f"thaliris --task-id {old_task_id} rollback backup-id",
        f"thaliris --task-id {old_task_id} codex-install",
        f"thaliris --task-id {old_task_id} uninstall",
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(tool_name="Bash", tool_input={"command": command})))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        expected = ("THALIRIS_HOST_MAINTENANCE_INTENT_REQUIRED" if "codex-install" in command
                    else "INVALID_STATE")
        assert expected in denied["hookSpecificOutput"]["permissionDecisionReason"]

    digest = hashlib.sha256(old_bytes).hexdigest()
    bridge = codex_adapter._controller_bridge()["controller_bridge_sha256"]
    command = f"thaliris --task-id {old_task_id} task-recover-state --expected-sha256 {digest} --abandon-active --controller-bridge-sha256 {bridge}"
    _, token = _attested_recovery_command(root, command)
    assert cli.main([
        "--root", str(root), "--task-id", old_task_id, "task-recover-state", "--expected-sha256", digest,
        "--abandon-active", "--hook-attestation", token,
        "--controller-bridge-sha256", bridge,
    ]) == 0
    recovered = json.loads(capsys.readouterr().out)
    archive = root / recovered["preserved_state_location"]
    assert recovered["status"] == "STATE_ARCHIVED_FOR_RECOVERY"
    assert archive.read_bytes() == old_bytes
    assert not state_path.exists()

    fresh = core.task_start(root, "new current-schema task", None, None)
    assert fresh["status"] == "ACTIVE"
    current = json.loads(core._state_path(root, fresh["task_id"]).read_text(encoding="utf-8"))
    assert current["schema_version"] == core._STATE_SCHEMA_VERSION




def test_host_capability_record_requires_sessionmeta_for_live_implementer_activation() -> None:
    record = Path("docs/codex-host-capability-20260920.md").read_text(encoding="utf-8")
    assert "source default of `gpt-5.6-luna`" in record
    assert "installed/generated\n`thaliris-implementer` profile bytes are configuration/install proof only" in record
    assert "do not prove that a spawned child actually used Luna" in record
    assert "native,\ncurrent-session `SessionMeta` observation" in record
    assert "`gpt-5.6-luna` for `thaliris-implementer`" in record
    assert "Unattested or untrusted alpha,\nstale, or other-session evidence is non-live/`UNKNOWN`" in record
    assert "cannot satisfy this\ncriterion" in record
    assert "`profile_native_active` remains\n`UNKNOWN`" in record
    assert "no live probe was attempted" in record


def test_authorized_spawn_requires_fresh_explicit_serial_handoff(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "spawn contract", None, None)

    for tool_input in (
        {"fork_turns": "all", "agent_type": "worker", "message": "task"},
        {"fork_turns": "none", "agent_type": "worker", "message": ""},
        {"fork_turns": "none", "agent_type": "unknown-role", "message": "task"},
    ):
        denied = json.loads(handle_hook(root, "PreToolUse", hook_payload(tool_name="spawn_agent", tool_input=tool_input)))
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    valid = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "first task",
    })
    assert handle_hook(root, "PreToolUse", valid) == ""
    duplicate = json.loads(handle_hook(root, "PreToolUse", hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "second task",
    })))
    assert duplicate["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_native_spawn_failure_without_posttool_keeps_pending_reservation(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "spawn failure recovery", None, None)
    failed_spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "failed handoff",
    })
    assert handle_hook(root, "PreToolUse", failed_spawn) == ""
    pending = lifecycle(root)["pending_authorized_spawn"]
    assert pending is not None

    # Codex 0.154 returns the native error without PostToolUse. The reservation
    # therefore remains until the Controller explicitly invokes recovery.
    assert lifecycle(root)["pending_authorized_spawn"] == pending


def test_pending_spawn_recovery_requires_exact_handoff_id(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "wrong recovery id", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    with pytest.raises(ValueError, match="does not match"):
        lifecycle_module.recover_pending_spawn(root, "handoff-" + "0" * 32)
    assert lifecycle(root)["pending_authorized_spawn"] is not None


def test_exact_pending_spawn_recovery_clears_reservation_and_allows_next_spawn(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "exact recovery id", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    handoff_id = lifecycle(root)["pending_authorized_spawn"]["handoff_id"]
    with pytest.raises(ValueError, match="trusted terminal Host evidence"):
        lifecycle_module.recover_pending_spawn(root, handoff_id)
    assert handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"task_name": "/root/failed-child"}}) == ""
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents", tool_response={"agents": [{"agent_name": "/root/failed-child", "agent_status": "interrupted"}]},
    )) == ""
    recovered = lifecycle_module.recover_pending_spawn(root, handoff_id)
    assert recovered["recovered"] is True
    state = lifecycle(root)
    assert state["pending_authorized_spawn"] is None
    assert state["spawn_recoveries"][-1]["handoff_id"] == handoff_id

    next_spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "next handoff",
    })
    assert handle_hook(root, "PreToolUse", next_spawn) == ""
    assert lifecycle(root)["pending_authorized_spawn"] is not None


@pytest.mark.parametrize("status", ["pending_init", "running", "not_found", {"completed": "result"}])
def test_pending_recovery_rejects_nonfailure_native_status(tmp_path: Path, status: object) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "pending evidence", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    handoff_id = lifecycle(root)["pending_authorized_spawn"]["handoff_id"]
    assert handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"task_name": "/root/child"}}) == ""
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents", tool_response={"agents": [{"agent_name": "/root/child", "agent_status": status}]},
    )) == ""
    with pytest.raises(ValueError, match="trusted terminal Host evidence"):
        lifecycle_module.recover_pending_spawn(root, handoff_id)
    assert lifecycle(root)["pending_authorized_spawn"] is not None


def test_pending_recovery_requires_exact_spawn_failure_callback_identity(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "exact failure callback", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_use_id="native-tool-1", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    handoff_id = lifecycle(root)["pending_authorized_spawn"]["handoff_id"]
    handle_hook(root, "PostToolUse", {**spawn, "tool_use_id": "other-tool", "tool_response": {"error": "spawn failed"}})
    with pytest.raises(ValueError, match="trusted terminal Host evidence"):
        lifecycle_module.recover_pending_spawn(root, handoff_id)
    handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"error": "spawn failed"}})
    assert lifecycle_module.recover_pending_spawn(root, handoff_id)["recovered"] is True


def test_pending_spawn_recovery_rejects_handoff_already_bound_to_child(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "bound recovery", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "bound handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    handoff_id = lifecycle(root)["pending_authorized_spawn"]["handoff_id"]
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="bound-child", agent_type="worker")) == ""
    with pytest.raises(ValueError, match="already bound") as error:
        lifecycle_module.recover_pending_spawn(root, handoff_id)
    assert "authorized native Codex role session" in str(error.value)
    assert lifecycle(root)["children"][-1]["managed"] is True


def test_unknown_spawn_result_does_not_release_reservation(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "unknown spawn", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "PostToolUse", {**spawn, "tool_response": {"detail": "no outcome"}}) == ""
    assert lifecycle(root)["pending_authorized_spawn"] is not None


def test_lifecycle_binds_matching_identity_and_stop(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "lifecycle", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "thaliris-reviewer", "message": "review this",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""

    # Wrong native role cannot consume the reservation.
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="wrong", agent_type="worker")) == ""
    state = lifecycle(root)
    assert state["children"][0]["managed"] is False
    assert state["pending_authorized_spawn"] is not None

    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="reviewer-1", agent_type="thaliris-reviewer")) == ""
    running = lifecycle(root)["children"][-1]
    assert running["managed"] is True and running["terminal_state"] == "RUNNING"
    assert handle_hook(root, "SubagentStop", hook_payload(agent_id="other", agent_type="thaliris-reviewer")) == ""
    assert lifecycle(root)["children"][-1]["terminal_state"] == "RUNNING"
    assert handle_hook(root, "SubagentStop", hook_payload(agent_id="reviewer-1", agent_type="thaliris-reviewer")) == ""
    stopped = lifecycle(root)["children"][-1]
    assert stopped["terminal_state"] == "RUNNING"
    assert stopped["native_terminal_status"] is None
    assert isinstance(stopped["started"], int) and isinstance(stopped["stop_observed"], int)
    assert stopped["stopped"] is None


def test_stop_requires_explicit_native_completed_for_close(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "native completion", None, None)
    spawn_start(root, "worker-1")
    stop(root, "worker-1")
    state = core.task_show(root)["state"]
    with pytest.raises(ValueError, match="authorized handoff/identity bindings"):
        codex_adapter.task_close(root, state["revision"])

    reconcile(root, "worker-1", {"completed": "result"})
    assert codex_adapter.task_close(root, state["revision"])["status"] == "DONE"


def test_string_spawn_response_records_native_task_name(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "string spawn response", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "PostToolUse", {
        **spawn,
        "tool_response": json.dumps({"task_name": "/root/worker-1"}),
    }) == ""
    assert lifecycle(root)["pending_authorized_spawn"]["task_name_hash"] == lifecycle_module._identity_hash("/root/worker-1")


def test_post_tool_json_string_decoding_is_limited_to_collaboration_tools() -> None:
    response = json.dumps({"exit_code": 1})
    assert lifecycle_module._post_tool_response({"tool_name": "Bash", "tool_response": response}) == response
    assert lifecycle_module._post_tool_response({"tool_name": "spawn_agent", "tool_response": response}) == {"exit_code": 1}


def test_task_name_string_response_binds_distinct_host_child_id_through_close(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "distinct native identities", None, None)
    task_name, agent_id = "/root/worker-task-name", "native-child-id"
    spawn_start_with_host_task_name(root, task_name, agent_id)
    child = lifecycle(root)["children"][-1]
    assert child["task_name_hash"] == lifecycle_module._identity_hash(task_name)
    assert child["agent_id_hash"] == lifecycle_module._identity_hash(agent_id)
    assert child["task_name_hash"] != child["agent_id_hash"]
    stop(root, agent_id)

    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response=json.dumps({"agents": [{"agent_name": task_name, "agent_status": {"completed": "result"}}]}),
    )) == ""
    child = lifecycle(root)["children"][-1]
    assert child["terminal_state"] == "NATIVE_TERMINAL_RECONCILED"
    assert child["native_terminal_status"] == "completed"
    assert codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])["status"] == "DONE"


def test_string_list_response_does_not_reconcile_wrong_identity(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "wrong native identity", None, None)
    task_name, agent_id = "/root/worker-task-name", "native-child-id"
    spawn_start_with_host_task_name(root, task_name, agent_id)
    stop(root, agent_id)

    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response=json.dumps({"agents": [{"agent_name": "/root/wrong-child", "agent_status": {"completed": "result"}}]}),
    )) == ""
    child = lifecycle(root)["children"][-1]
    assert child["native_terminal_status"] is None
    with pytest.raises(ValueError, match="authorized handoff/identity bindings"):
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])


def test_string_wait_response_is_not_completion_evidence(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "wait response is not completion", None, None)
    task_name, agent_id = "/root/worker-task-name", "native-child-id"
    spawn_start_with_host_task_name(root, task_name, agent_id)
    stop(root, agent_id)

    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="wait_agent", tool_input={"targets": [task_name]},
        tool_response=json.dumps({"agents": [{"agent_name": task_name, "agent_status": {"completed": "result"}}]}),
    )) == ""
    child = lifecycle(root)["children"][-1]
    assert child["native_terminal_status"] is None
    with pytest.raises(ValueError, match="task-close requires"):
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])


def test_desktop_wait_wake_needs_name_bound_list_status_before_close(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "Desktop completion bridge", None, None)
    task_name, agent_id = "/root/desktop_probe", "native-desktop-child-id"
    spawn_start_with_host_task_name(root, task_name, agent_id)
    stop(root, agent_id)

    # Desktop's observed wait result is a wake signal without child status.
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="wait_agent", tool_input={"timeout_ms": 3_600_000},
        tool_response=json.dumps({"message": "Wait completed.", "timed_out": False}),
    )) == ""
    assert lifecycle(root)["children"][-1]["native_terminal_status"] is None
    with pytest.raises(ValueError, match="use list_agents"):
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])

    # A real Desktop list response contains a root entry and a named child
    # whose completed variant carries the child's final text.
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response=json.dumps({"agents": [
            {"agent_name": "/root", "agent_status": "running"},
            {"agent_name": task_name, "agent_status": {"completed": "Probe completed normally."}},
        ]}),
    )) == ""
    assert lifecycle(root)["children"][-1]["native_terminal_status"] == "completed"
    assert codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])["status"] == "DONE"


def test_string_interrupt_response_reconciles_exact_task_name(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "interrupt response identity", None, None)
    task_name, agent_id = "/root/worker-task-name", "native-child-id"
    spawn_start_with_host_task_name(root, task_name, agent_id)
    stop(root, agent_id)

    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="interrupt_agent", tool_input={"target": task_name},
        tool_response=json.dumps({"previous_status": {"completed": "result"}}),
    )) == ""
    child = lifecycle(root)["children"][-1]
    assert child["native_terminal_status"] == "completed"
    with pytest.raises(ValueError, match="use list_agents"):
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])
    reconcile(root, task_name, {"completed": "result"})
    assert codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])["status"] == "DONE"


def test_string_list_response_reconciles_completed_child_and_allows_close(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "string list response", None, None)
    spawn_start(root, "worker-1")
    stop(root, "worker-1")
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response=json.dumps({"agents": [{"agent_name": "worker-1", "agent_status": {"completed": "result"}}]}),
    )) == ""
    child = lifecycle(root)["children"][-1]
    assert child["terminal_state"] == "NATIVE_TERMINAL_RECONCILED"
    assert child["native_terminal_status"] == "completed"
    assert codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])["status"] == "DONE"


@pytest.mark.parametrize("response", [
    "{not-json}",
    json.dumps([{"task_name": "/root/worker-1"}]),
    json.dumps("completed"),
    '{"agents":[{"agent_name":"worker-1","agent_status":{"completed":"result"}}],"extra":NaN}',
])
def test_malformed_or_non_dict_string_response_produces_no_completion_fact(tmp_path: Path, response: str) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "unknown string response", None, None)
    spawn_start(root, "worker-1")
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response=response,
    )) == ""
    child = lifecycle(root)["children"][-1]
    assert child["terminal_state"] == "RUNNING"
    assert child["native_terminal_status"] is None


def test_missing_stop_native_completed_proves_execution_closure(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "reconcile", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "implement",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="worker-1", agent_type="worker")) == ""
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="list_agents",
        tool_response={"agents": [{"agent_name": "worker-1", "agent_status": {"completed": "result"}}]},
    )) == ""
    child = lifecycle(root)["children"][-1]
    assert child["terminal_state"] == "NATIVE_TERMINAL_RECONCILED"
    assert child["native_terminal_status"] == "completed"

    assert child.get("stop_observed") is None
    # No child prose is stored as model acceptance; Controller invokes close.
    assert "result" not in json.dumps(child)
    shown = core.task_show(root)["state"]
    assert shown["status"] == "ACTIVE"
    assert codex_adapter.task_close(root, shown["revision"])["status"] == "DONE"


@pytest.mark.parametrize("stop_first", [False, True])
def test_optional_stop_preserves_native_completed_in_either_order(tmp_path, stop_first):
    root = repo(tmp_path)
    _owned_task_start(root, "observation order", None, None)
    spawn_start(root, "child")
    if stop_first:
        stop(root, "child")
    reconcile(root, "child", {"completed": "result"})
    if not stop_first:
        stop(root, "child")
    child = lifecycle(root)["children"][-1]
    assert isinstance(child["stop_observed"], int)
    assert child["terminal_state"] == "NATIVE_TERMINAL_RECONCILED"
    assert child["native_terminal_status"] == "completed"
    assert lifecycle_module.qualifying_child_completed(root)


@pytest.mark.parametrize("unsupported", [
    {"completed": 4},
    {"completed": False},
    {"completed": {"text": "result"}},
])
def test_unsupported_completed_payload_keeps_native_status_unknown(tmp_path, unsupported):
    root = repo(tmp_path)
    _owned_task_start(root, "unsupported native completed payload", None, None)
    spawn_start(root, "child")
    reconcile(root, "child", unsupported)
    child = lifecycle(root)["children"][-1]
    assert child["terminal_state"] == "RUNNING"
    assert child["native_terminal_status"] is None
    assert not lifecycle_module.qualifying_child_completed(root)
    with pytest.raises(ValueError, match="use list_agents"):
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])


@pytest.mark.parametrize("result", [None, "result"])
def test_v1_wait_native_completed_closes_without_list_or_stop(tmp_path, result):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 completion", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_input={"fork_context": False,
        "agent_type": "worker", "message": "explicit V1 handoff"})
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "PostToolUse", {**spawn, "tool_response": {
        "agent_id": "v1-agent-id", "nickname": None}}) == ""
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="v1-agent-id", agent_type="worker")) == ""
    assert handle_hook(root, "PostToolUse", hook_payload(tool_name="wait_agent",
        tool_input={"targets": ["v1-agent-id"], "timeout_ms": 30000},
        tool_response=json.dumps({"status": {"v1-agent-id": {"completed": result}}, "timed_out": False}))) == ""
    child = lifecycle(root)["children"][-1]
    assert child["native_terminal_source"] == "wait_agent"
    assert child["handoff_bound"] and child.get("stop_observed") is None
    assert lifecycle_module.qualifying_child_completed(root)
    # Execution evidence does not perform semantic acceptance or task closure.
    assert core.task_show(root)["state"]["status"] == "ACTIVE"
    assert codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])["status"] == "DONE"


@pytest.mark.parametrize("flags", [{}, {"fork_context": True}, {"fork_context": 0},
    {"fork_context": False, "fork_turns": "all"}, {"fork_context": True, "fork_turns": "none"}])
def test_native_fresh_spawn_requires_explicit_nonconflicting_isolation(tmp_path, flags):
    root = repo(tmp_path)
    _owned_task_start(root, "native isolation", None, None)
    assert "THALIRIS_ISOLATION_REQUIRED" in handle_hook(root, "PreToolUse", hook_payload(
        tool_name="spawn_agent", tool_input={**flags, "agent_type": "worker", "message": "handoff"}))
    assert lifecycle(root)["pending_authorized_spawn"] is None


def test_v2_null_completion_is_execution_only(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "V2 null completion", None, None)
    spawn_start_with_host_task_name(root, "/root/native", "child-id")
    reconcile(root, "/root/native", {"completed": None})
    assert lifecycle_module.qualifying_child_completed(root)
    assert core.task_show(root)["state"]["status"] == "ACTIVE"


@pytest.mark.parametrize("start_first", [False, True])
@pytest.mark.parametrize("returned_id", ["actual-id", "wrong-id"])
def test_v1_spawn_and_start_identity_corroboration_in_both_orders(tmp_path, start_first, returned_id):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 binding", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_use_id="native-call", tool_input={
        "fork_context": False, "agent_type": "worker", "message": "selected handoff"})
    assert handle_hook(root, "PreToolUse", spawn) == ""
    started = hook_payload(agent_id="actual-id", agent_type="worker")
    returned = {**spawn, "tool_response": {"agent_id": returned_id, "nickname": "display only"}}
    for event, payload in (("SubagentStart", started), ("PostToolUse", returned)) if start_first else (
        ("PostToolUse", returned), ("SubagentStart", started)):
        assert handle_hook(root, event, payload) == ""
    handle_hook(root, "PostToolUse", hook_payload(tool_name="wait_agent", tool_input={"targets": ["actual-id"]},
        tool_response={"status": {"actual-id": {"completed": None}}, "timed_out": False}))
    assert lifecycle_module.qualifying_child_completed(root) is (returned_id == "actual-id")


def test_v1_native_completion_still_requires_authorized_handoff(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "unbound V1", None, None)
    handle_hook(root, "SubagentStart", hook_payload(agent_id="unbound", agent_type="worker"))
    handle_hook(root, "PostToolUse", hook_payload(tool_name="wait_agent", tool_input={"targets": ["unbound"]},
        tool_response={"status": {"unbound": {"completed": None}}, "timed_out": False}))
    assert not lifecycle_module.qualifying_child_completed(root)


@pytest.mark.parametrize("start_order", ["after_conflicting_results", "between_results"])
def test_conflicting_v1_spawn_ids_block_next_authorization_in_either_start_order(tmp_path, start_order):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 conflicting spawn ids", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_use_id="same-native-call", tool_input={
        "fork_context": False, "agent_type": "worker", "message": "explicit V1 handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    start = hook_payload(agent_id="spawn-id-A", agent_type="worker")
    returned_a = {**spawn, "tool_response": {"agent_id": "spawn-id-A", "nickname": None}}
    returned_b = {**spawn, "tool_response": {"agent_id": "spawn-id-B", "nickname": None}}

    if start_order == "between_results":
        assert handle_hook(root, "PostToolUse", returned_a) == ""
        assert handle_hook(root, "SubagentStart", start) == ""
        assert handle_hook(root, "PostToolUse", returned_b) == ""
    else:
        assert handle_hook(root, "PostToolUse", returned_a) == ""
        assert handle_hook(root, "PostToolUse", returned_b) == ""
        assert handle_hook(root, "SubagentStart", start) == ""

    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="wait_agent", tool_input={"targets": ["spawn-id-A"]},
        tool_response={"status": {"spawn-id-A": {"completed": None}}, "timed_out": False},
    )) == ""
    state = lifecycle(root)
    assert state.get("identity_collisions") or state["children"][-1].get("native_status_conflict") is True
    assert not lifecycle_module.qualifying_child_completed(root)
    denied = handle_hook(root, "PreToolUse", hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": "next handoff",
    }))
    assert "THALIRIS_NATIVE_IDENTITY_COLLISION" in denied or "THALIRIS_SERIAL_ROLE_SESSION_REQUIRED" in denied
    assert lifecycle(root)["pending_authorized_spawn"] is None


def test_v1_wait_failure_for_exact_pending_native_id_allows_explicit_recovery(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 pending identity recovery", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_use_id="pending-native-call", tool_input={
        "fork_context": False, "agent_type": "worker", "message": "explicit V1 handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "PostToolUse", {**spawn, "tool_response": {
        "agent_id": "pending-agent-id", "nickname": None,
    }}) == ""
    pending = lifecycle(root)["pending_authorized_spawn"]
    assert pending is not None
    handoff_id = pending["handoff_id"]
    assert pending["native_agent_id_hash"] == lifecycle_module._identity_hash("pending-agent-id")
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="wait_agent", tool_input={"targets": ["pending-agent-id"]},
        tool_response={"status": {"pending-agent-id": {"errored": "native start failed"}}, "timed_out": False},
    )) == ""
    evidence = lifecycle(root)["pending_spawn_terminal_evidence"]
    assert evidence["handoff_id"] == handoff_id
    assert evidence["status"] == "errored"
    assert evidence["source"] == "wait_agent"
    assert evidence["native_agent_id_hash"] == pending["native_agent_id_hash"]
    assert lifecycle_module.recover_pending_spawn(root, handoff_id)["recovered"] is True
    assert lifecycle(root)["pending_authorized_spawn"] is None


@pytest.mark.parametrize("status", ["not_found", "running", {"completed": None}, {"errored": "wrong target"}])
def test_v1_wait_nonfailure_or_unmatched_pending_status_cannot_recover(tmp_path, status):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 pending invalid status", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_use_id="pending-native-call", tool_input={
        "fork_context": False, "agent_type": "worker", "message": "explicit V1 handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "PostToolUse", {**spawn, "tool_response": {
        "agent_id": "pending-agent-id", "nickname": None,
    }}) == ""
    handoff_id = lifecycle(root)["pending_authorized_spawn"]["handoff_id"]
    target = "different-agent-id" if status == {"errored": "wrong target"} else "pending-agent-id"
    assert handle_hook(root, "PostToolUse", hook_payload(
        tool_name="wait_agent", tool_input={"targets": [target]},
        tool_response={"status": {target: status}, "timed_out": False},
    )) == ""
    with pytest.raises(ValueError, match="trusted terminal Host evidence"):
        lifecycle_module.recover_pending_spawn(root, handoff_id)
    assert lifecycle(root)["pending_authorized_spawn"] is not None


def test_v1_wait_wake_only_response_cannot_recover_pending_spawn(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 pending wake-only response", None, None)
    spawn = hook_payload(tool_name="spawn_agent", tool_use_id="pending-native-call", tool_input={
        "fork_context": False, "agent_type": "worker", "message": "explicit V1 handoff",
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    assert handle_hook(root, "PostToolUse", {**spawn, "tool_response": {
        "agent_id": "pending-agent-id", "nickname": None,
    }}) == ""
    handoff_id = lifecycle(root)["pending_authorized_spawn"]["handoff_id"]
    assert handle_hook(root, "PostToolUse", hook_payload(tool_name="wait_agent",
        tool_input={"targets": ["pending-agent-id"]},
        tool_response={"message": "Wait completed.", "timed_out": False})) == ""
    with pytest.raises(ValueError, match="trusted terminal Host evidence"):
        lifecycle_module.recover_pending_spawn(root, handoff_id)
    assert lifecycle(root)["pending_authorized_spawn"] is not None


def test_v1_close_does_not_replace_completion_observation(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 close is control observation", None, None)
    spawn_start(root, "v1-child")
    handle_hook(root, "PostToolUse", hook_payload(tool_name="close_agent", tool_input={"id": "v1-child"},
        tool_response={"previous_status": {"completed": None}}))
    assert lifecycle(root)["children"][-1]["native_terminal_status"] == "completed"
    assert not lifecycle_module.qualifying_child_completed(root)
    handle_hook(root, "PostToolUse", hook_payload(tool_name="wait_agent", tool_input={"targets": ["v1-child"]},
        tool_response={"status": {"v1-child": {"completed": None}}, "timed_out": False}))
    assert lifecycle_module.qualifying_child_completed(root)


@pytest.mark.parametrize("response, targets", [
    ({"status": {"other": {"completed": None}}, "timed_out": False}, ["v1-agent-id"]),
    ({"status": {"v1-agent-id": {"completed": None}}, "timed_out": "false"}, ["v1-agent-id"]),
    ({"status": {"v1-agent-id": {"completed": None}}}, ["v1-agent-id"]),
    ({"message": "Wait completed.", "timed_out": False}, ["v1-agent-id"]),
    ({"status": {"v1-agent-id": {"completed": None}}, "timed_out": False}, []),
])
def test_v1_wait_rejects_unbound_or_wake_only_evidence(tmp_path, response, targets):
    root = repo(tmp_path)
    _owned_task_start(root, "V1 unknown completion", None, None)
    spawn_start(root, "v1-agent-id")
    handle_hook(root, "PostToolUse", hook_payload(tool_name="wait_agent",
        tool_input={"targets": targets}, tool_response=response))
    assert not lifecycle_module.qualifying_child_completed(root)


@pytest.mark.parametrize("contradiction", ["running", "interrupted", {"errored": "failure"}, "shutdown"])
def test_conflicting_native_status_cannot_become_completion(tmp_path, contradiction):
    root = repo(tmp_path)
    _owned_task_start(root, "conflicting native observations", None, None)
    spawn_start(root, "child")
    reconcile(root, "child", {"completed": "result"})
    reconcile(root, "child", contradiction)
    reconcile(root, "child", {"completed": "result"})
    assert lifecycle(root)["children"][-1]["native_status_conflict"] is True
    assert not lifecycle_module.qualifying_child_completed(root)


def test_native_status_conflict_blocks_new_spawn_and_close(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "conflicting status blocks work", None, None)
    spawn_start(root, "child")
    reconcile(root, "child", {"completed": "result"})
    reconcile(root, "child", "running")
    child = lifecycle(root)["children"][-1]
    assert child["native_status_conflict"] is True
    assert child["terminal_state"] == "NATIVE_TERMINAL_RECONCILED"

    denied = handle_hook(root, "PreToolUse", hook_payload(
        tool_name="spawn_agent",
        tool_input={"fork_turns": "none", "agent_type": "worker", "message": "next handoff"},
    ))
    assert "THALIRIS_NATIVE_IDENTITY_COLLISION" in denied
    assert lifecycle(root)["pending_authorized_spawn"] is None
    with pytest.raises(ValueError, match="authorized handoff/identity bindings"):
        codex_adapter.task_close(root, core.task_show(root)["state"]["revision"])


def test_known_native_task_name_excludes_different_agent_id_name(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "canonical native name", None, None)
    spawn_start_with_host_task_name(root, "/root/task", "child-id")
    reconcile(root, "child-id", {"completed": "result"})
    assert lifecycle(root)["children"][-1]["native_terminal_status"] is None
    reconcile(root, "/root/task", {"completed": "result"})
    assert lifecycle_module.qualifying_child_completed(root)


def test_native_completed_parent_keeps_active_descendant_and_unbound_child_fail_closed(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "native descendant closure", None, None)
    spawn_start(root, "parent")
    nested = hook_payload(agent_id="parent", agent_type="worker", tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "thaliris-investigator", "message": "selected discovery",
    })
    assert handle_hook(root, "PreToolUse", nested) == ""
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="scanner", agent_type="thaliris-investigator")) == ""
    reconcile(root, "parent", {"completed": "result"})
    assert not lifecycle_module.qualifying_child_completed(root)
    stop(root, "scanner", "thaliris-investigator")
    assert not lifecycle_module.qualifying_child_completed(root)
    reconcile(root, "scanner", {"completed": "facts"})
    assert lifecycle_module.qualifying_child_completed(root)
    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="unbound", agent_type="worker")) == ""
    assert not lifecycle_module.qualifying_child_completed(root)


def test_bound_executor_can_iterate_locally_without_controller_or_native_reuse(tmp_path):
    root = repo(tmp_path)
    _owned_task_start(root, "local self iteration", None, None)
    spawn_start(root, "child")
    for command in ("Get-Content src/example.py", "Set-Content src/example.py fixed", "pytest tests/test_example.py"):
        assert handle_hook(root, "PreToolUse", hook_payload(agent_id="child", agent_type="worker",
            tool_name="Bash", tool_input={"command": command})) == ""
    denied = handle_hook(root, "PreToolUse", hook_payload(agent_id="child", agent_type="worker",
        tool_name="Bash", tool_input={"command": "thaliris task-close --base-revision 1"}))
    assert "CONTROL_STATE_MUTATION" in denied


def test_selected_handoff_sentinel_exists_once_across_native_and_adapter_payload(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "once", None, None)
    handoff = "SELECTED_FACT HANDOFF_SENTINEL"
    spawn = hook_payload(tool_name="spawn_agent", tool_input={
        "fork_turns": "none", "agent_type": "worker", "message": handoff,
    })
    assert handle_hook(root, "PreToolUse", spawn) == ""
    adapter_payload = handle_hook(root, "SubagentStart", hook_payload(agent_id="child", agent_type="worker"))
    assert (handoff + adapter_payload).count("HANDOFF_SENTINEL") == 1


def test_latest_managed_child_alone_controls_close(tmp_path: Path) -> None:
    terminal_cases = (
        ({"completed": "result"}, False, True),
        ("interrupted", True, False),
        ({"errored": "boom"}, True, False),
        ("shutdown", True, False),
        ({"completed": "result"}, True, True),
    )
    for index, (latest_status, attest_stop, should_close) in enumerate(terminal_cases):
        root = tmp_path / str(index)
        root.mkdir()
        root = repo(root)
        _owned_task_start(root, "latest child", None, None)
        spawn_start(root, "child-a")
        stop(root, "child-a")
        reconcile(root, "child-a", {"completed": "result"})
        spawn_start(root, "child-b")
        if attest_stop:
            stop(root, "child-b")
        reconcile(root, "child-b", latest_status)
        state = core.task_show(root)["state"]
        if should_close:
            assert codex_adapter.task_close(root, state["revision"])["status"] == "DONE"
        else:
            try:
                codex_adapter.task_close(root, state["revision"])
            except ValueError as exc:
                assert "authorized handoff/identity bindings" in str(exc)
            else:
                raise AssertionError(f"latest child status {latest_status!r} was hidden by historical success")


def test_subagent_start_identity_collision_preserves_reservation(tmp_path: Path) -> None:
    root = repo(tmp_path)
    _owned_task_start(root, "collision", None, None)
    spawn_start(root, "reused-id")
    stop(root, "reused-id")
    reconcile(root, "reused-id", {"completed": "first result"})
    assert handle_hook(root, "PreToolUse", hook_payload(
        tool_name="spawn_agent",
        tool_input={"fork_turns": "none", "agent_type": "worker", "message": "second handoff"},
    )) == ""

    assert handle_hook(root, "SubagentStart", hook_payload(agent_id="reused-id", agent_type="worker")) == ""
    state = lifecycle(root)
    assert state["pending_authorized_spawn"] is not None
    assert len([child for child in state["children"] if child.get("managed") is True]) == 1
    assert state["identity_collisions"][-1]["pending_handoff_id"] == state["pending_authorized_spawn"]["handoff_id"]


def test_only_current_lifecycle_schema_is_accepted(tmp_path: Path) -> None:
    root = repo(tmp_path)
    started = _owned_task_start(root, "current lifecycle", None, None)
    path = root / ".context" / "audit" / "lifecycle" / f"{lifecycle_module._task_key(started['task_id'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": lifecycle_module.LIFECYCLE_STATE_VERSION - 1,
        "task_id_hash": lifecycle_module._task_key(started["task_id"]),
        "children": [],
        "pending_authorized_spawn": None,
        "sequence": 0,
    }), encoding="utf-8")
    try:
        lifecycle_module._load_lifecycle(path, started["task_id"])
    except ValueError as exc:
        assert "invalid lifecycle runtime state" in str(exc)
    else:
        raise AssertionError("old lifecycle schema was accepted")


def test_exact_role_keyed_historical_profiles_migrate_without_claiming_edits(tmp_path: Path) -> None:
    root = repo(tmp_path)
    agents = root / ".codex" / "agents"
    agents.mkdir(parents=True)
    for name, hashes in codex_adapter._KNOWN_GENERATED_AGENT_PROFILE_HASHES.items():
        assert hashes or name == "thaliris-focused-implementer.toml"
        # State recognition is hash-only and role-keyed: an unknown edit stays user-owned.
        assert codex_adapter._agent_profile_state(b"generated-looking but edited", name) == "user"
    # Recover the exact pre-Luna generator from immutable repository history.
    source = historical_blob("78fca60^:src/thaliris/codex_adapter.py", text=True)
    module = ast.parse(source)
    historic_fn = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_agent_profile")
    namespace: dict[str, object] = {}
    exec(compile(ast.Module([historic_fn], []), "historic", "exec"), namespace)
    for role in ("investigator", "curator", "implementer"):
        name = f"thaliris-{role}.toml"
        legacy = agents / name
        legacy_bytes = namespace["_agent_profile"](name.removesuffix(".toml"), role, "gpt-5.6-luna", "medium")
        if role == "implementer":
            # Exact generated bytes from the role-keyed migration provenance
            # (commits 0ebbba3/db6f19d), not a fuzzy or cross-role match.
            source = historical_blob("0ebbba3:src/thaliris/codex_adapter.py", text=True)
            historic = ast.parse(source)
            fn = next(node for node in historic.body if isinstance(node, ast.FunctionDef) and node.name == "_agent_profile")
            exact_namespace: dict[str, object] = {}
            exec(compile(ast.Module([fn], []), "historic-exact", "exec"), exact_namespace)
            legacy_bytes = exact_namespace["_agent_profile"]("thaliris-implementer", "implementer", "gpt-5.6-luna", "medium")
            assert hashlib.sha256(legacy_bytes).hexdigest() == "55c1ea16853dcc4f5a4617005e57a939cd4dcd773e2fd24c5e0911ea3c9e90c0"
        legacy.write_bytes(legacy_bytes)
        assert codex_adapter._agent_profile_state(legacy.read_bytes(), name) == "legacy"
    verifier_name = "thaliris-verifier.toml"
    # The installed historical profile is a fixed LF/UTF-8 fixture copied from
    # the exact blob 073db5e in immutable commits 7a94032/e02b953.  The older
    # medium fixture below is a separate supported generator rendering.
    verifier_legacy = (Path(__file__).parent / "fixtures" / "thaliris-verifier-installed-xhigh.toml").read_bytes()
    assert len(verifier_legacy) == 1810
    assert verifier_legacy.endswith(b"\n") and b"\r" not in verifier_legacy
    assert hashlib.sha256(verifier_legacy).hexdigest() == "fa1585e8df2c9136eed055f22e85594805c62a0cec0d6387700dd4959fe9dc19"
    assert codex_adapter._agent_profile_state(verifier_legacy, verifier_name) == "legacy"
    medium = (Path(__file__).parent / "fixtures" / "thaliris-verifier-pre-candidate.toml").read_bytes()
    assert len(medium) == 1811
    assert medium.endswith(b"\n") and b"\r" not in medium
    assert hashlib.sha256(medium).hexdigest() == "df6b0e82979329f15318356d060c2321095a2de7941539dfa0e007f08f2c2ff4"
    # This separate legacy identity is retained as fixed bytes captured from
    # immutable verifier-medium provenance (source commit
    # e02b9532e8dfd50aaafe480377a4aa735466697a, source blob
    # 86f6c753a1921f05b016927da1af3d2675552a2b). Do not reconstruct it from
    # the current checkout or Git history at test runtime.
    assert hashlib.sha1(b"blob 1811\0" + medium).hexdigest() == "85118f04eacad3b323800129e10d7b564d8abf7b"
    assert codex_adapter._agent_profile_state(medium, verifier_name) == "legacy"
    assert codex_adapter._agent_profile_state(verifier_legacy, "thaliris-implementer.toml") == "user"
    assert codex_adapter._agent_profile_state(
        codex_adapter._agent_profile("thaliris-implementer", "implementer", "gpt-5.6-luna", "medium"),
        verifier_name,
    ) == "user"
    assert codex_adapter._agent_profile_state(verifier_legacy + b"\nuser edit\n", verifier_name) == "user"
    (agents / verifier_name).write_bytes(verifier_legacy)
    first = codex_adapter.init(root)
    assert first["agent_profile_changed"] is False
    expected_manual = (
        ["canonical_executable_unavailable"]
        if first["canonical_executable_available"] == "NO"
        else []
    )
    assert first["manual_action_required"] == expected_manual
    for role in ("investigator", "curator", "implementer"):
        name = f"thaliris-{role}.toml"
        assert codex_adapter._agent_profile_state((agents / name).read_bytes(), name) == "legacy"
    verifier = (agents / verifier_name).read_text(encoding="utf-8")
    assert 'model = "gpt-5.6-luna"' in verifier
    assert 'model_reasoning_effort = "xhigh"' in verifier
    assert codex_adapter.init(root)["changed"] is False


def test_exact_historical_role_pack_migrates_and_unknown_bytes_are_preserved(tmp_path: Path) -> None:
    root = repo(tmp_path)
    packs = root / "docs" / "thaliris-role-packs.md"
    assert codex_adapter._role_pack_state(codex_adapter.ROLE_PACKS.encode("utf-8")) == "current"
    # Fixed LF/UTF-8 bytes from v5 (commit 7a940327, blob e06153d7), not
    # repository history: this remains valid in shallow clones and on Windows.
    legacy = (Path(__file__).parent / "fixtures" / "thaliris-role-packs-v5.md").read_bytes()
    assert len(legacy) == 5443
    assert hashlib.sha256(legacy).hexdigest() == "b6dba8d5d5e855face02667993601f84c4a54e77d7c33012d542a6b91483ec6c"
    assert codex_adapter._role_pack_state(legacy) == "legacy"
    packs.write_bytes(legacy)
    first = codex_adapter.init(root)
    assert packs.read_bytes() == codex_adapter.ROLE_PACKS.encode("utf-8")
    assert "docs/thaliris-role-packs.md" in first["files"]
    assert codex_adapter.init(root)["changed"] is False

    packs.write_bytes(legacy + b"\nuser edit\n")
    assert codex_adapter._role_pack_state(packs.read_bytes()) == "user"
    codex_adapter.init(root)
    assert packs.read_bytes() == legacy + b"\nuser edit\n"


def test_role_profiles_keep_routing_and_model_choice_with_the_controller() -> None:
    # Public ingress/binding facts remain mechanical contracts. Prompt ownership
    # and semantic concepts are tested separately in test_prompt_contract.py.
    assert codex_adapter._ROLE_MODEL_DEFAULTS == {
        "controller": (None, None),
        "investigator": ("gpt-6-luna", "xhigh"),
        "curator": ("gpt-6-luna", "xhigh"),
        "reasoning-specialist": ("gpt-6.1-sol", "high"),
        "implementer": ("gpt-6-luna", "xhigh"),
        "focused-implementer": ("gpt-6.1-sol", "high"),
        "verifier": ("gpt-6-luna", "xhigh"),
        "reviewer": ("gpt-6.1-sol", "high"),
    }
    for name, (model, effort, role) in codex_adapter._AGENT_PROFILES.items():
        parsed = tomllib.loads(codex_adapter._agent_profile(name[:-5], role, model, effort).decode())
        assert parsed["developer_instructions"] == roles.profile_instructions(role, name[:-5])
        assert "sandbox_mode" not in parsed
        assert "selected native spawn handoff is your task-specific input" in parsed["developer_instructions"]
        assert "selected supplemental evidence or factual correction within the same goal and role" in parsed["developer_instructions"]
    assert Path("docs/thaliris-role-packs.md").read_text(encoding="utf-8") == codex_adapter.render_role_packs()
    assert Path("docs/thaliris-role-registry.md").read_bytes() == roles.render_registry_document()
