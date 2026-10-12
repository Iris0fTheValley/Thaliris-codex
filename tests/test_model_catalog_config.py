from copy import deepcopy
import json
from datetime import datetime, timezone
import subprocess

import pytest

from thaliris_codex import model_catalog_config as catalog, codex_adapter as adapter, host_maintenance as maintenance, host_transition
from tests.test_host_maintenance_contract import intent
from tests.model_catalog_fixtures import observed_catalog, bundled_compatible_catalog, supply

PRODUCTION_EXPORTER = catalog.export_upstream


def upstream(extra=False):
    model = {"slug": "test", "capabilities": {"arbitrary": [1, "new", False]},
             "model_messages": {"instructions_template": "first\n" + catalog.TARGET + "\nlast\n", "variables": {"keep": "exact"}}}
    return json.dumps({"metadata": {"etag": "original"}, "models": [model] + ([dict(deepcopy(model), slug="new-model")] if extra else [])}).encode()


def test_only_exact_sentence_changes_and_new_models_preserved():
    raw = upstream(True)
    patched, result = catalog.patch_catalog(raw)
    expected = json.loads(raw)
    for model in expected["models"]:
        model["model_messages"]["instructions_template"] = "first\nlast\n"
    assert json.loads(patched) == expected
    assert result["status"] == "COMPATIBLE"
    assert result["patched_templates"] == 2


@pytest.mark.parametrize("template,status", [("missing", "TARGET_ABSENT_UNEXPECTED"), (catalog.TARGET + "\n" + catalog.TARGET, "TARGET_MULTIPLE_MATCHES"), ("prefix " + catalog.TARGET, "TARGET_CHANGED_OR_EMBEDDED")])
def test_compatibility_refuses_fuzzy_or_multiple(template, status):
    value = json.loads(upstream())
    value["models"][0]["model_messages"]["instructions_template"] = template
    patched, result = catalog.patch_catalog(json.dumps(value).encode())
    assert patched is None and result["status"] == status


def test_split_target_line_is_not_accepted_as_exact():
    split = catalog.TARGET.replace("longer than 60", "longer than\n60")
    value = json.loads(upstream())
    value["models"][0]["model_messages"]["instructions_template"] = "before\n" + split + "\nafter\n"
    patched, result = catalog.patch_catalog(json.dumps(value).encode())
    assert patched is None and result["status"] == "TARGET_ABSENT_UNEXPECTED"


def test_observed_bundled_11_models_allow_only_known_absent_slug():
    raw = bundled_compatible_catalog()
    patched, result = catalog.patch_catalog(raw, cli_version="codex-cli 0.162.0-alpha.17.2", source="bundled")
    assert result["status"] == "COMPATIBLE"
    assert result["patched_templates"] == 10
    assert result["template_statuses"] == {"EXACT_MATCH": 10, "KNOWN_ABSENT": 1}
    original = json.loads(raw)
    expected = deepcopy(original)
    for model in expected["models"]:
        if model["slug"] != "gpt-5.5":
            lines = model["model_messages"]["instructions_template"].splitlines(keepends=True)
            model["model_messages"]["instructions_template"] = "".join(
                line for line in lines if line.rstrip("\r\n") != catalog.TARGET
            )
    assert json.loads(patched) == expected


@pytest.mark.parametrize("cli_version", [
    "codex-cli 0.162.0",
    "codex-cli 0.162.1",
    "codex-cli 0.162.2",
    "codex-cli 0.163.0",
])
def test_catalog_capability_uses_content_not_release_allowlist(cli_version):
    patched, result = catalog.patch_catalog(
        observed_catalog("online"), cli_version=cli_version, source="online"
    )
    assert patched is not None and result["status"] == "COMPATIBLE"
    assert result["patched_templates"] == 9


