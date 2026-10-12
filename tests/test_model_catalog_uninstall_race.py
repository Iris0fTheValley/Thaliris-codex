from thaliris_codex import codex_adapter as adapter, codex_app_server, model_catalog_config as catalog
from tests import test_model_catalog_config as catalog_tests
from tests.test_host_maintenance_contract import intent


def test_uninstall_preserves_catalog_when_user_adopts_field_during_preflight(
    tmp_path, monkeypatch, pinned_test_thaliris
):
    executable, _ = pinned_test_thaliris
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    catalog_tests.supply(monkeypatch)
    installed = adapter.codex_install(maintenance_contract=intent(tmp_path, home, executable))
    assert installed["ok"], installed
    catalog_path = home / catalog.NAME
    original_catalog = catalog_path.read_bytes()
    config_path = home / "config.toml"
    original_lookup = codex_app_server.owned_hook_keys_from_host

    def adopt_catalog(hook_home, commands):
        config_path.write_bytes(
            config_path.read_bytes().replace(catalog.MARKER.encode(), b"# user adopted catalog\n")
        )
        return original_lookup(hook_home, commands)

    monkeypatch.setattr(codex_app_server, "owned_hook_keys_from_host", adopt_catalog)
    result = adapter.codex_uninstall(
        maintenance_contract=intent(tmp_path, home, executable, "codex-uninstall")
    )

    assert result["ok"], result
    assert result["native_model_catalog_compatibility"]["status"] == "USER_CHANGED_PRESERVED"
    assert b"# user adopted catalog\n" in config_path.read_bytes()
    assert catalog.KEY.encode() in config_path.read_bytes()
    assert catalog_path.read_bytes() == original_catalog
    assert catalog.NAME in result["preserved_files"]
