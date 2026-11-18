"""Seamless, receipt-authorized model catalog refresh after a Codex CLI change."""
from __future__ import annotations

import json
import subprocess

import pytest

from thaliris_codex import catalog_recovery, catalog_refresh, cli, codex_adapter as adapter, codex_bootstrap
from thaliris_codex import host_maintenance as maintenance, host_transition, lifecycle, model_catalog_config as catalog, runtime_identity
from tests.model_catalog_fixtures import CLI_0170, catalog_0170, observed_catalog
from tests.test_host_maintenance_contract import intent, snapshot
from tests.test_nested_scanner import active  # noqa: F401

OLD = {"cli_version": "codex-cli 0.165.0", "cli_sha256": "a" * 64}
NEW = {"cli_version": CLI_0170, "cli_sha256": "b" * 64}


class FakeCli:
    """One observable Codex CLI: its reported version, binary identity and export."""

    def __init__(self, monkeypatch, identity):
        self.identity = dict(identity)
        self.exports: list[tuple[str, float]] = []
        self.raw = observed_catalog
        self.failure: Exception | None = None
        monkeypatch.setattr(catalog, "current_cli_identity", lambda: dict(self.identity))
        monkeypatch.setattr(catalog, "_executable", lambda: "codex-under-test")
        monkeypatch.setattr(catalog, "_version_provenance", lambda _exe: self.identity["cli_version"])
        monkeypatch.setattr(catalog, "export_upstream", self.export)

    def export(self, _home, *, source="online", timeout=90):
        self.exports.append((source, timeout))
        if self.failure is not None:
            raise self.failure
        return self.raw(source), dict(self.identity) | {
            "kind": source, "online_freshness": "VERIFIED" if source == "online" else "UNKNOWN"}

    def upgrade(self):
        self.identity = dict(NEW)
        self.raw = catalog_0170