@pytest.mark.parametrize("cli_version,expected", [
    ("codex-cli 0.162.0-alpha.17.2", "0.162.0"),
    ("codex-cli 0.162.0", "0.162.0"),
    ("codex-cli 0.162.1", "0.162.1"),
    ("codex-cli 0.163.4-beta.2", "0.163.4"),
    ("codex-cli 0.163.4+build.2", "0.163.4"),
])
def test_model_cache_version_uses_cli_whole_release(cli_version, expected):
    assert catalog.cache_client_version(cli_version) == expected


@pytest.mark.parametrize("cli_version", [
    "codex-cli unknown", "0.162.1", "codex-cli 0.162", "codex-cli 0.162.0-",
    "codex-cli 0.162.0-01", "codex-cli 00.162.0",
])
def test_model_cache_version_requires_parseable_cli_identity(cli_version):
    assert catalog.cache_client_version(cli_version) is None


def test_observed_online_10_models_have_source_specific_roster():
    patched, result = catalog.patch_catalog(
        observed_catalog("online"), cli_version="codex-cli 0.162.0-alpha.17.2", source="online"
    )
    assert patched is not None and result["status"] == "COMPATIBLE"
    assert result["patched_templates"] == 9
    assert result["template_statuses"] == {"EXACT_MATCH": 9, "KNOWN_ABSENT": 1}


def test_version_source_and_schema_variations_fail_closed():
    raw = observed_catalog("online")
    patched, result = catalog.patch_catalog(raw, cli_version="codex-cli 0.162.0-alpha.17.2")
    assert patched is None and result["status"] == "CATALOG_PROFILE_UNKNOWN"

    value = json.loads(raw)
    del value["models"][0]["model_messages"]["instructions_template"]
    patched, result = catalog.patch_catalog(
        json.dumps(value).encode(), cli_version="codex-cli 0.162.0-alpha.17.2", source="online"
    )
    assert patched is None and result["status"] == "MODEL_TEMPLATE_UNSUPPORTED"

    patched, result = catalog.patch_catalog(b"{")
    assert patched is None and result["status"] == "CATALOG_JSON_UNSUPPORTED"
    patched, result = catalog.patch_catalog(b'{"models":[]}')
    assert patched is None and result["status"] == "CATALOG_SCHEMA_UNSUPPORTED"


