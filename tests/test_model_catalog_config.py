from copy import deepcopy
import json
from datetime import datetime, timezone
import subprocess

import pytest

from thaliris_codex import model_catalog_config as catalog, codex_adapter as adapter, host_maintenance as maintenance, host_transition
from tests.test_host_maintenance_contract import intent

PRODUCTION_EXPORTER = catalog.export_upstream


def upstream(extra=False):
    model = {"slug": "test", "capabilities": {"arbitrary": [1, "new", False]},
             "model_messages": {"instructions_template": "first\n" + catalog.TARGET + "\nlast\n", "variables": {"keep": "exact"}}}
    return json.dumps({"metadata": {"etag": "original"}, "models": [model] + ([dict(deepcopy(model), slug="new-model")] if extra else [])}).encode()


def supply(monkeypatch, raw=None):
    monkeypatch.setattr(catalog, "export_upstream", lambda _home, **_kwargs: (raw or upstream(), {"kind": "online", "cli_version": "codex-cli 0.162.0-alpha.17.2"}))


def test_only_exact_sentence_changes_and_new_models_preserved():
    raw = upstream(True)
    patched, result = catalog.patch_catalog(raw)
    expected = json.loads(raw)
    for model in expected["models"]:
        model["model_messages"]["instructions_template"] = "first\nlast\n"
    assert json.loads(patched) == expected
    assert result["patched_templates"] == 2


@pytest.mark.parametrize("template,status", [("missing", "TARGET_ABSENT"), (catalog.TARGET + "\n" + catalog.TARGET, "TARGET_MULTIPLE_MATCHES"), ("prefix " + catalog.TARGET, "TARGET_CHANGED_OR_EMBEDDED")])
def test_compatibility_refuses_fuzzy_or_multiple(template, status):
    value = json.loads(upstream())
    value["models"][0]["model_messages"]["instructions_template"] = template
    assert catalog.patch_catalog(json.dumps(value).encode()) == (None, catalog.status(status))


@pytest.mark.parametrize("value", ["", "custom.json", False])
def test_user_leaf_and_catalog_not_read_or_claimed(tmp_path, monkeypatch, value):
    (tmp_path / "config.toml").write_text("model_catalog_json = " + json.dumps(value).replace("false", "false"))
    (tmp_path / catalog.NAME).write_bytes(b"user bytes")
    monkeypatch.setattr(catalog, "export_upstream", lambda _home: pytest.fail("user override must bypass export"))
    record, result, raw = catalog.plan_install(tmp_path, {})
    assert record is None and raw is None and result["status"] == "USER_CONFIG_PRESERVED"
    assert (tmp_path / catalog.NAME).read_bytes() == b"user bytes"


