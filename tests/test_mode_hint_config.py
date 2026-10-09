from __future__ import annotations

import json
import tomllib

import pytest

from thaliris_codex import codex_adapter as adapter, host_maintenance as maintenance, host_transition, mode_hint_config as hint
from tests.test_host_maintenance_contract import intent, snapshot
from thaliris_codex.codex_app_server import owned_hook_keys_from_host as real_owned_keys, remove_owned_hook_trust as real_remove_trust


@pytest.fixture
def target(tmp_path, monkeypatch, pinned_test_thaliris):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(hint, "capability", lambda: "SUPPORTED")
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


@pytest.mark.parametrize("original", [b"", b'# user comment\r\nmodel = "user"\r\n',
    b'[features]\nmulti_agent = true\n',
    b'[features.multi_agent_v2]',
    b'[features.multi_agent_v2] # keep\n# user\nother = true\n[other]\nx = 3\n'])
def test_first_install_upgrade_and_field_restore(tmp_path, target, original):
    home, _ = target
    (home / "config.toml").write_bytes(original)
    result = install(tmp_path, target)
    assert result["ok"], result
    assert result["native_mode_hint_compatibility"]["status"] == "MANAGED"
    config = (home / "config.toml").read_bytes()
    assert hint.leaf(tomllib.loads(config.decode())) == (True, "")
    managed = receipt(home)
    assert "config.toml" not in managed["owned_bytes"]
    assert managed[hint.RECORD_KEY]["prior"] == {"present": False}
    result = install(tmp_path, target)
    assert result["ok"] and result["native_mode_hint_compatibility"]["changed"] is False
    assert receipt(home) == managed
    assert (home / "config.toml").read_bytes() == config
    result = uninstall(tmp_path, target)
    assert result["ok"], result
    assert result["native_mode_hint_compatibility"]["status"] == "RESTORED_ABSENT"
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("value,expected", [('""', "USER_EMPTY_PRESERVED"), ('"my custom instructions"', "USER_CUSTOM_PRESERVED"),
    ('42', "USER_CUSTOM_PRESERVED"), ('[]', "USER_CUSTOM_PRESERVED")])
