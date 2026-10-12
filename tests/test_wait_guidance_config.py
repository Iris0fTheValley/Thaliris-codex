from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tomllib

import pytest

from thaliris_codex import codex_adapter as adapter, host_maintenance as maintenance, model_catalog_config as catalog
from thaliris_codex import host_transition, wait_guidance_config as guidance
from tests.test_host_maintenance_contract import intent
from tests.model_catalog_fixtures import without_managed_fragment


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
    assert catalog.KEY not in tomllib.loads((home / "config.toml").read_text()), result["native_model_catalog_compatibility"]["status"]
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("value", ['""', '"user instructions"'])
def test_existing_user_developer_instructions_are_never_claimed(tmp_path, target, value):
    home, _ = target
    original = f"developer_instructions = {value} # user-owned\n".encode()
    (home / "config.toml").write_bytes(original)

    result = install(tmp_path, target)
    assert result["ok"], json.dumps(result, indent=2)
    expected = "USER_EMPTY_PRESERVED" if value == '""' else "USER_CONFIG_PRESERVED"
    assert result["controller_wait_guidance_compatibility"]["status"] == expected
    assert result["manual_action_required"] == []
    assert guidance.RECORD_KEY not in receipt(home)
    assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == tomllib.loads(original.decode())[guidance.KEY]
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == original, json.dumps(removed, indent=2)


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
    catalog_record = receipt(home).get(catalog.RECORD_KEY)
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert removed["controller_wait_guidance_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert catalog.KEY not in tomllib.loads((home / "config.toml").read_text())
    # Uninstall removes the exact catalog fragment while preserving the edited
    # guidance as user-owned bytes.
    assert (home / "config.toml").read_bytes() == without_managed_fragment(edited, catalog_record)


def test_empty_user_edit_to_managed_guidance_is_distinguished_and_preserved(tmp_path, target):
    home, _ = target
    original = b'# keep this prefix\n'
    (home / "config.toml").write_bytes(original)
    assert install(tmp_path, target)["ok"]
    edited = (home / "config.toml").read_bytes().replace(
        json.dumps(guidance.GUIDANCE).encode(), b'""', 1)
    (home / "config.toml").write_bytes(edited)

    upgraded = install(tmp_path, target)
    assert upgraded["ok"], upgraded
    assert upgraded["controller_wait_guidance_compatibility"]["status"] == "USER_EMPTY_PRESERVED"
    assert (home / "config.toml").read_bytes() == edited
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert removed["controller_wait_guidance_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    removed_raw = (home / "config.toml").read_bytes()
    assert removed_raw.startswith(original)
    assert tomllib.loads(removed_raw.decode())[guidance.KEY] == ""


@pytest.mark.parametrize("old_guidance", [PRE_EVENT_FIRST_GUIDANCE, (Path(__file__).parent / "fixtures/all-layer-wait-predecessor/guidance.txt").read_text(encoding="utf-8"), (Path(__file__).parent / "fixtures/role-wait-scope-predecessor/guidance.txt").read_text(encoding="utf-8")], ids=["pre-event", "41157f5-event-first", "5d65c128-all-layer"])
@pytest.mark.parametrize("upgrade", [False, True], ids=["direct-old-uninstall", "upgrade-then-uninstall"])
def test_historical_template_record_remains_owned_across_upgrade_and_uninstall(tmp_path, target, monkeypatch, upgrade, old_guidance):
    home, _ = target
    original = b'# user config\r\n[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "user"\r\n'
    (home / "config.toml").write_bytes(original)
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
        assert upgraded["controller_wait_guidance_compatibility"]["changed"] is True
        migrated_record = receipt(home)[guidance.RECORD_KEY]
        assert migrated_record["fragment"] == guidance._fragment("\r\n")
        assert old_record["fragment"] in migrated_record["history"]
        expected_bytes = managed_bytes.replace(old_record["fragment"].encode(),
                                               migrated_record["fragment"].encode(), 1)
        assert (home / "config.toml").read_bytes() == expected_bytes
        assert tomllib.loads(expected_bytes.decode())[guidance.KEY] == current_guidance
        stable_receipt = receipt(home)
        repeated = install(tmp_path, target)
        assert repeated["ok"], repeated
        assert repeated["controller_wait_guidance_compatibility"]["status"] == "MANAGED"
        assert repeated["controller_wait_guidance_compatibility"]["changed"] is False
        assert receipt(home) == stable_receipt
        assert (home / "config.toml").read_bytes() == expected_bytes
    else:
        assert receipt(home)[guidance.RECORD_KEY] == old_record
        assert (home / "config.toml").read_bytes() == managed_bytes

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


def test_successive_guidance_receipts_keep_exact_history_for_uninstall(tmp_path, target, monkeypatch):
    home, _ = target
    original = b'# unrelated bytes\r\n[features.multi_agent_v2]\r\nmulti_agent_mode_hint_text = "user"\r\n'
    (home / "config.toml").write_bytes(original)
    first_text = "First historically managed guidance."
    second_text = "Second historically managed guidance."
    current_text = guidance.GUIDANCE
    monkeypatch.setattr(guidance, "GUIDANCE", first_text)
    assert install(tmp_path, target)["ok"]
    first_record = receipt(home)[guidance.RECORD_KEY]

    monkeypatch.setattr(guidance, "GUIDANCE", second_text)
    second = install(tmp_path, target)
    assert second["ok"], second
    second_record = receipt(home)[guidance.RECORD_KEY]
    assert first_record["fragment"] in second_record["history"]
    assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == second_text

    monkeypatch.setattr(guidance, "GUIDANCE", current_text)
    latest = install(tmp_path, target)
    assert latest["ok"], latest
    latest_record = receipt(home)[guidance.RECORD_KEY]
    assert first_record["fragment"] in latest_record["history"]
    assert second_record["fragment"] in latest_record["history"]
    assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == current_text
    assert uninstall(tmp_path, target)["ok"]
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("when,expected", [
    ("before", "APPLY_OUTCOME_UNKNOWN_PRESERVED"),
    ("after", "MANAGED"),
])
def test_interrupted_guidance_migration_recovers_from_journal_without_reacquisition(
        tmp_path, target, monkeypatch, when, expected):
    home, exe = target
    original = b'# keep this exact prefix\r\n[other]\r\nvalue = "preserve"\r\n'
    (home / "config.toml").write_bytes(original)
    old_text = "Receipt-proven prior guidance."
    current_text = guidance.GUIDANCE
    monkeypatch.setattr(guidance, "GUIDANCE", old_text)
    assert install(tmp_path, target)["ok"]
    old_raw = (home / "config.toml").read_bytes()
    old_record = receipt(home)[guidance.RECORD_KEY]
    monkeypatch.setattr(guidance, "GUIDANCE", current_text)
    contract = intent(tmp_path, home, exe)
    write = adapter._atomic_host_write

    class Interrupted(BaseException):
        pass

    def interrupt_migration(path, contents):
        if path == home / "config.toml":
            if when == "after":
                write(path, contents)
            raise Interrupted()
        return write(path, contents)

    monkeypatch.setattr(adapter, "_atomic_host_write", interrupt_migration)
    with pytest.raises(Interrupted):
        adapter.codex_install(maintenance_contract=contract)
    assert host_transition.pending(home)
    assert (home / "config.toml").read_bytes() == (
        old_raw if when == "before" else old_raw.replace(old_record["fragment"].encode(),
                                                          guidance._fragment("\r\n").encode(), 1))

    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    recovered = adapter.codex_install(maintenance_contract=contract)
    assert recovered["ok"], recovered
    assert recovered["controller_wait_guidance_compatibility"]["status"] == expected
    assert not host_transition.pending(home)
    current_record = receipt(home)[guidance.RECORD_KEY]
    assert old_record["fragment"] in current_record["history"]
    if when == "after":
        assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == current_text
    else:
        assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == old_text
        # A later explicit install may retry after the prior journal has safely
        # completed; recovery itself never repeats an uncertain write.
        retried = install(tmp_path, target)
        assert retried["ok"], retried
        assert retried["controller_wait_guidance_compatibility"]["status"] == "MANAGED"
        assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == current_text
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == original


def test_migration_checkpoint_failure_preserves_old_field_and_original_receipt(tmp_path, target, monkeypatch):
    home, exe = target
    original = b'root_value = "unchanged"\n'
    (home / "config.toml").write_bytes(original)
    old_text = "Still owned before the checkpoint."
    monkeypatch.setattr(guidance, "GUIDANCE", old_text)
    assert install(tmp_path, target)["ok"]
    old_raw = (home / "config.toml").read_bytes()
    old_record = receipt(home)[guidance.RECORD_KEY]
    monkeypatch.setattr(guidance, "GUIDANCE", "New value after durable checkpoint.")
    contract = intent(tmp_path, home, exe)
    write = host_transition._write

    def fail_attempt_checkpoint(path, transition):
        if transition["finish"].get("wait_guidance_phase") == "ATTEMPTING":
            raise OSError("simulated required migration journal failure")
        return write(path, transition)

    monkeypatch.setattr(host_transition, "_write", fail_attempt_checkpoint)
    failed = adapter.codex_install(maintenance_contract=contract)
    assert not failed["ok"], failed
    assert failed["transition_pending"] is True
    assert host_transition.pending(home)
    assert (home / "config.toml").read_bytes() == old_raw
    pending_record = receipt(home)[guidance.RECORD_KEY]
    assert old_record["fragment"] in pending_record["history"]

    monkeypatch.setattr(host_transition, "_write", write)
    recovered = adapter.codex_install(maintenance_contract=contract)
    assert recovered["ok"], recovered
    assert not host_transition.pending(home)
    assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == "New value after durable checkpoint."
    current_record = receipt(home)[guidance.RECORD_KEY]
    assert (home / "config.toml").read_bytes() == old_raw.replace(
        old_record["fragment"].encode(), current_record["fragment"].encode(), 1)
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("outcome,expected", [
    ("before", "OPTIONAL_WRITE_FAILED_PRESERVED"),
    ("after", "MANAGED"),
    ("user_edit", "APPLY_OUTCOME_UNKNOWN_PRESERVED"),
])
def test_migration_write_errors_preserve_field_and_unrelated_config(
        tmp_path, target, monkeypatch, outcome, expected):
    home, _ = target
    original = b'# preserve exactly\r\n[other]\r\nvalue = "unrelated"\r\n'
    (home / "config.toml").write_bytes(original)
    old_text = "Prior value for write-error test."
    current_text = guidance.GUIDANCE
    monkeypatch.setattr(guidance, "GUIDANCE", old_text)
    assert install(tmp_path, target)["ok"]
    old_raw = (home / "config.toml").read_bytes()
    old_record = receipt(home)[guidance.RECORD_KEY]
    monkeypatch.setattr(guidance, "GUIDANCE", current_text)
    write = adapter._atomic_host_write

    def fail_guidance_migration(path, contents):
        if path == home / "config.toml":
            if outcome == "after":
                write(path, contents)
            elif outcome == "user_edit":
                path.write_bytes(b'developer_instructions = "user edit"\n' + original)
            raise OSError("simulated guidance migration write error")
        return write(path, contents)

    monkeypatch.setattr(adapter, "_atomic_host_write", fail_guidance_migration)
    result = install(tmp_path, target)
    assert result["ok"], json.dumps(result, indent=2)
    assert result["host_integration_ready"] == "YES"
    assert result["transition_pending"] is False
    assert result["controller_wait_guidance_compatibility"]["status"] == expected
    installed_record = receipt(home)[guidance.RECORD_KEY]
    assert old_record["fragment"] in installed_record["history"]
    expected_bytes = {
        "before": old_raw,
        "after": old_raw.replace(old_record["fragment"].encode(),
                                  installed_record["fragment"].encode(), 1),
        "user_edit": b'developer_instructions = "user edit"\n' + original,
    }[outcome]
    assert (home / "config.toml").read_bytes() == expected_bytes

    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == (
        expected_bytes if outcome == "user_edit" else original)


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


def test_damaged_history_receipt_is_not_used_for_migration_or_overwrite(tmp_path, target, monkeypatch):
    home, _ = target
    original = b'# retain these unrelated bytes\r\n[other]\r\nvalue = "kept"\r\n'
    (home / "config.toml").write_bytes(original)
    old_text = "Trusted old exact field value."
    monkeypatch.setattr(guidance, "GUIDANCE", old_text)
    assert install(tmp_path, target)["ok"]
    monkeypatch.setattr(guidance, "GUIDANCE", "Current migration target.")
    assert install(tmp_path, target)["ok"]
    before = (home / "config.toml").read_bytes()
    tampered = receipt(home)
    tampered[guidance.RECORD_KEY]["history"][0] = "# incomplete ownership fragment\n"
    (home / maintenance.RECEIPT_NAME).write_text(json.dumps(tampered), encoding="utf-8")

    monkeypatch.setattr(guidance, "GUIDANCE", "A later migration target.")
    result = install(tmp_path, target)
    assert not result["ok"]
    assert (home / "config.toml").read_bytes() == before
    assert receipt(home) == tampered
    assert not host_transition.pending(home)


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


def test_guidance_keeps_only_generic_work_and_evidence_principles():
    text = guidance.GUIDANCE
    for clause in (
        "Continue necessary independent work before waiting", "meaningful native notifications",
        "do not wake models merely to observe unchanged state",
        "Messages, timeouts and exceptions do not prove completion", "preserve UNKNOWN",
        "without confirming the same completion again", "Observe your own tests or external processes",
        "Follow applicable role instructions and the selected handoff", "grants no role or authority",
    ):
        assert clause in text
    for role_policy in ("wait_agent", "3600000", "60-minute", "Controller", "Implementer", "Scanner", "final acceptance"):
        assert role_policy not in text


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
    actual = (home / "config.toml").read_bytes()
    if preexisting_managed:
        assert actual == installed
    else:
        assert without_managed_fragment(actual, receipt(home).get(catalog.RECORD_KEY)) == original

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
    actual = (home / "config.toml").read_bytes()
    if preexisting_managed:
        assert actual == expected_config
    else:
        assert without_managed_fragment(actual, receipt(home).get(catalog.RECORD_KEY)) == original
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
        catalog_fragment = catalog.fragment(home, "\n").encode()
        if (path == home / "config.toml" and guidance.GUIDANCE.encode() in contents and
                catalog_fragment not in contents):
            if write_outcome == "after":
                write(path, contents)
            elif write_outcome == "user_edit":
                path.write_bytes(b'developer_instructions = "user edit"\n' + original)
            raise OSError("simulated optional config write failure")
        return write(path, contents)

    monkeypatch.setattr(adapter, "_atomic_host_write", fail_guidance_write)
    result = install(tmp_path, target)

    assert result["ok"], json.dumps(result, indent=2)
    assert result["host_integration_ready"] == "YES"
    assert result["transition_pending"] is False
    assert result["controller_wait_guidance_compatibility"]["status"] == expected_status
    user_edit = b'developer_instructions = "user edit"\n' + original
    if write_outcome == "before":
        assert without_managed_fragment((home / "config.toml").read_bytes(),
                                        receipt(home).get(catalog.RECORD_KEY)) == original
    elif write_outcome == "after":
        assert tomllib.loads((home / "config.toml").read_text())[guidance.KEY] == guidance.GUIDANCE
    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    removed = uninstall(tmp_path, target)
    assert removed["ok"], removed
    assert (home / "config.toml").read_bytes() == (user_edit if write_outcome == "user_edit" else original)
