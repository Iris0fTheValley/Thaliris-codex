from __future__ import annotations

import json
import subprocess
import tomllib

import pytest

from thaliris_codex import codex_adapter as adapter, host_maintenance as maintenance
from thaliris_codex import host_transition, wait_guidance_config as guidance
from tests.test_host_maintenance_contract import intent


PRE_EVENT_FIRST_GUIDANCE = (
    "When awaiting a necessary native subagent, the general 60-second blocking-wait "
    "recommendation is not a fixed timeout limit. Choose an event-aware wait duration "
    "informed by the expected task, which may take several minutes or longer. Prefer "
    "native completion events over short polling loops. A timeout alone is not progress. "
    "Avoid unnecessary model wakeups and preserve responsiveness to interruptions and "
    "substantive events."
)


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
    assert result["manual_action_required"] == []
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
    edited = raw.replace(json.dumps(guidance.GUIDANCE).encode(), json.dumps(edited_value).encode(), 1)
    (home / "config.toml").write_bytes(edited)

    upgraded = install(tmp_path, target)
    assert upgraded["ok"], upgraded
    assert upgraded["controller_wait_guidance_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert (home / "config.toml").read_bytes() == edited
    result = uninstall(tmp_path, target)
    assert result["ok"], result
    assert (home / "config.toml").read_bytes() == edited


@pytest.mark.parametrize("upgrade", [False, True], ids=["direct-old-uninstall", "upgrade-then-uninstall"])
def test_historical_template_record_remains_owned_across_upgrade_and_uninstall(tmp_path, target, monkeypatch, upgrade):
    home, _ = target
    original = b'# user config\r\n[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\r\n'
    (home / "config.toml").write_bytes(original)
    old_guidance = PRE_EVENT_FIRST_GUIDANCE
    current_guidance = guidance.GUIDANCE
    monkeypatch.setattr(guidance, "GUIDANCE", old_guidance)

    first = install(tmp_path, target)
    assert first["ok"], first
    old_record = receipt(home)[guidance.RECORD_KEY]
    assert old_record["fragment"] == guidance._fragment("\r\n")
    managed_bytes = (home / "config.toml").read_bytes()
    assert tomllib.loads(managed_bytes.decode())[guidance.KEY] == old_guidance

    monkeypatch.setattr(guidance, "GUIDANCE", current_guidance)
    if upgrade:
        upgraded = install(tmp_path, target)
        assert upgraded["ok"], upgraded
        assert upgraded["controller_wait_guidance_compatibility"]["status"] == "MANAGED"
        assert (home / "config.toml").read_bytes() == managed_bytes
        assert receipt(home)[guidance.RECORD_KEY] == old_record

    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert removed["controller_wait_guidance_compatibility"]["status"] == "RESTORED_ABSENT"
    assert (home / "config.toml").read_bytes() == original


def test_user_edit_to_historical_template_is_not_reclaimed_on_upgrade_or_uninstall(
        tmp_path, target, monkeypatch):
    home, _ = target
    original = b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\n'
    (home / "config.toml").write_bytes(original)
    baseline_guidance = guidance.GUIDANCE
    old_guidance = PRE_EVENT_FIRST_GUIDANCE
    current_guidance = baseline_guidance
    monkeypatch.setattr(guidance, "GUIDANCE", old_guidance)
    first = install(tmp_path, target)
    assert first["ok"], first

    raw = (home / "config.toml").read_bytes()
    edited = raw.replace(old_guidance.encode(), (old_guidance + " User addition.").encode(), 1)
    (home / "config.toml").write_bytes(edited)
    monkeypatch.setattr(guidance, "GUIDANCE", current_guidance)

    upgraded = install(tmp_path, target)
    assert upgraded["ok"], upgraded
    assert upgraded["controller_wait_guidance_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert (home / "config.toml").read_bytes() == edited

    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert removed["controller_wait_guidance_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert (home / "config.toml").read_bytes() == edited


def test_unsupported_version_does_not_insert_guidance(tmp_path, target, monkeypatch):
    home, _ = target
    monkeypatch.setattr(guidance, "capability", lambda: "UNKNOWN")
    (home / "config.toml").write_bytes(b'# preserve this comment\n')
    result = install(tmp_path, target)
    assert result["ok"], result
    assert result["controller_wait_guidance_compatibility"]["status"] == "VERSION_SUPPORT_UNKNOWN"
    assert result["manual_action_required"] == []
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


def test_invalid_ownership_record_is_not_hidden_by_optional_config_read_error(tmp_path, target, monkeypatch):
    home, _ = target
    assert install(tmp_path, target)["ok"]
    record = receipt(home)[guidance.RECORD_KEY]
    record["fragment"] = "# forged optional ownership\n"

    def fail_config_read(path):
        raise OSError("simulated optional config read failure")

    monkeypatch.setattr(guidance, "read", fail_config_read)
    with pytest.raises(ValueError, match="invalid Controller wait guidance owned bytes"):
        guidance.plan_install(home, {guidance.RECORD_KEY: record})


def test_guidance_matches_the_accepted_waiting_priorities():
    text = guidance.GUIDANCE
    for clause in (
        "Prefer event-driven native wait_agent waiting over timed polling",
        "First confirm", "unconfirmed capabilities remain UNKNOWN",
        "When meaningful-event early return is confirmed and no dependency needs an interim decision",
        "default to the supported 60-minute window (timeout_ms=3600000)",
        "not a required execution duration", "native completion wakes Controller early",
        "Short historical averages must not force an earlier wake",
        "60 seconds for very short tasks", "10–60 minutes for ordinary tasks",
        "about 30 minutes for longer-task stage checks",
        "reliable events without interim decisions still favor 60 minutes",
        "higher-level duration limits", "take precedence", "never bypass Host limits",
        "messages and timeouts do not prove completion", "one available exact native status check",
        "without confirming the same completion again", "Do not substitute sleep",
        "per-child timed polling loops", "Executors own local tests and CI",
        "independent closing owns final acceptance",
    ):
        assert clause in text
    assert "general 60-second blocking-wait recommendation" not in text


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


@pytest.mark.parametrize("preexisting_managed", [False, True])
def test_optional_guidance_read_errors_do_not_fail_host_install(
        tmp_path, target, monkeypatch, preexisting_managed):
    home, _ = target
    original = b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\n'
    (home / "config.toml").write_bytes(original)
    if preexisting_managed:
        first = install(tmp_path, target)
        assert first["ok"], first
        installed = (home / "config.toml").read_bytes()
    read = guidance.read
    calls = 0

    def fail_finalization_read(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated optional config read failure")
        return read(path)

    monkeypatch.setattr(guidance, "read", fail_finalization_read)
    result = install(tmp_path, target)

    assert result["ok"], result
    assert result["host_integration_ready"] == "YES"
    assert result["transition_pending"] is False
    assert result["controller_wait_guidance_compatibility"]["status"] == "OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED"
    assert (home / "config.toml").read_bytes() == (installed if preexisting_managed else original)

    monkeypatch.setattr(guidance, "read", read)
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("preexisting_managed", [False, True])
def test_optional_guidance_planning_read_errors_preserve_install_and_ownership(
        tmp_path, target, monkeypatch, preexisting_managed):
    home, _ = target
    original = b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\n'
    (home / "config.toml").write_bytes(original)
    prior_record = None
    expected_config = original
    if preexisting_managed:
        first = install(tmp_path, target)
        assert first["ok"], first
        prior_record = receipt(home)[guidance.RECORD_KEY]
        expected_config = (home / "config.toml").read_bytes()
    read = guidance.read

    def fail_first_planning_read(path):
        raise OSError("simulated optional config planning read failure")

    monkeypatch.setattr(guidance, "read", fail_first_planning_read)
    result = install(tmp_path, target)

    assert result["ok"], result
    assert result["host_integration_ready"] == "YES"
    assert result["transition_pending"] is False
    assert result["controller_wait_guidance_compatibility"]["status"] == "OPTIONAL_CONFIG_UNAVAILABLE_PRESERVED"
    assert (home / "config.toml").read_bytes() == expected_config
    updated_receipt = receipt(home)
    if prior_record is None:
        assert guidance.RECORD_KEY not in updated_receipt
    else:
        assert updated_receipt[guidance.RECORD_KEY] == prior_record

    monkeypatch.setattr(guidance, "read", read)
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == original


def test_optional_guidance_journal_failure_stops_before_config_mutation(tmp_path, target, monkeypatch):
    home, exe = target
    original = b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\n'
    (home / "config.toml").write_bytes(original)
    contract = intent(tmp_path, home, exe)
    write = host_transition._write

    def fail_attempt_checkpoint(path, transition):
        if transition["finish"].get("wait_guidance_phase") == "ATTEMPTING":
            raise OSError("simulated required transition journal failure")
        return write(path, transition)

    monkeypatch.setattr(host_transition, "_write", fail_attempt_checkpoint)
    failed = adapter.codex_install(maintenance_contract=contract)
    assert not failed["ok"], failed
    assert failed["transition_pending"] is True
    assert host_transition.pending(home)
    assert (home / "config.toml").read_bytes() == original

    monkeypatch.setattr(host_transition, "_write", write)
    recovered = adapter.codex_install(maintenance_contract=contract)
    assert recovered["ok"], recovered
    assert not host_transition.pending(home)
    assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == guidance.GUIDANCE

    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("write_outcome,expected_status", [
    ("before", "OPTIONAL_WRITE_FAILED_PRESERVED"),
    ("after", "MANAGED"),
    ("user_edit", "APPLY_OUTCOME_UNKNOWN_PRESERVED"),
])
def test_optional_guidance_write_errors_do_not_fail_host_install(
        tmp_path, target, monkeypatch, write_outcome, expected_status):
    home, _ = target
    original = b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\n'
    (home / "config.toml").write_bytes(original)
    write = adapter._atomic_host_write

    def fail_guidance_write(path, contents):
        if path == home / "config.toml":
            if write_outcome == "after":
                write(path, contents)
            elif write_outcome == "user_edit":
                path.write_bytes(b'developer_instructions = "user edit"\n' + original)
            raise OSError("simulated optional config write failure")
        return write(path, contents)

    monkeypatch.setattr(adapter, "_atomic_host_write", fail_guidance_write)
    result = install(tmp_path, target)

    assert result["ok"], result
    assert result["host_integration_ready"] == "YES"
    assert result["transition_pending"] is False
    assert result["controller_wait_guidance_compatibility"]["status"] == expected_status
    user_edit = b'developer_instructions = "user edit"\n' + original
    if write_outcome == "before":
        assert (home / "config.toml").read_bytes() == original
    elif write_outcome == "after":
        assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == guidance.GUIDANCE
    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == (user_edit if write_outcome == "user_edit" else original)