def test_existing_user_leaf_never_claimed(tmp_path, target, value, expected):
    home, _ = target
    original = f'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = {value} # user\n'.encode()
    (home / "config.toml").write_bytes(original)
    for _ in range(2):
        result = install(tmp_path, target)
        assert result["ok"], result
        assert result["native_mode_hint_compatibility"]["status"] == expected
        assert hint.RECORD_KEY not in receipt(home)
    assert uninstall(tmp_path, target)["ok"]
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("change", ["custom", "delete", "empty_without_marker", "structure", "non_table_parent"])
def test_user_later_changes_preserved_on_upgrade_and_uninstall(tmp_path, target, change):
    home, _ = target
    assert install(tmp_path, target)["ok"]
    text = (home / "config.toml").read_text()
    if change == "custom":
        text = text.replace('= ""', '= "custom"')
    elif change == "delete":
        text = text.replace(hint.MARKER, "")
    elif change == "empty_without_marker":
        text = text.replace("# thaliris:multi-agent-mode-hint\n", "")
    elif change == "structure":
        text = '# user restructuring\nfeatures = { multi_agent_v2 = { multi_agent_mode_hint_text = "" } }\n'
    else:
        text = '# user restructuring\nfeatures = false\n'
    (home / "config.toml").write_text(text, encoding="utf-8")
    edited = (home / "config.toml").read_bytes()
    result = install(tmp_path, target)
    assert result["ok"], result
    assert result["native_mode_hint_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert hint.RECORD_KEY in receipt(home)
    assert (home / "config.toml").read_bytes() == edited
    result = uninstall(tmp_path, target)
    assert result["ok"], result
    assert (home / "config.toml").read_bytes() == edited


def test_restore_preserves_new_sibling_and_other_comments(tmp_path, target):
    home, _ = target
    original = b'# original\nmodel = "user"\n'
    (home / "config.toml").write_bytes(original)
    assert install(tmp_path, target)["ok"]
    with (home / "config.toml").open("ab") as file:
        file.write(b'# later comment\nother = true\n[unrelated]\nx = 7\n')
    assert uninstall(tmp_path, target)["ok"]
    raw = (home / "config.toml").read_bytes()
    assert raw.startswith(original)
    assert b'# later comment\nother = true' in raw
    parsed = tomllib.loads(raw.decode())
    assert parsed["features"]["multi_agent_v2"]["other"] is True
    assert parsed["unrelated"]["x"] == 7
    assert not hint.leaf(parsed)[0]


@pytest.mark.parametrize("original", [b'features = 3\n', b'[features]\nmulti_agent_v2 = 3\n', b'bad = [\n'])
def test_malformed_or_non_table_parent_fails_before_mutation(tmp_path, target, original):
    home, _ = target
    (home / "config.toml").write_bytes(original)
    before = snapshot(home)
    result = install(tmp_path, target)
    assert not result["ok"] and not result["changed"]
    assert snapshot(home) == before


def test_inline_structure_and_unknown_version_preserved(tmp_path, target, monkeypatch):
    home, _ = target
    original = b'features = { multi_agent_v2 = { other = true } }\n'
    (home / "config.toml").write_bytes(original)
    result = install(tmp_path, target)
    assert result["native_mode_hint_compatibility"]["status"] == "STRUCTURE_UNSUPPORTED_PRESERVED"
    assert (home / "config.toml").read_bytes() == original
    (home / "config.toml").write_bytes(b'# user\n')
    monkeypatch.setattr(hint, "capability", lambda: "UNKNOWN")
    result = install(tmp_path, target)
    assert result["native_mode_hint_compatibility"]["status"] == "VERSION_SUPPORT_UNKNOWN"
    assert hint.RECORD_KEY not in receipt(home)
    assert (home / "config.toml").read_bytes() == b'# user\n'


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("newline", ["\n", "\r\n", ""])
def test_boolean_feature_migration_keeps_enabled_and_restores_exact_source(tmp_path, target, value, newline):
    home, _ = target
    eol = newline or "\n"
    original = ('# user feature flag' + eol + '[features]' + eol +
                'multi_agent_v2 = ' + str(value).lower() + ' # keep user choice' + newline).encode()
    (home / "config.toml").write_bytes(original)
    result = install(tmp_path, target)
    assert result["ok"], result
    config = hint.read(home)[1]
    assert config["features"]["multi_agent_v2"]["enabled"] is value
    assert hint.leaf(config) == (True, "")
    assert receipt(home)[hint.RECORD_KEY]["bool_migration"]["value"] is value
    assert install(tmp_path, target)["ok"]
    result = uninstall(tmp_path, target)
    assert result["native_mode_hint_compatibility"]["status"] == "RESTORED_ABSENT"
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("value", [True, False])
def test_root_dotted_boolean_migration_restores_source(tmp_path, target, value):
    home, _ = target
    original = f'# root dotted flag\nfeatures.multi_agent_v2 = {str(value).lower()} # user choice\n[other]\nx = 3\n'.encode()
    (home / "config.toml").write_bytes(original)
    assert install(tmp_path, target)["ok"]
    assert hint.read(home)[1]["features"]["multi_agent_v2"]["enabled"] is value
    assert uninstall(tmp_path, target)["ok"]
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("change", ["enabled", "sibling", "marker"])
def test_boolean_scaffold_user_edits_preserved_on_field_restore(tmp_path, target, change):
    home, _ = target
    original = b'[features]\nother_feature = true\nmulti_agent_v2 = false # user choice\n'
    (home / "config.toml").write_bytes(original)
    assert install(tmp_path, target)["ok"]
    text = (home / "config.toml").read_text()
    if change == "enabled":
        text = text.replace('enabled = false', 'enabled = true # user edit')
    elif change == "sibling":
        text += '# new feature setting\nother = 3\n'
    else:
        text = text.replace(hint.BOOL_MARKER, '# user original ')
    (home / "config.toml").write_bytes(text.encode("utf-8"))
    expected = hint.without_leaf(hint.read(home)[1])
    result = uninstall(tmp_path, target)
    assert result["ok"], result
    assert result["native_mode_hint_compatibility"]["status"] == "RESTORED_ABSENT_STRUCTURE_PRESERVED"
    config = hint.read(home)[1]
    assert not hint.leaf(config)[0]
    assert hint.without_leaf(config) == expected
    assert config["features"]["multi_agent_v2"]["enabled"] is (change == "enabled")


def test_upgrade_legacy_receipt_then_manage_absent_leaf(tmp_path, target, monkeypatch):
    home, _ = target
    monkeypatch.setattr(hint, "capability", lambda: "UNKNOWN")
    assert install(tmp_path, target)["ok"]
    assert hint.RECORD_KEY not in receipt(home)
    monkeypatch.setattr(hint, "capability", lambda: "SUPPORTED")
    result = install(tmp_path, target)
    assert result["native_mode_hint_compatibility"]["status"] == "MANAGED"
    assert uninstall(tmp_path, target)["ok"]
    assert not hint.leaf(tomllib.loads((home / "config.toml").read_text()))[0]


@pytest.mark.parametrize("stage", ["receipt", "config", "trust"])
def test_failures_leave_restoration_evidence_and_replay(tmp_path, target, monkeypatch, stage):
    home, exe = target
    path = intent(tmp_path, home, exe)
    write = adapter._atomic_host_write
    trust = adapter._install_host_hook_trust
    def failing_write(target, contents):
        if target == home / (maintenance.RECEIPT_NAME if stage == "receipt" else "config.toml"):
            raise OSError("injected write failure")
        return write(target, contents)
    if stage == "trust":
        monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *args: (_ for _ in ()).throw(ValueError("RPC failed")))
    else:
        monkeypatch.setattr(adapter, "_atomic_host_write", failing_write)
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home), result
    assert not (home / "config.toml").exists()
    journal = json.loads((home / host_transition.NAME).read_bytes())
    assert journal["finish"]["mode_hint_record"]["prior"] == {"present": False}
    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    monkeypatch.setattr(adapter, "_install_host_hook_trust", trust)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"] and not host_transition.pending(home), result
    assert hint.RECORD_KEY in receipt(home)
    assert uninstall(tmp_path, target)["ok"]
    assert (home / "config.toml").read_bytes() == b""