def test_plan_preserves_state_on_unsupported_catalog_schema(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(catalog, "export_upstream", lambda *_args, **_kwargs: (
        b'{"models":[]}', {"kind": "online", "cli_version": "codex-cli 0.162.0-alpha.17.2"}
    ))
    record, result, changed = catalog.plan_install(home, {})
    assert record is None and changed is None
    assert result["status"] == "TEMPLATE_INCOMPATIBILITY_PRESERVED"
    assert result["template_compatibility"]["status"] == "CATALOG_SCHEMA_UNSUPPORTED"
    assert not (home / catalog.NAME).exists()


@pytest.mark.parametrize("slug,template,expected_status", [
    ("formerly-matched", "edited upstream wording", "TARGET_ABSENT_UNEXPECTED"),
    ("gpt-5.5", "before\n" + catalog.TARGET + "\nafter\n", "KNOWN_ABSENT_MODEL_CHANGED"),
    ("new-model", "new model without the pinned target", "TARGET_ABSENT_UNEXPECTED"),
])
def test_partial_or_new_model_absence_is_incompatible(slug, template, expected_status):
    value = json.loads(bundled_compatible_catalog())
    model = {"slug": slug, "model_messages": {"instructions_template": template}}
    if slug == "formerly-matched":
        value["models"][0] = model
    elif slug == "gpt-5.5":
        value["models"] = [model]
    else:
        value["models"].append(model)
    changed, result = catalog.patch_catalog(json.dumps(value).encode(), cli_version="codex-cli 0.162.0-alpha.17.2", source="bundled")
    assert changed is None and result["status"] == expected_status


def test_moved_known_target_requires_review():
    value = json.loads(bundled_compatible_catalog())
    model = next(m for m in value["models"] if m["slug"] == "gpt-6-astra")
    lines = model["model_messages"]["instructions_template"].splitlines()
    target_index = lines.index(catalog.TARGET)
    lines[target_index - 1], lines[target_index] = lines[target_index], lines[target_index - 1]
    model["model_messages"]["instructions_template"] = "\n".join(lines) + "\n"
    patched, result = catalog.patch_catalog(
        json.dumps(value).encode(), cli_version="codex-cli 0.162.0-alpha.17.2", source="bundled"
    )
    assert patched is None and result["status"] == "TARGET_LOCATION_CHANGED"


def test_removed_known_model_does_not_invalidate_remaining_catalog():
    original = json.loads(bundled_compatible_catalog())
    removed_slug = "gpt-6-astra"
    input_value = deepcopy(original)
    input_value["models"] = [model for model in input_value["models"] if model["slug"] != removed_slug]
    expected = deepcopy(input_value)
    for model in expected["models"]:
        if model["slug"] == "gpt-5.5":
            continue
        lines = model["model_messages"]["instructions_template"].splitlines(keepends=True)
        model["model_messages"]["instructions_template"] = "".join(
            line for line in lines if line.rstrip("\r\n") != catalog.TARGET
        )

    patched, result = catalog.patch_catalog(
        json.dumps(input_value).encode(),
        cli_version="codex-cli 0.162.0-alpha.17.2", source="bundled"
    )

    assert patched is not None and result["status"] == "COMPATIBLE"
    assert result["patched_templates"] == 9
    assert json.loads(patched) == expected


def test_present_known_model_still_requires_its_exact_target():
    value = json.loads(bundled_compatible_catalog())
    model = next(m for m in value["models"] if m["slug"] == "gpt-6-astra")
    model["model_messages"]["instructions_template"] = "known model without the target\n"
    patched, result = catalog.patch_catalog(
        json.dumps(value).encode(), cli_version="codex-cli 0.162.0-alpha.17.2", source="bundled"
    )
    assert patched is None and result["status"] == "TARGET_ABSENT_UNEXPECTED"


def test_new_exact_target_model_is_removed_but_new_absent_model_is_incompatible():
    raw = observed_catalog("online", extra=True)
    patched, result = catalog.patch_catalog(
        raw, cli_version="codex-cli 0.162.0-alpha.17.2", source="online"
    )
    assert result["status"] == "COMPATIBLE"
    new = next(m for m in json.loads(patched)["models"] if m["slug"] == "new-model")
    assert catalog.TARGET not in new["model_messages"]["instructions_template"]


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
    supply(monkeypatch, observed_catalog("online", extra=True))
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert result["ok"], result
    assert len(json.loads((home / catalog.NAME).read_bytes())["models"]) == 11
    result = adapter.codex_uninstall(maintenance_contract=intent(tmp_path, home, exe, "codex-uninstall"))
    assert result["ok"], result
    assert (home / catalog.NAME).exists()
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
    assert (home / catalog.NAME).read_bytes() == b"user modified catalog"
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
    assert not result["ok"], result
    assert result["native_model_catalog_compatibility"]["status"] == "UPSTREAM_REFRESH_FAILED_PRESERVED"
    assert (home / catalog.NAME).read_bytes() == before


def test_old_record_install_incompatibility_fails_and_preserves_owned_state(tmp_path, monkeypatch, pinned_test_thaliris):
    exe, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    supply(monkeypatch)
    first = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert first["ok"], first
    paths = [home / catalog.NAME, home / "config.toml", home / maintenance.RECEIPT_NAME]
    before = [path.read_bytes() for path in paths]

    changed = json.loads(observed_catalog())
    changed["models"][0]["model_messages"]["instructions_template"] = "upstream wording changed\n"
    supply(monkeypatch, json.dumps(changed).encode())
    result = adapter.codex_install(maintenance_contract=intent(tmp_path, home, exe))
    assert not result["ok"], result
    compatibility = result["native_model_catalog_compatibility"]
    assert compatibility["status"] == "TEMPLATE_INCOMPATIBILITY_PRESERVED"
    assert compatibility["template_compatibility"]["status"] == "TARGET_ABSENT_UNEXPECTED"
    assert [path.read_bytes() for path in paths] == before
    assert not host_transition.pending(home)


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
@pytest.mark.parametrize("cli_version,cache_version", [
    ("codex-cli 0.162.0-alpha.17.2", "0.162.0"),
    ("codex-cli 0.162.0", "0.162.0"),
    ("codex-cli 0.162.1", "0.162.1"),
    ("codex-cli 0.163.0", "0.163.0"),
])
def test_export_preserves_provider_excludes_self_and_checks_whole_version_cache(
    tmp_path, monkeypatch, source, fresh, cli_version, cache_version,
):
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
            return subprocess.CompletedProcess(args, 0, (cli_version + "\n").encode(), b"")
        isolated = catalog.Path(kwargs["env"]["CODEX_HOME"])
        seen.append(isolated)
        assert isolated != home and kwargs["cwd"] == isolated
        assert not (isolated / "models_cache.json").exists()
        assert not (isolated / catalog.NAME).exists()
        if source == "online":
            assert (isolated / "config.toml").read_bytes() == original
            assert (isolated / "auth.json").read_bytes() == b"private authentication fixture"
            if fresh:
                cache = {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "identity": "provider-auth-opaque",
                    "client_version": cache_version,
                    "models": json.loads(upstream())["models"],
                }
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
        assert evidence["cli_version"] == cli_version
        assert evidence["online_freshness"] == ("VERIFIED" if fresh else "UNKNOWN")
    assert seen and not seen[0].exists()
    assert (home / "config.toml").read_bytes() == original
    assert (home / "auth.json").read_bytes() == b"private authentication fixture"


def test_export_rejects_cache_from_a_different_whole_cli_version(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"verified CLI")
    monkeypatch.setattr(catalog.shutil, "which", lambda _name: str(exe))

    def run(args, **kwargs):
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, b"codex-cli 0.162.1\n", b"")
        isolated = catalog.Path(kwargs["env"]["CODEX_HOME"])
        cache = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "identity": "provider-auth-opaque",
            "client_version": "0.162.0",
            "models": json.loads(upstream())["models"],
        }
        (isolated / "models_cache.json").write_text(json.dumps(cache))
        return subprocess.CompletedProcess(args, 0, upstream(), b"")

    monkeypatch.setattr(catalog.subprocess, "run", run)
    with pytest.raises(ValueError, match="ONLINE_FRESHNESS_UNVERIFIED"):
        catalog.export_upstream(home, source="online")


