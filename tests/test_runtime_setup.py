"""Real Python/pip source-fixture evidence for the dedicated runtime boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from thaliris_codex import runtime_setup, runtime_identity, host_maintenance, host_preflight, codex_adapter


def source_wheel(tmp_path, name, package, *, entry=False, legacy_cli=False):
    """Pack current test source as a disposable fixture, not a release artifact."""
    path = tmp_path / f"{name}-0.4.3-py3-none-any.whl"
    info = f"{name}-0.4.3.dist-info"
    with zipfile.ZipFile(path, "w") as wheel:
        for source in package.rglob("*.py"):
            relative = name + "/" + source.relative_to(package).as_posix()
            if legacy_cli and source.name == "cli.py":
                wheel.writestr(relative, "import json,sys\ndef main():\n"
                    "    print(json.dumps({'ok':sys.argv[1:] == ['version'],'version':'0.4.3'}))\n"
                    "    return 0 if sys.argv[1:] == ['version'] else 3\n")
            else:
                wheel.write(source, relative)
        wheel.writestr(info + "/METADATA", f"Metadata-Version: 2.1\nName: {name.replace('_', '-')}\nVersion: 0.4.3\n")
        wheel.writestr(info + "/WHEEL", "Wheel-Version: 1.0\nGenerator: source-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr(info + "/RECORD", "")
        if entry:
            wheel.writestr(info + "/entry_points.txt", "[console_scripts]\nthaliris = thaliris_codex.cli:main\n")
    return str(path) + "#sha256=" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_python311_pip_bootstrap_creates_runtime_without_pth_repair(tmp_path, monkeypatch):
    import thaliris
    import thaliris_codex
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    # The caller may contain executable .pth/setuptools; no bytes from that
    # startup machinery are copied into the target's importable environment.
    target = tmp_path / "dedicated runtime"
    result = runtime_setup.create(target, core, adapter)
    assert result["ok"]
    assert not list(target.rglob("*.pth"))
    assert not list(target.rglob("setuptools*"))
    assert not list(target.rglob("pip-*.dist-info"))
    assert not list(target.rglob("*.pyc"))
    executable = Path(result["executable"])
    assert result["runtime_dir"] == str(runtime_identity.physical_directory(target))
    assert result["console_smoke"]["interpreter"] == str(executable.parent / ("python.exe" if os.name == "nt" else "python"))
    assert result["console_smoke"]["bytecode_disabled"] is True
    assert (target / runtime_identity.LOCATION_NAME).read_bytes() == runtime_identity.location_bytes(target)
    before = runtime_identity.manifest_bytes(executable)
    selection = {"executable": str(executable), "runtime_sha256": result["runtime_sha256"],
                 "source_pin": "sha256:" + adapter.rsplit("=", 1)[1]}
    assert host_maintenance.selected_runtime(selection)[0] == executable
    home = tmp_path / "home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    # A plan is generated only after the public final-path launcher smoke. No
    # installation or approval is performed by planning in this empty home.
    planned = subprocess.run([str(executable), "codex-maintenance-plan", "codex-install",
        "--executable", str(executable), "--source-pin", selection["source_pin"],
        "--human-instruction", "Prepare this disposable fixture for review."],
        env=runtime_identity.child_environment(), capture_output=True, timeout=15)
    assert planned.returncode == 0, planned.stderr or planned.stdout
    assert json.loads(planned.stdout)["maintenance_contract"]["candidate"] == selection
    assert not home.exists()
    assert runtime_identity.manifest_bytes(executable) == before
    # Exercise the real interpreter origin and native console-launcher ABI
    # probe; actual Codex trust/catalog loading stays outside this fixture.
    probe = codex_adapter._host_install_executable(home, executable, json.loads(before)["executable_sha256"])
    assert probe[2] is None, probe
    assert runtime_identity.manifest_bytes(executable) == before
    from thaliris_codex import codex_bootstrap, lifecycle
    expected = len(lifecycle.HOOK_EVENTS)
    monkeypatch.setattr(codex_adapter, "_install_host_hook_trust", lambda *a: {
        "status": "TRUSTED", "trusted_count": expected, "enabled_count": expected, "changed": False})
    contract = tmp_path / "approved-fixture-install.json"
    contract.write_text(json.dumps({"format": host_maintenance.FORMAT, "operation": "codex-install",
        "codex_home": str(home), "human_instruction": "Install source fixture into disposable test home.",
        "executor": selection, "candidate": selection, "installed_runtime_sha256": "ABSENT",
        "execution_constraint": None}), encoding="utf-8")
    installed = codex_adapter.codex_install(maintenance_contract=contract)
    assert installed["ok"], installed
    project = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "docs").mkdir()
    (project / "docs/thaliris-role-packs.md").write_bytes(b"user-owned role description")
    # Bootstrap executes the installed console launcher and installed Core,
    # rather than a development _invoke or executable substitute.
    ready = codex_bootstrap.bootstrap(project)
    assert ready["status"] == "DEFINITION_READY_ACTOR_UNKNOWN", ready
    assert (project / "docs/thaliris-role-packs.md").read_bytes() == b"user-owned role description"
    assert runtime_identity.manifest_bytes(executable) == before
    with pytest.raises(ValueError, match="already exists"):
        runtime_setup.create(target, core, adapter)
    assert runtime_identity.manifest_bytes(executable) == before


@pytest.mark.skipif(os.name != "nt", reason="actual Windows pip console launcher ABI")
@pytest.mark.parametrize("relocation", ["copy", "move"])
def test_relocated_windows_runtime_cannot_be_selected_by_rehashing(tmp_path, monkeypatch, relocation):
    import thaliris
    import thaliris_codex
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    original = tmp_path / "original-final-runtime"
    result = runtime_setup.create(original, core, adapter)
    original_exe = Path(result["executable"])
    original_manifest = runtime_identity.manifest_bytes(original_exe)
    relocated = tmp_path / "relocated-runtime"
    if relocation == "copy":
        shutil.copytree(original, relocated)
    else:
        shutil.move(original, relocated)
    exe = relocated / "Scripts/thaliris.exe"
    # In the copy case the old interpreter still exists: this console actually
    # succeeds, reporting the ORIGINAL interpreter. Success alone is not proof
    # of the final-path identity invariant.
    probe = subprocess.run([str(exe), "runtime-check"], env=runtime_identity.child_environment(),
                           capture_output=True, timeout=15)
    if relocation == "copy":
        assert probe.returncode == 0, probe.stderr
        observed = json.loads(probe.stdout)
        assert observed["interpreter"] == str(original / "Scripts/python.exe")
        assert observed["venv_dir"] == str(original)
        assert runtime_identity.manifest_bytes(original_exe) == original_manifest
    else:
        assert probe.returncode != 0
    # Recompute every hash and rebase manifest topology without using the
    # validator to construct it. Explicit location validation must still fail.
    record = json.loads(original_manifest)
    record.update(executable=str(exe), venv_dir=str(relocated),
                  package_dir=str(relocated / "Lib/site-packages/thaliris_codex"),
                  files=runtime_identity._files(relocated))
    contents = (json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    identity = runtime_identity.manifest_identity(contents)
    selection = {"executable": str(exe), "runtime_sha256": identity,
                 "source_pin": "sha256:" + adapter.rsplit("=", 1)[1]}
    with pytest.raises(ValueError, match="location changed"):
        runtime_identity.validate_manifest(contents, exe, identity)
    with pytest.raises(ValueError, match="location changed"):
        host_maintenance.selected_runtime(selection)
    preflight = tmp_path / "preflight.ps1"
    preflight.write_bytes(host_preflight.script_bytes())
    manifest = tmp_path / runtime_identity.MANIFEST_NAME
    def native_rejects(current, diagnostic):
        manifest.write_bytes(current)
        environment = runtime_identity.child_environment()
        environment.pop("THALIRIS_HOOK_EVENT", None)
        environment.update(THALIRIS_INSTALL_MANIFEST=str(manifest),
                           THALIRIS_RUNTIME_SHA256=runtime_identity.manifest_identity(current),
                           THALIRIS_EXECUTABLE=str(exe))
        checked = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File", str(preflight)],
                                 env=environment, capture_output=True, timeout=15)
        assert checked.returncode != 0, checked.stdout
        failure = json.loads(checked.stdout)
        assert failure["status"] == "THALIRIS_RUNTIME_IDENTITY_MISMATCH"
        assert diagnostic in failure["diagnostic"]
    native_rejects(contents, "runtime location changed")
    # Rewriting/deleting the location anchor and recomputing hashes cannot
    # bless the installed launcher's immutable absolute interpreter binding.
    anchor = relocated / runtime_identity.LOCATION_NAME
    anchor.write_bytes(runtime_identity.location_bytes(relocated))
    with pytest.raises(ValueError, match="launcher location changed"):
        runtime_identity.manifest_bytes(exe)
    # Store-local resolution of an old logical alias must never hide the
    # launcher's noncanonical lexical binding. It is rejected before that
    # alias can be resolved, even if an app would map it to the new interpreter.
    resolved_aliases = []
    safe_file = runtime_identity._safe_file
    def alias(path):
        if path == original / "Scripts/python.exe":
            resolved_aliases.append(path)
            return relocated / "Scripts/python.exe"
        return safe_file(path)
    with monkeypatch.context() as mapped:
        mapped.setattr(runtime_identity, "_safe_file", alias)
        with pytest.raises(ValueError, match="launcher location changed"):
            runtime_identity._assert_launcher_binding(exe)
    assert resolved_aliases == []
    record["files"] = runtime_identity._files(relocated)
    rebased = (json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    native_rejects(rebased, "runtime launcher location changed")
    anchor.unlink()
    with pytest.raises(ValueError, match="launcher location changed"):
        runtime_identity.manifest_bytes(exe)


def test_redirected_destination_stops_before_venv_or_package_install(tmp_path, monkeypatch):
    import thaliris
    import thaliris_codex
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    target = tmp_path / "requested-runtime"
    actual = tmp_path / "physical-runtime"
    monkeypatch.setattr(runtime_setup, "_owned_directory_physical_path", lambda _owned: actual)
    calls = []
    monkeypatch.setattr(runtime_setup.venv.EnvBuilder, "create", lambda *_args: calls.append("venv"))
    monkeypatch.setattr(runtime_setup.subprocess, "run", lambda *_args, **_kw: calls.append("pip"))
    with pytest.raises(ValueError, match="select final physical directory") as error:
        runtime_setup.create(target, core, adapter)
    assert calls == []
    assert target.exists() is (os.name != "nt")
    if os.name != "nt":
        assert "created directory was preserved because safe empty cleanup was unavailable" in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="atomic created-directory cleanup is Windows-native")
def test_redirected_empty_cleanup_allows_same_path_retry(tmp_path, monkeypatch):
    target = tmp_path / "requested-runtime"
    actual = tmp_path / "physical-runtime"
    core = "git+https://example.test/core@" + "a" * 40
    adapter = "git+https://example.test/adapter@" + "b" * 40
    monkeypatch.setattr(runtime_setup, "_owned_directory_physical_path", lambda _owned: actual)
    with pytest.raises(ValueError, match="select final physical directory"):
        runtime_setup.create(target, core, adapter)
    assert not target.exists()

    calls = []
    monkeypatch.setattr(runtime_setup, "_owned_directory_physical_path", lambda _owned: target)
    monkeypatch.setattr(runtime_identity, "location_bytes", lambda _path: b"location")
    monkeypatch.setattr(runtime_setup.venv.EnvBuilder, "create", lambda *_args: calls.append("venv"))
    monkeypatch.setattr(runtime_setup.subprocess, "run", lambda *_args, **_kwargs: calls.append("command"))
    monkeypatch.setattr(runtime_identity, "manifest_bytes", lambda _executable: b"manifest")
    monkeypatch.setattr(runtime_identity, "manifest_identity", lambda _contents: "digest")
    monkeypatch.setattr(runtime_identity, "console_smoke", lambda *_args: {"ok": True})
    monkeypatch.setattr(host_preflight, "verify_runtime", lambda *_args: None)

    result = runtime_setup.create(target, core, adapter)
    assert result["ok"]
    assert target.is_dir()
    assert calls == ["venv", "command", "command"]


def test_redirected_destination_cleanup_preserves_nonempty_attempt_directory(tmp_path, monkeypatch):
    import thaliris
    import thaliris_codex
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    adapter = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    target = tmp_path / "requested-runtime"
    actual = tmp_path / "physical-runtime"
    marker = target / "created-after-probe"

    def redirected(path):
        marker.write_text("preserve", encoding="utf-8")
        return actual

    monkeypatch.setattr(runtime_setup, "_owned_directory_physical_path", redirected)
    with pytest.raises(ValueError, match="created directory was preserved because safe empty cleanup was unavailable"):
        runtime_setup.create(target, core, adapter)
    assert target.is_dir()
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_redirected_destination_setup_blocks_replacement_after_create(tmp_path, monkeypatch):
    target = tmp_path / "requested-runtime"
    displaced = tmp_path / "original-attempt-directory"
    actual = tmp_path / "physical-runtime"
    sentinel = target / "replacement-owned.txt"

    create_owned = runtime_setup._create_owned_directory

    def replace_after_atomic_create(path):
        owned = create_owned(path)
        # Reproduce replacement after the native create returned but before the
        # caller could have captured a path identity. Windows keeps the target
        # open without delete sharing, so this competing rename must fail.
        try:
            path.rename(displaced)
        except OSError:
            assert os.name == "nt"
        else:
            path.mkdir()
            (path / sentinel.name).write_text("preserve", encoding="utf-8")
        return owned

    monkeypatch.setattr(runtime_setup, "_create_owned_directory", replace_after_atomic_create)
    monkeypatch.setattr(runtime_setup, "_owned_directory_physical_path", lambda _owned: actual)
    with pytest.raises(ValueError, match="select final physical directory"):
        runtime_setup.create(target, "git+https://example.test/core@" + "a" * 40,
                             "git+https://example.test/adapter@" + "b" * 40)
    if os.name == "nt":
        assert not target.exists()
        assert not displaced.exists()
    else:
        assert target.is_dir()
        assert sentinel.read_text(encoding="utf-8") == "preserve"
        assert displaced.is_dir()


def test_redirected_cleanup_blocks_replacement_after_path_check(tmp_path, monkeypatch):
    target = tmp_path / "requested-runtime"
    displaced = tmp_path / "original-attempt-directory"
    actual = tmp_path / "physical-runtime"
    sentinel = target / "replacement-owned.txt"
    remove_owned = runtime_setup._remove_owned_directory_if_empty

    def replace_at_cleanup_boundary(owned):
        # This is the old identity-check / rmdir gap: replace the name after
        # the destination check, exactly before cleanup's destructive action.
        try:
            target.rename(displaced)
        except OSError:
            assert os.name == "nt"
        else:
            target.mkdir()
            (target / sentinel.name).write_text("preserve", encoding="utf-8")
        remove_owned(owned)

    monkeypatch.setattr(runtime_setup, "_owned_directory_physical_path", lambda _owned: actual)
    monkeypatch.setattr(runtime_setup, "_remove_owned_directory_if_empty", replace_at_cleanup_boundary)
    with pytest.raises(ValueError, match="select final physical directory"):
        runtime_setup.create(target, "git+https://example.test/core@" + "a" * 40,
                             "git+https://example.test/adapter@" + "b" * 40)
    if os.name == "nt":
        assert not target.exists()
        assert not displaced.exists()
    else:
        assert sentinel.read_text(encoding="utf-8") == "preserve"
        # Portable fallback preserves both names because it cannot perform
        # race-safe removal by handle.
        assert displaced.exists()


def test_redirected_destination_does_not_touch_preexisting_target(tmp_path, monkeypatch):
    target = tmp_path / "preexisting-runtime"
    target.mkdir()
    sentinel = target / "user-owned.txt"
    sentinel.write_text("keep", encoding="utf-8")
    probed = []
    monkeypatch.setattr(runtime_identity, "physical_directory", lambda path: probed.append(path))

    with pytest.raises(ValueError, match="already exists"):
        runtime_setup.create(target, "git+https://example.test/core@" + "a" * 40,
                             "git+https://example.test/adapter@" + "b" * 40)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert probed == []


@pytest.mark.skipif(os.name != "nt", reason="Windows Codex package LocalCache discovery")
def test_default_runtime_resolves_current_host_cache_before_creating_candidate(tmp_path, monkeypatch):
    family = "OpenAI.Codex_2p2nqsd0c76g0"
    app_data = tmp_path / "AppData" / "Local"
    logical_cache = app_data / "Packages" / family / "LocalCache" / "Local"
    logical_cache.mkdir(parents=True)
    physical_cache = tmp_path / "physical-local-cache"
    physical_cache.mkdir()
    monkeypatch.setenv(runtime_setup._HOST_PACKAGE_FAMILY_ENV, family)
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))
    observed = []

    def resolve(path):
        observed.append(path)
        assert path == logical_cache
        assert path.is_dir()
        return physical_cache

    monkeypatch.setattr(runtime_identity, "physical_directory", resolve)
    target = runtime_setup.default_runtime_directory(
        "git+https://example.test/adapter@" + "c" * 40)
    assert observed == [logical_cache]
    assert target.parent == physical_cache / "Thaliris" / "runtimes"
    assert target.name.startswith("codex-")
    assert not target.exists()
    assert not target.parent.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows AppX package discovery")
def test_default_runtime_external_terminal_selects_only_exact_codex_package(tmp_path, monkeypatch):
    monkeypatch.delenv(runtime_setup._HOST_PACKAGE_FAMILY_ENV, raising=False)
    app_data = tmp_path / "AppData" / "Local"
    logical_cache = app_data / "Packages" / "OpenAI.Codex_2p2nqsd0c76g0" / "LocalCache" / "Local"
    logical_cache.mkdir(parents=True)
    physical_cache = tmp_path / "physical-local-cache"
    physical_cache.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))
    calls = []

    def registered_package(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "OpenAI.Codex_2p2nqsd0c76g0", "")

    monkeypatch.setattr(runtime_setup.subprocess, "run", registered_package)
    monkeypatch.setattr(runtime_identity, "physical_directory", lambda path: physical_cache)
    target = runtime_setup.default_runtime_directory(
        "git+https://example.test/adapter@" + "d" * 40)
    assert target.parent == physical_cache / "Thaliris" / "runtimes"
    assert len(calls) == 1
    assert "Get-AppxPackage -Name 'OpenAI.Codex'" in calls[0][0][-1]
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows Codex package discovery")
@pytest.mark.parametrize("package_result", [
    subprocess.CompletedProcess([], 2, "", ""),
    subprocess.CompletedProcess([], 0, "OpenAI.Codex_2p2nqsd0c76g0\nOpenAI.Codex_3p3nqsd0c76g0", ""),
])
def test_default_runtime_fails_closed_without_unique_host_registration(tmp_path, monkeypatch, package_result):
    monkeypatch.delenv(runtime_setup._HOST_PACKAGE_FAMILY_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(runtime_setup.subprocess, "run", lambda *args, **kwargs: package_result)
    observed = []
    monkeypatch.setattr(runtime_identity, "physical_directory", lambda path: observed.append(path))
    with pytest.raises(ValueError, match="unique current Codex Host package"):
        runtime_setup.default_runtime_directory("git+https://example.test/adapter@" + "e" * 40)
    assert observed == []


@pytest.mark.skipif(os.name != "nt", reason="Windows Codex package discovery")
def test_default_runtime_fails_closed_on_invalid_host_package_context(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime_setup._HOST_PACKAGE_FAMILY_ENV, "Other.Package_2p2nqsd0c76g0")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(runtime_setup.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not enumerate packages"))
    observed = []
    monkeypatch.setattr(runtime_identity, "physical_directory", lambda path: observed.append(path))
    with pytest.raises(ValueError, match="package context is invalid"):
        runtime_setup.default_runtime_directory("git+https://example.test/adapter@" + "f" * 40)
    assert observed == []


def test_runtime_setup_cli_defaults_to_discovery_but_keeps_explicit_override(tmp_path, monkeypatch, capsys):
    automatic = tmp_path / "host" / "runtime"
    explicit = tmp_path / "custom" / "runtime"
    default_calls = []
    created = []
    monkeypatch.setattr(runtime_setup, "default_runtime_directory",
                        lambda source: default_calls.append(source) or automatic)
    monkeypatch.setattr(runtime_setup, "create",
                        lambda path, core, adapter: created.append((path, core, adapter)) or {"ok": True})
    sources = ["git+https://example.test/core@" + "a" * 40,
               "git+https://example.test/adapter@" + "b" * 40]

    monkeypatch.setattr(runtime_setup.sys, "argv", ["runtime_setup", "--core-source", sources[0],
                                                      "--adapter-source", sources[1]])
    assert runtime_setup.main() == 0
    capsys.readouterr()
    assert created[-1][0] == automatic
    assert default_calls == [sources[1]]

    monkeypatch.setattr(runtime_setup.sys, "argv", ["runtime_setup", "--runtime", str(explicit),
                                                      "--core-source", sources[0],
                                                      "--adapter-source", sources[1]])
    assert runtime_setup.main() == 0
    capsys.readouterr()
    assert created[-1][0] == explicit
    assert default_calls == [sources[1]]


def test_prior_owned_generation_without_location_or_probe_can_upgrade(tmp_path, monkeypatch):
    """Real prior console ABI, exact receipt ownership, and new candidate entry."""
    import thaliris
    import thaliris_codex
    import venv
    from thaliris_codex import lifecycle
    core = source_wheel(tmp_path, "thaliris", Path(thaliris.__file__).parent)
    legacy_sources = tmp_path / "legacy-sources"
    legacy_sources.mkdir()
    old_wheel = source_wheel(legacy_sources, "thaliris_codex", Path(thaliris_codex.__file__).parent,
                            entry=True, legacy_cli=True)
    old_runtime = tmp_path / "prior-final-runtime"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(old_runtime)
    old_python = old_runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([sys.executable, "-I", "-B", "-m", "pip", "--isolated", "--python", str(old_python),
        "install", "--no-deps", "--no-compile", runtime_setup._source(core), runtime_setup._source(old_wheel)],
        env=runtime_identity.child_environment(), check=True, capture_output=True)
    old_exe = old_python.parent / ("thaliris.exe" if os.name == "nt" else "thaliris")
    assert subprocess.run([str(old_exe), "version"], env=runtime_identity.child_environment(),
                          capture_output=True).returncode == 0
    assert subprocess.run([str(old_exe), "runtime-check"], env=runtime_identity.child_environment(),
                          capture_output=True).returncode != 0
    assert not (old_runtime / runtime_identity.LOCATION_NAME).exists()
    prior = runtime_identity._manifest_bytes(old_exe, candidate=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    (home / runtime_identity.MANIFEST_NAME).write_bytes(prior)
    global_bytes = b"<!-- thaliris:global:begin -->\n## Authorized prior generation\n<!-- thaliris:global:end -->\n"
    (home / "AGENTS.md").write_bytes(global_bytes)
    (home / "agents").mkdir()
    profile = b"# Independently authorized prior profile bytes\n"
    (home / "agents/thaliris-implementer.toml").write_bytes(profile)
    receipt = {"format": host_maintenance.RECEIPT_FORMAT,
        "runtime_sha256": host_maintenance.digest(prior), "maintenance_contract_sha256": "a" * 64,
        "human_instruction": "The prior test operator authorized these exact historical bytes.",
        "source_pin": "sha256:" + old_wheel.rsplit("=", 1)[1], "execution_constraint": None,
        "owned_bytes": {"AGENTS.md#global": host_maintenance.digest(host_maintenance._global_owned_bytes(global_bytes)),
                        "agents/thaliris-implementer.toml": host_maintenance.digest(profile)},
        "hook_handlers": {}}
    (home / host_maintenance.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
    assert host_maintenance._installed(home) == prior
    assert host_maintenance.ownership(home, prior, {}) == receipt
    old_selected = {"executable": str(old_exe), "runtime_sha256": host_maintenance.digest(prior),
                    "source_pin": receipt["source_pin"]}
    with pytest.raises(ValueError, match="final-location setup anchor"):
        host_maintenance.selected_runtime(old_selected)
    # Candidate rendering cannot establish ownership of that prior profile.
    new_wheel = source_wheel(tmp_path, "thaliris_codex", Path(thaliris_codex.__file__).parent, entry=True)
    candidate = runtime_setup.create(tmp_path / "new-final-runtime", core, new_wheel)
    exe = Path(candidate["executable"])
    selected = {"executable": str(exe), "runtime_sha256": candidate["runtime_sha256"],
                "source_pin": "sha256:" + new_wheel.rsplit("=", 1)[1]}
    intent = {"format": host_maintenance.FORMAT, "operation": "codex-install", "codex_home": str(home),
        "human_instruction": "Upgrade the independently owned prior test generation to this exact final-path candidate.",
        "executor": selected, "candidate": selected, "installed_runtime_sha256": host_maintenance.digest(prior),
        "execution_constraint": None}
    contract = tmp_path / "upgrade.json"
    contract.write_text(json.dumps(intent), encoding="utf-8")
    expected = len(lifecycle.HOOK_EVENTS)
    monkeypatch.setattr(codex_adapter, "_install_host_hook_trust", lambda *a: {
        "status": "TRUSTED", "trusted_count": expected, "enabled_count": expected, "changed": False})
    before = host_maintenance._files(home)
    (home / host_maintenance.RECEIPT_NAME).unlink()
    rejected = codex_adapter.codex_install(maintenance_contract=contract)
    assert not rejected["ok"]
    assert (home / "AGENTS.md").read_bytes() == global_bytes
    assert (home / "agents/thaliris-implementer.toml").read_bytes() == profile
    (home / host_maintenance.RECEIPT_NAME).write_bytes(before[host_maintenance.RECEIPT_NAME])
    original_smoke = runtime_identity.console_smoke
    def smoke(path, contents):
        assert path != old_exe, "the prior generation must not be required to expose a new probe"
        return original_smoke(path, contents)
    monkeypatch.setattr(runtime_identity, "console_smoke", smoke)
    upgraded = codex_adapter.codex_install(maintenance_contract=contract)
    assert upgraded["ok"], upgraded
    assert (home / runtime_identity.MANIFEST_NAME).read_bytes() == runtime_identity.manifest_bytes(exe)
    assert host_maintenance.ownership(home, host_maintenance._installed(home), {})["runtime_sha256"] == candidate["runtime_sha256"]
    assert runtime_identity._manifest_bytes(old_exe, candidate=False) == prior


def test_runtime_setup_rejects_unpinned_or_changed_artifacts_before_create(tmp_path):
    target = tmp_path / "runtime"
    with pytest.raises(ValueError, match="immutable"):
        runtime_setup.create(target, "git+https://example.test/core@main", "unreviewed")
    assert not target.exists()
    artifact = tmp_path / "test.whl"
    artifact.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="artifact identity mismatch"):
        runtime_setup.create(target, str(artifact) + "#sha256=" + "0" * 64, "unreviewed")
    assert not target.exists()