@pytest.mark.parametrize("corrupt", ["path", "prior", "fragment"])
def test_invalid_receipt_refuses_without_mutation(tmp_path, target, corrupt):
    home, _ = target
    assert install(tmp_path, target)["ok"]
    record = receipt(home)
    record[hint.RECORD_KEY][corrupt] = {"path": str(home / "other.toml"), "prior": {"present": True, "value": ""}, "fragment": "remove user bytes"}[corrupt]
    (home / maintenance.RECEIPT_NAME).write_text(json.dumps(record))
    before = snapshot(home)
    result = install(tmp_path, target)
    assert not result["ok"] and not result["changed"]
    assert snapshot(home) == before


@pytest.mark.parametrize("when", ["before", "after", "after_user_delete"])
def test_process_interruption_never_reacquires_deleted_leaf(tmp_path, target, monkeypatch, when):
    home, exe = target
    path = intent(tmp_path, home, exe)
    original = adapter._atomic_host_write
    class Interrupted(BaseException):
        pass
    def interrupted(target, contents):
        if target == home / "config.toml":
            if when != "before":
                original(target, contents)
            raise Interrupted()
        return original(target, contents)
    monkeypatch.setattr(adapter, "_atomic_host_write", interrupted)
    with pytest.raises(Interrupted):
        adapter.codex_install(maintenance_contract=path)
    assert host_transition.pending(home)
    assert receipt(home)[hint.RECORD_KEY]["prior"] == {"present": False}
    if when == "after_user_delete":
        (home / "config.toml").write_bytes(b'')
    monkeypatch.setattr(adapter, "_atomic_host_write", original)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"] and not host_transition.pending(home), result
    expected = "MANAGED" if when == "after" else "APPLY_OUTCOME_UNKNOWN_PRESERVED"
    assert result["native_mode_hint_compatibility"]["status"] == expected
    if when != "after":
        assert not hint.leaf(hint.read(home)[1])[0]
        assert install(tmp_path, target)["native_mode_hint_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert uninstall(tmp_path, target)["ok"]
    assert not hint.leaf(hint.read(home)[1])[0]


def test_uninstall_field_failure_keeps_journal_for_exact_retry(tmp_path, target, monkeypatch):
    home, exe = target
    assert install(tmp_path, target)["ok"]
    original = adapter._atomic_host_write
    def failed(target, contents):
        if target == home / "config.toml":
            raise OSError("field cleanup unavailable")
        return original(target, contents)
    path = intent(tmp_path, home, exe, "codex-uninstall")
    monkeypatch.setattr(adapter, "_atomic_host_write", failed)
    result = adapter.codex_uninstall(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home), result
    assert hint.leaf(hint.read(home)[1]) == (True, "")
    assert not (home / maintenance.RECEIPT_NAME).exists()
    monkeypatch.setattr(adapter, "_atomic_host_write", original)
    result = adapter.codex_uninstall(maintenance_contract=path)
    assert result["ok"] and not host_transition.pending(home), result
    assert not hint.leaf(hint.read(home)[1])[0]


def test_marker_moved_to_unrelated_table_does_not_prove_ownership(tmp_path, target):
    home, _ = target
    assert install(tmp_path, target)["ok"]
    edited = ('[features.multi_agent_v2]\nmulti_agent_mode_hint_text = "" # user\n'
              '[unrelated]\n' + hint.MARKER).encode()
    (home / "config.toml").write_bytes(edited)
    result = install(tmp_path, target)
    assert result["native_mode_hint_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert uninstall(tmp_path, target)["ok"]
    assert (home / "config.toml").read_bytes() == edited


def test_field_management_with_real_trust_code_and_disk_rpc_fake(tmp_path, target, monkeypatch):
    from thaliris_codex import codex_app_server, lifecycle
    from tests.test_codex_hook_trust import FakeAppServer
    home, _ = target
    original = b'# user flags\n[features]\nmulti_agent_v2 = false # user choice\n'
    (home / "config.toml").write_bytes(original)
    state = {"hashes": {event: f"sha256:{event}" for event in lifecycle.HOOK_EVENTS},
             "state": {"user-owned": {"enabled": False, "trusted_hash": "user-hash"}}, "disk_block": b""}
    calls = []
    def block():
        lines = ['[hooks.state]']
        for key, value in state["state"].items():
            pairs = [name + ' = ' + json.dumps(item) for name, item in value.items()]
            lines.append(json.dumps(key) + ' = { ' + ', '.join(pairs) + ' }')
        return ('\n'.join(lines) + '\n').encode()
    class DiskFake(FakeAppServer):
        def request(self, method, params):
            calls.append((method, params))
            if method == "config/read":
                raw, config = hint.read(home)
                return {"config": config, "layers": [{"name": {"type": "user", "file": str(home / "config.toml")},
                        "version": "sha256:" + maintenance.digest(raw), "config": config}], "origins": {}}
            result = super().request(method, params)
            if method == "config/batchWrite":
                raw = (home / "config.toml").read_bytes()
                previous, updated = state["disk_block"], block()
                assert not previous or raw.count(previous) == 1
                (home / "config.toml").write_bytes(raw.replace(previous, updated, 1) if previous else raw + updated)
                state["disk_block"] = updated
            return result
    def factory(selected_home):
        return DiskFake(selected_home, state)

    monkeypatch.setattr(codex_app_server, "_app_server_client", factory)
    monkeypatch.setattr(adapter, "_install_host_hook_trust", codex_app_server.trust_installed_host_hooks)
    monkeypatch.setattr(codex_app_server, "owned_hook_keys_from_host", real_owned_keys)
    monkeypatch.setattr(codex_app_server, "remove_owned_hook_trust", real_remove_trust)
    result = install(tmp_path, target)
    assert result["ok"], result
    assert hint.leaf(hint.read(home)[1]) == (True, "")
    assert hint.read(home)[1]["features"]["multi_agent_v2"]["enabled"] is False
    result = uninstall(tmp_path, target)
    assert result["ok"], result
    raw, config = hint.read(home)
    assert raw.startswith(original)
    assert config["features"]["multi_agent_v2"] is False
    assert config["hooks"]["state"] == {"user-owned": {"enabled": False, "trusted_hash": "user-hash"}}
    writes = [params for method, params in calls if method == "config/batchWrite"]
    assert all(params["edits"][0]["keyPath"] == "hooks.state" for params in writes)
    assert writes[-1]["expectedVersion"].startswith("sha256:")


@pytest.mark.parametrize("reported", ["codex-cli 0.162.0-alpha.2", "codex-cli 0.161.0", "codex-cli 0.163.0", "garbage"])
def test_version_support_boundary(monkeypatch, reported):
    import subprocess
    monkeypatch.setattr(hint.shutil, "which", lambda name: "controlled-fake-codex")
    monkeypatch.setattr(hint.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, reported, ""))
    assert hint.capability() == ("SUPPORTED" if reported == hint.SUPPORTED_VERSION else "UNKNOWN")