def test_source_selection_and_content_based_version_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "export_upstream", lambda _home, **kwargs: (
        bundled_compatible_catalog(), {"kind": "bundled", "cli_version": "codex-cli 0.162.2"}
    ))
    record, result, raw = catalog.plan_install(tmp_path, {}, source="bundled")
    assert record and result["status"] == "PLANNED" and raw
    assert record["source"]["cli_version"] == "codex-cli 0.162.2"
    record["source"]["kind"] = "online"
    old = deepcopy(record)
    new, result, raw = catalog.plan_install(tmp_path, {catalog.RECORD_KEY: record}, source="bundled")
    assert new == old and raw is None and result["status"] == "SOURCE_DOWNGRADE_PRESERVED"


def test_plan_accepts_unknown_cli_version_only_when_catalog_content_matches(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(catalog, "export_upstream", lambda _home, **_kwargs: (
        upstream(), {"kind": "online", "cli_version": "codex-cli 0.162.0-alpha.17.3"}
    ))
    record, result, changed = catalog.plan_install(home, {})
    assert record and changed is not None
    assert result["status"] == "PLANNED"
    assert record["source"]["cli_version"] == "codex-cli 0.162.0-alpha.17.3"

    monkeypatch.setattr(catalog, "export_upstream", lambda _home, **_kwargs: (
        b'{"models":[{"slug":"test","model_messages":{"instructions_template":"changed wording"}}]}',
        {"kind": "online", "cli_version": "codex-cli 0.162.0-alpha.17.3"},
    ))
    rejected, result, changed = catalog.plan_install(home, {})
    assert rejected is None and changed is None
    assert result["status"] == "TEMPLATE_INCOMPATIBILITY_PRESERVED"
    assert result["template_compatibility"]["status"] == "TARGET_ABSENT_UNEXPECTED"


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


def test_first_incompatible_catalog_is_not_claimed_or_written(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    config = home / "config.toml"
    config.write_bytes(b"# untouched\n")
    raw = observed_catalog().replace(catalog.TARGET.encode(), b"upstream replacement rule")
    supply(monkeypatch, raw)
    record, result, changed = catalog.plan_install(home, {})
    assert record is None and changed is None
    assert result["status"] == "TEMPLATE_INCOMPATIBILITY_PRESERVED"
    assert result["template_compatibility"]["status"] == "TARGET_ABSENT_UNEXPECTED"
    assert config.read_bytes() == b"# untouched\n"
    assert not (home / catalog.NAME).exists()


def test_old_record_partial_absence_is_preserved_by_plan(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    supply(monkeypatch)
    old_record, planned, catalog_bytes = catalog.plan_install(home, {})
    assert old_record and planned["status"] == "PLANNED" and catalog_bytes
    (home / catalog.NAME).write_bytes(catalog_bytes)
    (home / "config.toml").write_bytes(old_record["fragment"].encode())
    receipt = {catalog.RECORD_KEY: old_record}
    catalog_before = (home / catalog.NAME).read_bytes()
    config_before = (home / "config.toml").read_bytes()

    changed = json.loads(observed_catalog())
    changed["models"][0]["model_messages"]["instructions_template"] = "new upstream wording\n"
    raw = json.dumps(changed).encode()
    supply(monkeypatch, raw)
    planned_record, planned, changed_bytes = catalog.plan_install(home, receipt)
    assert planned_record == old_record and changed_bytes is None
    assert planned["status"] == "TEMPLATE_INCOMPATIBILITY_PRESERVED"
    assert planned["template_compatibility"]["status"] == "TARGET_ABSENT_UNEXPECTED"
    assert (home / catalog.NAME).read_bytes() == catalog_before
    assert (home / "config.toml").read_bytes() == config_before


def test_archive_proven_retained_catalog_can_be_reacquired_only_with_missing_field(tmp_path, monkeypatch):
    from thaliris_codex import catalog_recovery

    home = tmp_path / "home"
    home.mkdir()
    supply(monkeypatch)
    retained, planned, original_bytes = catalog.plan_install(home, {})
    assert retained and planned["status"] == "PLANNED" and original_bytes
    (home / catalog.NAME).write_bytes(original_bytes)
    before_config = b"# config has no catalog field\n"
    (home / "config.toml").write_bytes(before_config)
    monkeypatch.setattr(
        catalog_recovery, "retained_record",
        lambda _home, catalog_bytes=None: retained if catalog_bytes in (None, original_bytes) else None,
    )

    record, model_status, new_bytes = catalog.plan_install(home, {})
    assert record is not None and new_bytes == original_bytes
    assert model_status["status"] == "PLANNED"
    assert model_status["retained_backing_reclaimed"] is True
    finish = {"model_catalog_record": record, "model_catalog_status": model_status}
    before = {catalog.NAME: original_bytes, "config.toml": before_config}
    after = {catalog.NAME: new_bytes, "config.toml": before_config}
    catalog.validate_transition(finish, {}, record, before, after, home, install=True)


def test_retained_catalog_reclaim_refuses_changed_or_field_present_state(tmp_path, monkeypatch):
    from thaliris_codex import catalog_recovery

    home = tmp_path / "home"
    home.mkdir()
    supply(monkeypatch)
    retained, _, original_bytes = catalog.plan_install(home, {})
    (home / catalog.NAME).write_bytes(original_bytes + b"user edit")
    (home / "config.toml").write_bytes(b"# config has no catalog field\n")
    monkeypatch.setattr(catalog_recovery, "retained_record", lambda *_args, **_kwargs: retained)
    record, result, changed = catalog.plan_install(home, {})
    assert record is None and changed is None and result["status"] == "USER_CATALOG_PRESERVED"

    (home / catalog.NAME).write_bytes(original_bytes)
    (home / "config.toml").write_text("model_catalog_json = \"custom.json\"\n")
    record, result, changed = catalog.plan_install(home, {})
    assert record is None and changed is None and result["status"] == "USER_CONFIG_PRESERVED"


def test_restored_receipt_reacquires_missing_field_with_exact_helper_proof(tmp_path, monkeypatch):
    from thaliris_codex import catalog_recovery

    home = tmp_path / "home"
    home.mkdir()
    supply(monkeypatch)
    old_record, _, old_bytes = catalog.plan_install(home, {})
    (home / catalog.NAME).write_bytes(old_bytes)
    before_config = b"# restored catalog field is absent\n"
    (home / "config.toml").write_bytes(before_config)
    policy = {
        "format": catalog_recovery.POLICY_FORMAT,
        "project_root": str((tmp_path / "project").absolute()),
        "restored": True,
    }
    ownership = {catalog.RECORD_KEY: old_record, catalog_recovery.POLICY_KEY: policy}
    monkeypatch.setattr(
        catalog_recovery, "retained_record",
        lambda _home, catalog_bytes=None: old_record if catalog_bytes in (None, old_bytes) else None,
    )
    record, model_status, new_bytes = catalog.plan_install(home, ownership)
    assert record is not None and new_bytes == old_bytes
    assert model_status["status"] == "UPDATE_PLANNED"
    assert model_status["restored_field_reacquired"] is True
    finish = {"model_catalog_record": record, "model_catalog_status": model_status}
    before = {catalog.NAME: old_bytes, "config.toml": before_config}
    after = {catalog.NAME: new_bytes, "config.toml": before_config}
    catalog.validate_transition(finish, ownership, record, before, after, home, install=True)

    calls = []
    monkeypatch.setattr(catalog, "apply", lambda _home, _record, **kwargs: (calls.append(kwargs) or catalog.status("MANAGED")))
    monkeypatch.setattr(host_transition, "_write", lambda *_args, **_kwargs: None)
    result = catalog.finish_install(home, {"finish": finish})
    assert result["status"] == "MANAGED"
    assert calls == [{"allow_insert": True}]


def test_old_absent_target_journal_cannot_complete_as_managed(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    # Build a structurally valid historical record whose catalog bytes were the
    # old upstream pass-through after the target disappeared.
    source_bytes = upstream().replace(catalog.TARGET.encode(), b"upstream replacement rule")
    owned_record = {
        "path": str((home / "config.toml").absolute()),
        "catalog_path": str((home / catalog.NAME).absolute()),
        "prior": {"present": False},
        "fragment": catalog.fragment(home, "\n"),
        "catalog_sha256": catalog.digest(source_bytes),
        "source": {"kind": "online", "cli_version": "codex-cli 0.162.0-alpha.17.2",
                   "upstream_sha256": catalog.digest(source_bytes)},
    }
    finish = {
        "model_catalog_record": owned_record,
        "model_catalog_status": catalog.status(
            "MANAGED", template_compatibility=catalog.status("TARGET_ABSENT")
        ),
    }
    with pytest.raises(ValueError, match="incompatible model catalog template cannot be managed"):
        catalog.validate_transition(
            finish, {catalog.RECORD_KEY: owned_record}, owned_record,
            {catalog.NAME: source_bytes}, {catalog.NAME: source_bytes}, home, install=True,
        )
