from __future__ import annotations

import json
import subprocess
import tomllib

import pytest

from thaliris_codex import codex_adapter as adapter, host_maintenance as maintenance
from thaliris_codex import host_transition, wait_guidance_config as guidance
from tests.test_host_maintenance_contract import intent


@pytest.fixture
def target(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(guidance, "capability", lambda: "SUPPORTED")
    exe, _ = pinned_test_thaliris
    return home, exe


def install(tmp_path, target):
    home, exe = target
    return adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))


def uninstall(tmp_path, target):
    home, exe = target
    return adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall"))


def receipt(home):
    return json.loads((home / maintenance.RECEIPT_NAME).read_bytes())


@pytest.mark.parametrize("original", [
    b"",
    b'# user comment\r\nmodel = "user"\r\n[other]\r\nflag = true\r\n',
    b'root_setting = "keep exactly"',
])
def test_install_upgrade_and_uninstall_preserve_config_bytes(tmp_path, target, original):
    home, _ = target
    (home / "config.toml").write_bytes(original)

    first = install(tmp_path, target)
    assert first["ok"], first
    assert first["controller_wait_guidance_compatibility"]["status"] == "MANAGED"
    assert first["controller_wait_guidance_compatibility"]["effective_session_status"] == "UNKNOWN"
    managed_bytes = (home / "config.toml").read_bytes()
    config = tomllib.loads(managed_bytes.decode("utf-8"))
    assert config[guidance.KEY] == guidance.GUIDANCE
    assert "config.toml" not in receipt(home)["owned_bytes"]
    assert guidance.RECORD_KEY in receipt(home)

    second = install(tmp_path, target)
    assert second["ok"], second
    assert second["controller_wait_guidance_compatibility"]["status"] == "MANAGED"
    assert second["controller_wait_guidance_compatibility"]["changed"] is False
    assert (home / "config.toml").read_bytes() == managed_bytes

    result = uninstall(tmp_path, target)
    assert result["ok"], result
    assert result["controller_wait_guidance_compatibility"]["status"] == "RESTORED_ABSENT"
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("value", ['""', '"user instructions"'])
def test_existing_user_developer_instructions_are_never_claimed(tmp_path, target, value):
    home, _ = target
    original = f"developer_instructions = {value} # user-owned\n".encode()
    (home / "config.toml").write_bytes(original)

    result = install(tmp_path, target)
    assert result["ok"], result
    assert result["controller_wait_guidance_compatibility"]["status"] == "USER_CONFIG_PRESERVED"
    assert guidance.RECORD_KEY not in receipt(home)
    assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == tomllib.loads(original.decode())[guidance.KEY]
    assert uninstall(tmp_path, target)["ok"]
    assert (home / "config.toml").read_bytes() == original