def test_install_update_nochange_uninstall(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"], result
    assert result["native_model_catalog_compatibility"]["status"] == "MANAGED"
    assert catalog.KEY in (home / "config.toml").read_text()
    paths = [home / catalog.NAME, home / maintenance.RECEIPT_NAME, home / "config.toml"]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"] and not result["changed"], result
    assert before == [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    supply(monkeypatch, upstream(True))
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"], result
    assert len(json.loads((home / catalog.NAME).read_bytes())["models"]) == 2
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall"))
    assert result["ok"], result
    assert not (home / catalog.NAME).exists()
    assert catalog.KEY not in (home / "config.toml").read_text()


def test_user_changed_catalog_preserved_across_upgrade_and_uninstall(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"]
    (home / catalog.NAME).write_bytes(b"user modified catalog")
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"] and result["native_model_catalog_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall"))
    assert result["ok"], result
    assert (home / catalog.NAME).read_bytes() == b"user modified catalog"
    assert catalog.NAME in result["preserved_files"]


def test_failed_refresh_does_not_claim_stale_healthy(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"]
    before = (home / catalog.NAME).read_bytes()
    monkeypatch.setattr(catalog, "export_upstream", lambda _home, **_kwargs: (_ for _ in ()).throw(ValueError("offline")))
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["native_model_catalog_compatibility"]["status"] == "UPSTREAM_REFRESH_FAILED_PRESERVED"
    assert (home / catalog.NAME).read_bytes() == before


def test_prepared_rollback_and_committed_recovery(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    path = intent(tmp_path, home, exe)
    original = adapter._install_host_hook_trust
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *_args: (_ for _ in ()).throw(ValueError("unavailable")))
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home)
    monkeypatch.setattr(adapter, "_install_host_hook_trust", original)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"], result
    assert result["native_model_catalog_compatibility"]["status"] == "MANAGED"
    assert not host_transition.pending(home)


def test_user_changed_field_preserves_catalog_on_uninstall(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"]
    path = home / "config.toml"
    path.write_text(path.read_text().replace(catalog.MARKER, "# user adopted catalog\n"))
    catalog_before = (home / catalog.NAME).read_bytes()
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall"))
    assert result["ok"], result
    assert (home / catalog.NAME).read_bytes() == catalog_before
    assert b"# user adopted catalog" in path.read_bytes()
    assert catalog.KEY.encode() in path.read_bytes()


def test_field_crash_does_not_reacquire_after_user_delete(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    path = intent(tmp_path, home, exe)
    original = catalog.apply
    def interrupted(*args, **kwargs):
        raise RuntimeError("interrupted field write")
    monkeypatch.setattr(catalog, "apply", interrupted)
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home)
    monkeypatch.setattr(catalog, "apply", original)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["native_model_catalog_compatibility"]["status"] == "APPLY_OUTCOME_UNKNOWN_PRESERVED"
    assert catalog.KEY not in (home / "config.toml").read_text()


@pytest.mark.parametrize("source,fresh", [("online", True), ("online", False), ("bundled", False)])
def test_export_preserves_provider_excludes_self_and_requires_new_cache(tmp_path, monkeypatch, source, fresh):
    home = tmp_path / "home"
    home.mkdir()
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"verified CLI")
    monkeypatch.setattr(catalog.shutil, "which", lambda _name: str(exe))
    original = b'model_provider = "custom"\n[model_providers.custom]\nbase_url = "https://provider.test/v1"\n'
    (home / "config.toml").write_bytes(original)
    (home / "auth.json").write_bytes(b"private authentication fixture")
    (home / "models_cache.json").write_bytes(b"stale never copied")
    (home / catalog.NAME).write_bytes(b"self catalog never copied")
    seen = []
    def run(args, **kwargs):
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, b"codex-cli 0.162.0-alpha.17.2\n", b"")
        isolated = catalog.Path(kwargs["env"]["CODEX_HOME"])
        seen.append(isolated)
        assert isolated != home and kwargs["cwd"] == isolated
        assert not (isolated / "models_cache.json").exists()
        assert not (isolated / catalog.NAME).exists()
        if source == "online":
            assert (isolated / "config.toml").read_bytes() == original
            assert (isolated / "auth.json").read_bytes() == b"private authentication fixture"
            if fresh:
                cache = {"fetched_at": datetime.now(timezone.utc).isoformat(), "identity": "provider-auth-opaque", "client_version": "0.162.0", "models": json.loads(upstream())["models"]}
                (isolated / "models_cache.json").write_text(json.dumps(cache))
        else:
            assert args[-1] == "--bundled"
            assert not (isolated / "config.toml").exists() and not (isolated / "auth.json").exists()
        return subprocess.CompletedProcess(args, 0, upstream(), b"")
    monkeypatch.setattr(catalog.subprocess, "run", run)
    if source == "online" and not fresh:
        with pytest.raises(ValueError, match="ONLINE_FRESHNESS_UNVERIFIED"):
            catalog.export_upstream(home, source=source)
    else:
        raw, evidence = catalog.export_upstream(home, source=source)
        assert raw == upstream()
        assert evidence["kind"] == source
        assert evidence["online_freshness"] == ("VERIFIED" if fresh else "UNKNOWN")
    assert seen and not seen[0].exists()
    assert (home / "config.toml").read_bytes() == original
    assert (home / "auth.json").read_bytes() == b"private authentication fixture"


def test_source_selection_and_version_boundary(tmp_path, monkeypatch):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"CLI")
    monkeypatch.setattr(catalog.shutil, "which", lambda _: str(exe))
    monkeypatch.setattr(catalog.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"codex-cli 0.162.0-alpha.17.3", b""))
    with pytest.raises(ValueError, match="VERSION_SUPPORT_UNKNOWN"):
        catalog.export_upstream(tmp_path)
    monkeypatch.setattr(catalog, "export_upstream", lambda _home, **kwargs: (upstream(), {"kind": "bundled", "cli_version": "codex-cli 0.162.0-alpha.17.2"}))
    record, result, raw = catalog.plan_install(tmp_path, {}, source="bundled")
    assert record and result["status"] == "PLANNED" and raw
    record["source"]["kind"] = "online"
    old = deepcopy(record)
    new, result, raw = catalog.plan_install(tmp_path, {catalog.RECORD_KEY: record}, source="bundled")
    assert new == old and raw is None and result["status"] == "SOURCE_DOWNGRADE_PRESERVED"


