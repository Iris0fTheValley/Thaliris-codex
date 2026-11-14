"""Run the probe's actual CLI/HTTP boundary with a minimal simulated CLI."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from thaliris_codex import config_capability as probe
from thaliris_codex import mode_hint_config as hint, wait_guidance_config as guidance


CLI = r'''
import json, os, pathlib, sys, tomllib
from urllib.request import Request, ProxyHandler, build_opener
behavior = sys.argv[1]
if sys.argv[2:] == ["--version"]:
    print("codex-cli 0.162.2")
    sys.exit(0)
arguments = sys.argv[2:]
disabled = []
index = 0
while index < len(arguments):
    if arguments[index] == "--disable" and index + 1 < len(arguments):
        disabled.append(arguments[index + 1])
        index += 2
    else:
        index += 1
if disabled != ["hooks", "plugins"]:
    print("missing isolated feature overrides", file=sys.stderr)
    sys.exit(3)
home = pathlib.Path(os.environ["CODEX_HOME"])
config = tomllib.loads((home / "config.toml").read_text())
assert pathlib.Path.cwd() == home / "workspace"
assert os.environ["HOME"] == str(home)
assert "OPENAI_API_KEY" not in os.environ
assert not (home / "auth.json").exists()
assert config["approval_policy"] == "never"
assert config["sandbox_mode"] == "read-only"
assert config["project_doc_max_bytes"] == 0
assert config["project_root_markers"] == [".thaliris-config-probe"]
assert (pathlib.Path.cwd() / ".thaliris-config-probe").exists()
field = ("multi_agent_mode_hint_text" if "features" in config else "developer_instructions")
value = config["features"]["multi_agent_v2"][field] if "features" in config else config[field]
if behavior == "unavailable":
    print("unrelated startup failure", file=sys.stderr)
    sys.exit(2)
runs = home.parent / "runs"
count = int(runs.read_text()) + 1 if runs.exists() else 1
runs.write_text(str(count))
if behavior == "control_fails" and count >= 4:
    print("environment stopped working after the integer run", file=sys.stderr)
    sys.exit(2)
if not isinstance(value, str) and behavior != "wrong_type_accepted":
    if behavior == "ambiguous_type_failure":
        print(field + ": string configuration unavailable", file=sys.stderr)
        sys.exit(2)
    if behavior == "unworded_type_failure":
        sys.exit(1)
    if behavior == "integer_silent":
        sys.exit(0)
    if behavior == "misattributed_type_failure":
        print("Error loading config.toml: invalid type: integer `123`, expected a string\n"
              "in `model_providers.config_probe.base_url`", file=sys.stderr)
        sys.exit(1)
    if behavior == "untagged_feature_error":
        print("Error loading config.toml: data did not match any variant of untagged enum "
              "FeatureToml\nin `features.multi_agent_v2`", file=sys.stderr)
        sys.exit(1)
    print(field + ": invalid type: integer, expected a string", file=sys.stderr)
    sys.exit(2)
developer = config["developer_instructions"]
if behavior == "ignored" and field == "developer_instructions":
    developer = "unrelated instructions"
if field == "multi_agent_mode_hint_text":
    if behavior == "ignored":
        developer += "\n<multi_agent_mode>builtin fallback</multi_agent_mode>"
    elif value or behavior == "empty_ignored":
        developer += "\n<multi_agent_mode>\n" + str(value or "builtin fallback") + "\n</multi_agent_mode>"
body = {"input": [{"role": "developer", "content": [{"type": "input_text", "text": developer}]},
                  {"role": "user", "content": [{"type": "input_text", "text": sys.argv[-1]}]}]}
url = config["model_providers"]["config_probe"]["base_url"] + "/responses"
request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
build_opener(ProxyHandler({})).open(request, timeout=3).read()
'''


def simulated_cli(tmp_path, monkeypatch, behavior):
    script = tmp_path / "cli.py"
    script.write_text(CLI, encoding="utf-8")
    run = subprocess.run
    calls = []

    def execute(args, **kwargs):
        assert args[0] == "controlled-cli"
        calls.append((args, kwargs))
        return run([sys.executable, str(script), behavior, *args[1:]], **kwargs)

    monkeypatch.delenv("THALIRIS_CODEX_EXECUTABLE", raising=False)
    monkeypatch.setattr(probe.shutil, "which", lambda _name: "controlled-cli")
    monkeypatch.setattr(probe.subprocess, "run", execute)
    monkeypatch.setattr(probe, "_system_config_paths", lambda: (
        tmp_path / "system" / "config.toml",
        tmp_path / "system" / "requirements.toml",
        tmp_path / "system" / "managed_config.toml",
    ))
    monkeypatch.setenv("OPENAI_API_KEY", "user-owned-secret-must-not-enter-probe")
    return calls


@pytest.mark.parametrize("module", [hint, guidance])
@pytest.mark.parametrize("behavior,expected", [
    ("compatible", "SUPPORTED"),
    ("ignored", "INCOMPATIBLE"),
    ("wrong_type_accepted", "INCOMPATIBLE"),
    ("unavailable", "UNKNOWN"),
    # Typed rejection is shown by behaviour, not by matching error wording.
    ("ambiguous_type_failure", "SUPPORTED"),
    ("unworded_type_failure", "SUPPORTED"),
    # Exit 0 without a request proves neither acceptance nor rejection.
    ("integer_silent", "UNKNOWN"),
    # The Host attributes its failure to an unrelated location.
    ("misattributed_type_failure", "UNKNOWN"),
    # The accepted run no longer works, so the failure is not attributable.
    ("control_fails", "UNKNOWN"),
])
def test_unknown_patch_uses_actual_isolated_cli_effect(tmp_path, monkeypatch, module, behavior, expected):
    calls = simulated_cli(tmp_path, monkeypatch, behavior)
    assert module.capability() == expected
    assert calls[0][0] == ["controlled-cli", "--version"]
    assert len(calls) >= 2
    for args, kwargs in calls[1:]:
        assert args[1] == "exec"
        assert "--skip-git-repo-check" in args and "--json" in args
        assert args[args.index("--disable"):args.index("--disable") + 4] == [
            "--disable", "hooks", "--disable", "plugins"]
        assert kwargs["env"]["HTTP_PROXY"].startswith("http://127.0.0.1:")
        assert kwargs["stdin"] is subprocess.DEVNULL  # exec would wait on an inherited pipe
        assert not Path(kwargs["env"]["CODEX_HOME"]).exists()  # scratch removed


@pytest.mark.parametrize("module,expected", [(hint, "SUPPORTED"), (guidance, "UNKNOWN")])
def test_untagged_feature_rejection_proves_only_the_mode_hint_leaf(
        tmp_path, monkeypatch, module, expected):
    # Codex reports a wrong-typed mode hint through its bool-or-table feature enum.
    simulated_cli(tmp_path, monkeypatch, "untagged_feature_error")
    assert module.capability() == expected


@pytest.mark.parametrize("module", [hint, guidance])
@pytest.mark.parametrize("state", ["present", "unreadable", "unknown", "lookup_error"])
def test_system_config_presence_or_uncertainty_blocks_exec(
        tmp_path, monkeypatch, module, state):
    calls = simulated_cli(tmp_path, monkeypatch, "compatible")
    system_path = tmp_path / "real-system" / "config.toml"
    system_path.parent.mkdir()
    if state == "present":
        system_path.write_text("# managed config\n", encoding="utf-8")
        monkeypatch.setattr(probe, "_system_config_paths", lambda: (system_path,))
    elif state == "unreadable":
        original_lstat = Path.lstat

        def guarded_lstat(path):
            if path == system_path:
                raise PermissionError("system config existence is not observable")
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", guarded_lstat)
        monkeypatch.setattr(probe, "_system_config_paths", lambda: (system_path,))
    elif state == "lookup_error":
        def failed_lookup():
            raise OSError("known system config namespace is unavailable")

        monkeypatch.setattr(probe, "_system_config_paths", failed_lookup)
    else:
        monkeypatch.setattr(probe, "_system_config_paths", lambda: None)

    assert module.capability() == "UNKNOWN"
    assert len(calls) == 1
    assert calls[0][0] == ["controlled-cli", "--version"]


def test_system_config_paths_match_codex_local_system_layers(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "sys", type("Platform", (), {"platform": "linux"})())
    assert probe._system_config_paths() == (
        Path("/etc/codex/config.toml"),
        Path("/etc/codex/requirements.toml"),
        Path("/etc/codex/managed_config.toml"),
    )
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    assert probe._system_config_paths() is None


def test_windows_programdata_environment_does_not_select_system_config_root(
        tmp_path, monkeypatch):
    actual = tmp_path / "known-folder"
    redirected = tmp_path / "environment-redirect"
    fake = redirected / "OpenAI" / "Codex" / "config.toml"
    fake.parent.mkdir(parents=True)
    fake.write_text("# must not redirect known-folder lookup\n", encoding="utf-8")
    monkeypatch.setenv("PROGRAMDATA", str(redirected))
    monkeypatch.setattr(probe, "sys", type("Platform", (), {"platform": "win32"})())
    monkeypatch.setattr(probe, "_windows_program_data_dir", lambda: actual)

    assert probe._system_config_paths() == (
        actual / "OpenAI" / "Codex" / "config.toml",
        actual / "OpenAI" / "Codex" / "requirements.toml",
    )
    assert probe._system_config_is_absent()
    blocked = actual / "OpenAI" / "Codex" / "requirements.toml"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("# system requirements\n", encoding="utf-8")
    assert not probe._system_config_is_absent()


def test_mode_hint_empty_must_suppress_rendering(tmp_path, monkeypatch):
    simulated_cli(tmp_path, monkeypatch, "empty_ignored")
    assert hint.capability() == "INCOMPATIBLE"


@pytest.mark.parametrize("module", [hint, guidance])
@pytest.mark.parametrize("behavior,status", [
    ("compatible", "PLANNED"), ("ignored", "CAPABILITY_INCOMPATIBLE"),
    ("unavailable", "VERSION_SUPPORT_UNKNOWN"),
])
def test_planning_uses_verified_unknown_capability_and_preserves_user_bytes(
        tmp_path, monkeypatch, module, behavior, status):
    simulated_cli(tmp_path, monkeypatch, behavior)
    home = tmp_path / "user-home"
    home.mkdir()
    original = b'# user-owned\nmodel = "user-selected"\n'
    (home / "config.toml").write_bytes(original)
    planned = module.plan_install(home, {})
    assert planned[1]["status"] == status
    assert bool(planned[0]) == (status == "PLANNED")
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("module", [hint, guidance])
def test_existing_user_value_never_invokes_unknown_probe(tmp_path, monkeypatch, module):
    simulated_cli(tmp_path, monkeypatch, "compatible")
    home = tmp_path / "user-home"
    home.mkdir()
    original = (b'developer_instructions = ""\n' if module is guidance else
                b'[features.multi_agent_v2]\nmulti_agent_mode_hint_text = ""\n')
    (home / "config.toml").write_bytes(original)
    monkeypatch.setattr(module, "capability", lambda: pytest.fail("user value must precede probe"))
    assert module.plan_install(home, {})[1]["status"] == "USER_EMPTY_PRESERVED"
    assert (home / "config.toml").read_bytes() == original


def cached_cli(tmp_path, monkeypatch, behavior, *, name="codex.exe"):
    """A real file stands in for the resolved binary so its bytes can be hashed."""
    calls = simulated_cli(tmp_path, monkeypatch, behavior)
    binary = tmp_path / "bin" / name
    binary.parent.mkdir(exist_ok=True)
    binary.write_bytes(b"MZ simulated Codex binary one")
    run = probe.subprocess.run

    def execute(args, **kwargs):
        return run(["controlled-cli", *args[1:]], **kwargs)

    monkeypatch.setattr(probe.shutil, "which", lambda _name: str(binary))
    monkeypatch.setattr(probe.subprocess, "run", execute)
    return calls, binary


@pytest.mark.parametrize("module,field", [(hint, "multi_agent_mode_hint_text"),
                                          (guidance, "developer_instructions")])
def test_definitive_probe_result_is_reused_only_for_identical_binary_bytes(
        tmp_path, monkeypatch, module, field):
    calls, binary = cached_cli(tmp_path, monkeypatch, "compatible")
    assert module.capability() == "SUPPORTED"
    probed = len(calls)
    assert probed >= 5  # --version plus the four isolated exec runs
    assert module.capability() == "SUPPORTED"
    assert len(calls) == probed  # cache hit: no process at all
    cached = probe.cached_capability(field)
    assert cached["status"] == "SUPPORTED" and cached["evidence"] == "BINARY_SHA256_PROBE_CACHE"
    assert cached["cli_sha256"] == probe.binary_sha256(str(binary))
    entries = list(probe.cache_directory().glob("*.json"))
    assert len(entries) == 1
    assert json.loads(entries[0].read_bytes())["cli_version"] == "codex-cli 0.162.2"
    # Replaced bytes are a different Host: the old result does not apply.
    binary.write_bytes(b"MZ simulated Codex binary two")
    assert probe.cached_capability(field)["status"] == "UNKNOWN"
    assert module.capability() == "SUPPORTED"
    assert len(calls) > probed


def test_unknown_results_are_never_cached(tmp_path, monkeypatch):
    calls, _ = cached_cli(tmp_path, monkeypatch, "unavailable")
    assert hint.capability() == "UNKNOWN"
    first = len(calls)
    assert hint.capability() == "UNKNOWN"
    assert len(calls) == 2 * first
    assert not list(probe.cache_directory().glob("*.json"))


def test_incompatible_result_is_cached_and_still_preserves_user_bytes(tmp_path, monkeypatch):
    calls, _ = cached_cli(tmp_path, monkeypatch, "ignored")
    assert hint.capability() == "INCOMPATIBLE"
    first = len(calls)
    home = tmp_path / "user-home"
    home.mkdir()
    original = b'model = "user-selected"\n'
    (home / "config.toml").write_bytes(original)
    record, status = hint.plan_install(home, {})
    assert record is None and status["status"] == "CAPABILITY_INCOMPATIBLE"
    assert len(calls) == first
    assert (home / "config.toml").read_bytes() == original


@pytest.mark.parametrize("tamper", ["result", "binary", "contract", "format", "garbage"])
def test_tampered_or_foreign_cache_entries_grant_nothing(tmp_path, monkeypatch, tamper):
    calls, binary = cached_cli(tmp_path, monkeypatch, "unavailable")
    digest = probe.binary_sha256(str(binary))
    contract = probe._probe_contract()
    path = probe._cache_path(digest, "multi_agent_mode_hint_text", contract)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"format": probe.CACHE_FORMAT, "cli_sha256": digest, "field": "multi_agent_mode_hint_text",
             "probe_contract": contract, "result": "SUPPORTED", "cli_version": "codex-cli 0.162.2"}
    if tamper == "result":
        entry["result"] = "UNKNOWN"
    elif tamper == "binary":
        entry["cli_sha256"] = "f" * 64
    elif tamper == "contract":
        entry["probe_contract"] = "0" * 64
    elif tamper == "format":
        entry["format"] = "thaliris-config-capability-v0"
    path.write_bytes(b"not json" if tamper == "garbage" else json.dumps(entry).encode())
    assert hint.capability() == "UNKNOWN"
    assert len(calls) > 0  # the forged entry did not stand in for a probe


@pytest.mark.parametrize("name", ["codex.cmd", "codex.ps1", "codex.js"])
def test_launcher_scripts_are_probed_but_never_cached(tmp_path, monkeypatch, name):
    calls, binary = cached_cli(tmp_path, monkeypatch, "compatible", name=name)
    assert probe.binary_sha256(str(binary)) is None
    assert hint.capability() == "SUPPORTED"
    first = len(calls)
    assert hint.capability() == "SUPPORTED"
    assert len(calls) == 2 * first
    assert not list(probe.cache_directory().glob("*.json"))


def test_shebang_script_is_not_a_binary_identity(tmp_path):
    script = tmp_path / "codex"
    script.write_bytes(b"#!/usr/bin/env node\nrequire('codex')\n")
    assert probe.binary_sha256(str(script)) is None
    assert probe.binary_sha256(str(tmp_path / "missing.exe")) is None


def test_executable_resolution_matches_adapter_override(tmp_path, monkeypatch):
    selected = tmp_path / "selected" / "codex.exe"
    selected.parent.mkdir()
    selected.write_bytes(b"MZ selected")
    monkeypatch.setattr(probe.shutil, "which", lambda name: None if name == str(selected) else "path-codex")
    monkeypatch.setenv("THALIRIS_CODEX_EXECUTABLE", str(selected))
    assert probe.resolve_executable() == str(selected)
    monkeypatch.delenv("THALIRIS_CODEX_EXECUTABLE")
    assert probe.resolve_executable() == "path-codex"


def test_behavioural_rejection_never_follows_from_wording_alone():
    # Corroboration only: a named unrelated location blocks attribution, while
    # the leaf, its untagged parent or no location at all does not.
    assert probe._misattributed("in `model_providers.x.base_url`", "developer_instructions")
    assert not probe._misattributed("in `developer_instructions`", "developer_instructions")
    assert not probe._misattributed("no location", "developer_instructions")
    assert not probe._misattributed("in `features.multi_agent_v2`", "multi_agent_mode_hint_text")
    assert probe._misattributed("in `features.multi_agent_v2`", "developer_instructions")