def test_user_edit_to_managed_guidance_survives_upgrade_and_uninstall(tmp_path, target):
    home, _ = target
    original = b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\n'
    (home / "config.toml").write_bytes(original)
    assert install(tmp_path, target)["ok"]
    edited_value = guidance.GUIDANCE + " User addition."
    raw = (home / "config.toml").read_bytes()
    edited = raw.replace(guidance.GUIDANCE.encode(), edited_value.encode(), 1)
    (home / "config.toml").write_bytes(edited)

    upgraded = install(tmp_path, target)
    assert upgraded["ok"], upgraded
    assert upgraded["controller_wait_guidance_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert (home / "config.toml").read_bytes() == edited
    result = uninstall(tmp_path, target)
    assert result["ok"], result
    assert (home / "config.toml").read_bytes() == edited


def test_unsupported_version_does_not_insert_guidance(tmp_path, target, monkeypatch):
    home, _ = target
    monkeypatch.setattr(guidance, "capability", lambda: "UNKNOWN")
    (home / "config.toml").write_bytes(b'# preserve this comment\n')
    result = install(tmp_path, target)
    assert result["ok"], result
    assert result["controller_wait_guidance_compatibility"]["status"] == "VERSION_SUPPORT_UNKNOWN"
    assert guidance.RECORD_KEY not in receipt(home)
    assert guidance.GUIDANCE.encode() not in (home / "config.toml").read_bytes()
    assert uninstall(tmp_path, target)["ok"]


def test_invalid_ownership_record_fails_closed_before_config_mutation(tmp_path, target):
    home, _ = target
    assert install(tmp_path, target)["ok"]
    record = receipt(home)
    record[guidance.RECORD_KEY]["fragment"] = "# remove the user's field\n"
    (home / maintenance.RECEIPT_NAME).write_text(json.dumps(record), encoding="utf-8")
    before = (home / "config.toml").read_bytes()

    result = uninstall(tmp_path, target)
    assert not result["ok"]
    assert (home / "config.toml").read_bytes() == before
    assert host_transition.pending(home) is False


def test_guidance_matches_the_accepted_waiting_text():
    assert guidance.GUIDANCE == (
        "When awaiting a necessary native subagent, the general 60-second blocking-wait "
        "recommendation is not a fixed timeout limit. Choose an event-aware wait duration "
        "informed by the expected task, which may take several minutes or longer. Prefer "
        "native completion events over short polling loops. A timeout alone is not progress. "
        "Avoid unnecessary model wakeups and preserve responsiveness to interruptions and "
        "substantive events."
    )


@pytest.mark.parametrize("reported,supported", [
    ("codex-cli 0.162.0", True),
    ("codex-cli 0.162.1", True),
    ("codex-cli 0.162.0-alpha.2", True),
    ("codex-cli 0.161.9", False),
    ("codex-cli 0.163.0", False),
    ("garbage", False),
])
def test_version_capability_is_limited_to_0162(monkeypatch, reported, supported):
    monkeypatch.setattr(guidance.shutil, "which", lambda name: "controlled-fake-codex")
    monkeypatch.setattr(guidance.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, reported, ""))
    assert guidance.capability() == ("SUPPORTED" if supported else "UNKNOWN")


@pytest.mark.parametrize("when,expected", [
    ("before", "APPLY_OUTCOME_UNKNOWN_PRESERVED"),
    ("after", "MANAGED"),
    ("after_user_delete", "APPLY_OUTCOME_UNKNOWN_PRESERVED"),
])
def test_interrupted_guidance_write_is_reconciled_without_reacquisition(tmp_path, target, monkeypatch, when, expected):
    home, exe = target
    # A user-owned mode-hint value avoids a prior config write in this transition.
    original = b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\n'
    (home / "config.toml").write_bytes(original)
    contract = intent(tmp_path, home, exe)
    write = adapter._atomic_host_write

    class Interrupted(BaseException):
        pass

    def interrupt_guidance(path, contents):
        if path == home / "config.toml":
            if when != "before":
                write(path, contents)
            raise Interrupted()
        return write(path, contents)

    monkeypatch.setattr(adapter, "_atomic_host_write", interrupt_guidance)
    with pytest.raises(Interrupted):
        adapter.codex_install(maintenance_contract=contract)
    assert host_transition.pending(home)
    assert guidance.RECORD_KEY in receipt(home)
    if when == "after_user_delete":
        raw = (home / "config.toml").read_bytes()
        (home / "config.toml").write_bytes(raw.replace(receipt(home)[guidance.RECORD_KEY]["fragment"].encode(), b"", 1))
    if expected == "MANAGED":
        assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == guidance.GUIDANCE
    else:
        assert guidance.KEY not in tomllib.loads((home / "config.toml").read_text())

    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    result = adapter.codex_install(maintenance_contract=contract)
    assert result["ok"], result
    assert result["controller_wait_guidance_compatibility"]["status"] == expected
    if expected == "MANAGED":
        assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == guidance.GUIDANCE
    else:
        assert guidance.KEY not in tomllib.loads((home / "config.toml").read_text())
    assert not host_transition.pending(home)
    result = uninstall(tmp_path, target)
    assert result["ok"], result
    assert (home / "config.toml").read_bytes() == original