def test_user_change_during_export_never_overwrites(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    def changed(home, **kwargs):
        home.mkdir(exist_ok=True)
        (home / catalog.NAME).write_bytes(b"user created during export")
        return upstream(), {"kind": "online", "cli_version": "codex-cli 0.162.0-alpha.17.2"}
    monkeypatch.setattr(catalog, "export_upstream", changed)
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert not result["ok"]
    assert (home / catalog.NAME).read_bytes() == b"user created during export"
    assert not (home / maintenance.RECEIPT_NAME).exists()


@pytest.mark.parametrize("defect", ["bytes", "receipt", "source", "phase"])
def test_committed_journal_tamper_rejected(tmp_path, monkeypatch, pinned_test_thaliris, defect):
    import base64
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    path = intent(tmp_path, home, exe)
    trust = adapter._install_host_hook_trust
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *_: (_ for _ in ()).throw(ValueError("trust unavailable")))
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home)
    journal = home / host_transition.NAME
    value = json.loads(journal.read_bytes())
    if defect == "bytes":
        value["after"][catalog.NAME] = base64.b64encode(b"not the planned catalog").decode()
    elif defect == "receipt":
        value["finish"]["model_catalog_record"]["catalog_sha256"] = "0" * 64
    elif defect == "source":
        receipt = json.loads(base64.b64decode(value["after"][maintenance.RECEIPT_NAME]))
        receipt[catalog.RECORD_KEY]["source"]["kind"] = "bundled"
        value["after"][maintenance.RECEIPT_NAME] = base64.b64encode(json.dumps(receipt).encode()).decode()
        value["finish"]["model_catalog_record"]["source"]["kind"] = "bundled"
    else:
        value["finish"]["model_catalog_phase"] = "invalid"
    journal.write_text(json.dumps(value))
    monkeypatch.setattr(adapter, "_install_host_hook_trust", trust)
    before = (home / catalog.NAME).read_bytes()
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home)
    assert (home / catalog.NAME).read_bytes() == before


def test_prepared_catalog_generation_rolls_back_before_fresh_plan(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    path = intent(tmp_path, home, exe)
    real_apply = host_transition._apply
    def interrupted(home, values, **kwargs):
        real_apply(home, values, **kwargs)
        if not kwargs.get("rollback"):
            raise RuntimeError("interrupt before commit")
    monkeypatch.setattr(host_transition, "_apply", interrupted)
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home)
    assert (home / catalog.NAME).exists()
    monkeypatch.setattr(host_transition, "_apply", real_apply)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"], result
    assert result["native_model_catalog_compatibility"]["status"] == "MANAGED"
    assert not host_transition.pending(home)


def test_observed_export_timeout_preserves_prior_catalog(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"]
    before = (home / catalog.NAME).read_bytes()
    # Restore production exporter and supply a verified fake CLI identity.
    monkeypatch.setattr(catalog, "export_upstream", PRODUCTION_EXPORTER)
    # Full Host tests need their pinned runtime fixture, so verify the exporter
    # timeout directly and plan preserving behavior with its reported failure.
    fake = tmp_path / "codex.exe"
    fake.write_bytes(b"CLI fixture")
    monkeypatch.setattr(catalog.shutil, "which", lambda _: str(fake))
    def timeout(args, **kwargs):
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, b"codex-cli 0.162.0-alpha.17.2", b"")
        raise subprocess.TimeoutExpired(args, 90)
    monkeypatch.setattr(catalog.subprocess, "run", timeout)
    receipt = json.loads((home / maintenance.RECEIPT_NAME).read_bytes())
    record, result, changed = catalog.plan_install(home, receipt)
    assert record == receipt[catalog.RECORD_KEY] and changed is None
    assert result["status"] == "UPSTREAM_REFRESH_FAILED_PRESERVED"
    assert (home / catalog.NAME).read_bytes() == before


def test_first_absent_no_takeover_existing_absent_syncs_verbatim_and_recovers(tmp_path, monkeypatch, pinned_test_thaliris):
    raw = upstream(True).replace(catalog.TARGET.encode(), b"upstream replacement rule")
    supply(monkeypatch, raw)
    first_home = tmp_path / "first"
    first_home.mkdir()
    (first_home / "config.toml").write_bytes(b"# untouched\n")
    record, result, changed = catalog.plan_install(first_home, {})
    assert record is None and changed is None and result["status"] == "TARGET_ABSENT"
    assert (first_home / "config.toml").read_bytes() == b"# untouched\n"
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    assert adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))["ok"]
    supply(monkeypatch, raw)
    path = intent(tmp_path, home, exe)
    trust = adapter._install_host_hook_trust
    monkeypatch.setattr(adapter, "_install_host_hook_trust", lambda *_: (_ for _ in ()).throw(ValueError("trust unavailable")))
    result = adapter.codex_install(maintenance_contract=path)
    assert not result["ok"] and host_transition.pending(home)
    assert (home / catalog.NAME).read_bytes() == raw
    monkeypatch.setattr(adapter, "_install_host_hook_trust", trust)
    result = adapter.codex_install(maintenance_contract=path)
    assert result["ok"] and result["native_model_catalog_compatibility"]["status"] == "TARGET_ABSENT_MANAGED", result
    assert (home / catalog.NAME).read_bytes() == raw
    assert len(json.loads(raw)["models"]) == 2
    receipt = json.loads((home / maintenance.RECEIPT_NAME).read_bytes())
    assert receipt[catalog.RECORD_KEY]["catalog_sha256"] == receipt[catalog.RECORD_KEY]["source"]["upstream_sha256"]
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall"))
    assert result["ok"] and not (home / catalog.NAME).exists()