@pytest.fixture
def installed(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    fake = FakeCli(monkeypatch, OLD)
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"] and result["catalog_goal_met"], result
    fake.exports.clear()
    return home, fake


def receipt(home):
    return json.loads((home / maintenance.RECEIPT_NAME).read_bytes())


def surface(home):
    return maintenance.surface_status(home, maintenance.ownership(home, maintenance._installed(home), {}))


def changed(before, after):
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def test_cli_change_refreshes_only_catalog_and_its_receipt_entry(installed):
    home, fake = installed
    before = snapshot(home)
    assert surface(home)["status"] == "MATCH"
    assert catalog_refresh.refresh(home, automatic=True)["status"] == catalog_refresh.CURRENT
    assert fake.exports == []  # unchanged CLI: no export at SessionStart
    fake.upgrade()
    assert catalog_refresh.state(home)["reason"] == "CLI_CHANGED"
    result = catalog_refresh.refresh(home, automatic=True)
    assert result["ok"] and result["changed"] and result["status"] == catalog_refresh.REFRESHED, result
    assert fake.exports == [("online", catalog_refresh.AUTOMATIC_EXPORT_TIMEOUT)]  # recorded source kind
    after = snapshot(home)
    assert changed(before, after) == {catalog.NAME, maintenance.RECEIPT_NAME}
    old_receipt, new_receipt = json.loads(before[maintenance.RECEIPT_NAME]), receipt(home)
    assert {k: v for k, v in new_receipt.items() if k != catalog.RECORD_KEY} == {
        k: v for k, v in old_receipt.items() if k != catalog.RECORD_KEY}
    record = new_receipt[catalog.RECORD_KEY]
    assert record["source"]["cli_version"] == CLI_0170 and record["source"]["cli_sha256"] == NEW["cli_sha256"]
    assert record["catalog_sha256"] == catalog.digest(after[catalog.NAME])
    assert {k: record[k] for k in ("path", "catalog_path", "prior", "fragment")} == {
        k: old_receipt[catalog.RECORD_KEY][k] for k in ("path", "catalog_path", "prior", "fragment")}
    models = {model["slug"]: model for model in json.loads(after[catalog.NAME])["models"]}
    assert {"gpt-6.2-sol", "gpt-6.2-astra"} <= set(models)
    assert models["gpt-6.2-sol"]["multi_agent_version"] == "v2"
    assert catalog.TARGET not in after[catalog.NAME].decode()
    # Runtime identity is untouched and Host status keeps reporting MATCH.
    assert after[runtime_identity.MANIFEST_NAME] == before[runtime_identity.MANIFEST_NAME]
    assert after["config.toml"] == before["config.toml"]
    assert surface(home)["status"] == "MATCH"
    assert surface(home)["owned_config_fragments"][catalog.RECORD_KEY] == "MATCH"
    # The next session and a later install see a current, reusable catalog.
    assert catalog_refresh.refresh(home, automatic=True)["status"] == catalog_refresh.CURRENT
    assert catalog_refresh.state(home)["status"] == catalog_refresh.CURRENT
    assert catalog_refresh.refresh(home)["status"] == catalog_refresh.CURRENT
    assert len(fake.exports) == 1
    reused, selected, raw = catalog.plan_install(home, new_receipt)
    assert selected["compatible_reuse"] is True and reused == record and raw is None


def test_bundled_install_refreshes_offline_from_the_bundled_source(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    fake = FakeCli(monkeypatch, OLD)
    contract = intent(tmp_path, home, exe)
    value = json.loads(contract.read_bytes())
    value["model_catalog_source"] = "bundled"
    contract.write_text(json.dumps(value))
    assert adapter.codex_install(maintenance_contract=contract)["ok"]
    fake.exports.clear()
    fake.upgrade()
    result = catalog_refresh.refresh(home, automatic=True)
    assert result["status"] == catalog_refresh.REFRESHED, result
    assert fake.exports == [("bundled", catalog_refresh.AUTOMATIC_EXPORT_TIMEOUT)]
    assert receipt(home)[catalog.RECORD_KEY]["source"]["kind"] == "bundled"
    assert surface(home)["status"] == "MATCH"


def _edit_catalog(home, fake):
    path = home / catalog.NAME
    path.write_bytes(path.read_bytes() + b"\n")


def _remove_field(home, fake):
    record = receipt(home)[catalog.RECORD_KEY]
    path = home / "config.toml"
    path.write_bytes(path.read_bytes().replace(record["fragment"].encode(), b"", 1))


def _incompatible(home, fake):
    fake.raw = lambda source: catalog_0170(source, previous_for="gpt-6.2-sol")


def _export_fails(home, fake):
    fake.failure = ValueError("UPSTREAM_EXPORT_FAILED")


def _pending(home, fake):
    (home / host_transition.NAME).write_text("{}", encoding="utf-8")


@pytest.mark.parametrize(("unsafe", "reason", "exports"), [
    (_edit_catalog, "CATALOG_CHANGED_PRESERVED", 0),
    (_remove_field, "CATALOG_FIELD_NOT_MANAGED", 0),
    (_incompatible, "TEMPLATE_INCOMPATIBILITY_PRESERVED", 1),
    (_export_fails, "UPSTREAM_REFRESH_FAILED_PRESERVED", 1),
])
def test_unsafe_refresh_writes_nothing_and_reports_the_exact_command(installed, unsafe, reason, exports):
    home, fake = installed
    fake.upgrade()
    unsafe(home, fake)
    before = snapshot(home)
    result = catalog_refresh.refresh(home, automatic=True)
    assert result["ok"] is False and result["changed"] is False
    assert result["status"] == catalog_refresh.STALE and result["reason"] == reason, result
    assert catalog_refresh.COMMAND in result["command"]
    assert result["ordinary_work_blocked"] is False
    assert len(fake.exports) == exports
    assert snapshot(home) == before


def test_pending_transition_defers_refresh(installed):
    home, fake = installed
    fake.upgrade()
    _pending(home, fake)
    before = snapshot(home)
    for automatic in (True, False):
        result = catalog_refresh.refresh(home, automatic=automatic)
        assert result["status"] == "HOST_TRANSITION_PENDING" and result["changed"] is False
    assert catalog_refresh.state(home)["status"] == "HOST_TRANSITION_PENDING"
    assert fake.exports == [] and snapshot(home) == before


def test_concurrent_change_during_export_writes_nothing(installed, monkeypatch):
    home, fake = installed
    fake.upgrade()
    planner = catalog._exported_record

    def racing(*args, **kwargs):
        planned = planner(*args, **kwargs)
        with (home / "config.toml").open("ab") as stream:
            stream.write(b"\n# concurrent user edit\n")
        return planned

    monkeypatch.setattr(catalog, "_exported_record", racing)
    before_catalog, before_receipt = (home / catalog.NAME).read_bytes(), (home / maintenance.RECEIPT_NAME).read_bytes()
    result = catalog_refresh.refresh(home, automatic=True)
    assert result["status"] == catalog_refresh.STALE and result["reason"] == "HOST_CHANGED_DURING_REFRESH"
    assert (home / catalog.NAME).read_bytes() == before_catalog
    assert (home / maintenance.RECEIPT_NAME).read_bytes() == before_receipt


def test_interrupted_refresh_is_reported_then_completed_explicitly(installed, monkeypatch):
    home, fake = installed
    fake.upgrade()
    before_receipt = (home / maintenance.RECEIPT_NAME).read_bytes()
    write = adapter._atomic_host_write

    def crash_before_receipt(path, contents):
        if path.name == maintenance.RECEIPT_NAME:
            raise OSError("simulated interruption")
        write(path, contents)

    monkeypatch.setattr(adapter, "_atomic_host_write", crash_before_receipt)
    result = catalog_refresh.refresh(home, automatic=True)
    assert result["status"] == catalog_refresh.STALE and result["reason"] == "REFRESH_FAILED"
    monkeypatch.setattr(adapter, "_atomic_host_write", write)
    assert (home / maintenance.RECEIPT_NAME).read_bytes() == before_receipt
    assert surface(home)["status"] == "USER_CHANGED_PRESERVED"
    # SessionStart reports it without an export; the explicit command completes it.
    exports = len(fake.exports)
    assert catalog_refresh.refresh(home, automatic=True)["reason"] == "CATALOG_CHANGED_PRESERVED"
    assert len(fake.exports) == exports
    assert catalog_refresh.state(home)["reason"] == "CATALOG_CHANGED_PRESERVED"
    completed = catalog_refresh.refresh(home)
    assert completed["status"] == catalog_refresh.REFRESHED and completed["completed_interrupted_refresh"] is True
    assert fake.exports[-1] == ("online", catalog_refresh.EXPLICIT_EXPORT_TIMEOUT)
    assert surface(home)["status"] == "MATCH"


def test_unobservable_cli_never_exports_every_session(installed, monkeypatch):
    home, fake = installed
    fake.upgrade()
    monkeypatch.setattr(catalog, "_executable", lambda: None)
    before = snapshot(home)
    result = catalog_refresh.refresh(home, automatic=True)
    assert result["reason"] == "CLI_IDENTITY_UNOBSERVABLE" and fake.exports == []
    assert snapshot(home) == before


def _session(home, monkeypatch, tmp_path, **actor):
    project = tmp_path / "plain-project"
    project.mkdir(exist_ok=True)
    monkeypatch.chdir(project)
    identity = maintenance.digest((home / runtime_identity.MANIFEST_NAME).read_bytes())
    return catalog_recovery._session_start_recovery(home, identity, {"session_id": "native-session", **actor})


def test_owning_controller_session_start_refreshes(installed, monkeypatch, tmp_path):
    home, fake = installed
    fake.upgrade()
    result = _session(home, monkeypatch, tmp_path)
    assert result["model_catalog_refresh"]["status"] == catalog_refresh.REFRESHED, result
    assert surface(home)["status"] == "MATCH"


@pytest.mark.parametrize("actor", [
    {"agent_id": "child", "agent_type": "thaliris-implementer"},
    {"agent_type": "thaliris-reviewer"},
    {"readonly": True},
    {"fenced": True},
])
def test_child_readonly_or_fenced_session_start_never_refreshes(installed, monkeypatch, tmp_path, actor):
    home, fake = installed
    fake.upgrade()
    before = snapshot(home)
    result = _session(home, monkeypatch, tmp_path, **actor)
    assert result["model_catalog_refresh"]["status"] == "ACTOR_REFRESH_DENIED"
    assert fake.exports == [] and snapshot(home) == before


def _bash(command, **actor):
    return {"session_id": "root-session", "turn_id": "turn", "tool_name": "Bash",
            "tool_input": {"command": command}, **actor}


@pytest.mark.parametrize("actor", [
    {"agent_id": "child", "agent_type": "thaliris-implementer"},
    {"agent_id": "child", "agent_type": "thaliris-reviewer", "readonly": True},
    {"fenced": True},
])
def test_children_cannot_run_the_refresh_command(active, actor):
    result = lifecycle.handle_hook(active, "PreToolUse", _bash("thaliris codex-model-catalog-refresh", **actor))
    assert '"permissionDecision":"deny"' in result.replace(" ", "")


def test_role_session_refresh_is_a_control_state_mutation(active):
    denied = lifecycle._child_pre_tool_output(active, {
        "agent_type": "thaliris-implementer", "tool_name": "Bash",
        "tool_input": {"command": "thaliris codex-model-catalog-refresh"}})
    assert '"permissionDecision":"deny"' in denied
    assert lifecycle._context_operation({"tool_input": {"command": "thaliris codex-model-catalog-refresh"}}) in lifecycle._CHILD_CONTEXT_MUTATIONS


def test_controller_may_run_the_standalone_refresh_command(active):
    assert lifecycle.handle_hook(active, "PreToolUse", _bash("thaliris codex-model-catalog-refresh")) == ""
    compound = lifecycle.handle_hook(active, "PreToolUse", _bash("thaliris codex-model-catalog-refresh && echo done"))
    assert "deny" in compound


def test_explicit_command_requires_the_installed_runtime(installed, capsys):
    home, fake = installed
    fake.upgrade()
    before = snapshot(home)
    result = catalog_refresh.explicit(home)
    assert result["status"] == catalog_refresh.STALE and result["reason"] == "NOT_INSTALLED_RUNTIME"
    assert cli.main(["codex-model-catalog-refresh"]) == 3
    printed = json.loads(capsys.readouterr().out)
    assert printed["reason"] == "NOT_INSTALLED_RUNTIME" and catalog_refresh.COMMAND in printed["command"]
    assert fake.exports == [] and snapshot(home) == before


def test_bootstrap_reports_a_stale_catalog_without_blocking(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(codex_bootstrap, "_bootstrap", lambda *_args: {"ok": True, "status": "READY"})
    stale = {"ok": False, "changed": False, "status": catalog_refresh.STALE, "reason": "CLI_CHANGED",
             "command": "thaliris " + catalog_refresh.COMMAND, "ordinary_work_blocked": False}
    monkeypatch.setattr(catalog_refresh, "state", lambda _home: stale)
    result = codex_bootstrap.bootstrap(root)
    assert result["ok"] is True and result["status"] == "READY"
    assert result["model_catalog"] == stale
    monkeypatch.setattr(catalog_refresh, "state", lambda _home: {"ok": True, "status": catalog_refresh.CURRENT})
    assert "model_catalog" not in codex_bootstrap.bootstrap(root)
