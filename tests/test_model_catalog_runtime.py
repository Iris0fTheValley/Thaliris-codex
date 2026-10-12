"""Opt-in integration coverage for the installed Codex app-server runtime."""
from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "verify_model_catalog_runtime.py"
EXPECTED_VERSION = "codex-cli 0.162.0-alpha.17.2"


@pytest.fixture
def runtime_module():
    spec = importlib.util.spec_from_file_location("thaliris_runtime_verification", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_isolated_native_environment_retains_windows_systemroot_without_credentials(runtime_module, monkeypatch, tmp_path):
    monkeypatch.setattr(os, "environ", {"SYSTEMROOT": r"C:\Windows", "WINDIR": r"C:\Windows", "PATH": "test-path", "OPENAI_API_KEY": "must-not-inherit", "HTTPS_PROXY": "must-not-inherit"})
    env = runtime_module._isolated_env(tmp_path / "home", tmp_path)
    assert env["SYSTEMROOT"] == r"C:\Windows"
    assert "OPENAI_API_KEY" not in env
    assert "HTTPS_PROXY" not in env


def test_parent_spawn_arguments_do_not_establish_child_request_capture(runtime_module):
    mock = runtime_module.ResponsesMock()
    try:
        mock.requests.append(runtime_module.CapturedRequest(
            {"input": [{"type": "function_call", "call_id": runtime_module.ROOT_IMPLEMENTER_CALL, "arguments": runtime_module.IMPLEMENTER_PROMPT}]},
            "/v1/responses", "parent", False,
        ))
        with pytest.raises(runtime_module.VerificationError, match="timed out waiting"):
            mock.wait_for_markers((runtime_module.IMPLEMENTER_PROMPT,), timeout=0)
        mock.requests.append(runtime_module.CapturedRequest(
            {"input": [{"type": "agent_message", "text": runtime_module.IMPLEMENTER_PROMPT}]},
            "/v1/responses", "child", False,
        ))
        assert len(mock.wait_for_markers((runtime_module.IMPLEMENTER_PROMPT,), timeout=0)) == 2
    finally:
        mock.close()


def test_installed_codex_emits_patched_catalog_and_role_instructions_to_mock_responses():
    if os.environ.get("THALIRIS_RUN_CODEX_RUNTIME_TESTS") != "1":
        pytest.skip("installed runtime acceptance is opt-in; set THALIRIS_RUN_CODEX_RUNTIME_TESTS=1; unexecuted runtime remains UNKNOWN")
    executable = os.environ.get("THALIRIS_CODEX_EXECUTABLE") or shutil.which("codex")
    if executable is None:
        pytest.fail("requested runtime acceptance is UNKNOWN: installed Codex CLI is unavailable")
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15, check=False)
    if version.returncode != 0 or version.stdout.strip() != EXPECTED_VERSION:
        pytest.fail(f"requested runtime acceptance is UNKNOWN: runtime integration is pinned to {EXPECTED_VERSION}")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    if result.returncode == 2:
        evidence = json.loads(result.stdout)
        if evidence.get("status") == "UNKNOWN":
            pytest.fail(
                "installed runtime request acceptance remains UNKNOWN; a missing native request is not a pass: "
                + evidence.get("reason", "no diagnostic reason was returned")
            )
    assert result.returncode == 0, result.stderr or result.stdout
    evidence = json.loads(result.stdout)
    assert evidence["status"] == "PASS"
    assert evidence["external_model_requests"] == 0
    assert evidence["catalog_patched_templates"] > 0
    assert evidence["model_catalog_json_loaded"] is True
    assert evidence["captured_roles"]["Controller"]["model_switch_template_lines"] >= 3
    assert evidence["captured_roles"]["Implementer"]["model"] == "gpt-6-luna"
    assert evidence["captured_roles"]["Implementer"]["effort"] == "max"
    assert evidence["captured_roles"]["Reviewer"]["model"] == "gpt-6.1-sol"
    assert evidence["captured_roles"]["Reviewer"]["effort"] == "high"
    assert evidence["captured_roles"]["nested Investigator Scanner"]["fresh"] is True
    assert evidence["fork_resume"]["preserved_parent_instructions"] is True
    assert evidence["native_catalog_parity"] is True
    assert evidence["native_delivery_limitations"]["explicit_fork_override"] in {"PASS", "NATIVE_LIMITATION"}
    assert evidence["native_delivery_limitations"]["cold_resume_updated_role_profile"] in {"PASS", "NATIVE_LIMITATION"}
    assert evidence["captured_roles"]["Controller"]["project_agents"] is True
    assert evidence["fork_resume"]["direct_child_resume_override_ignored"] is True
    assert evidence["fork_resume"]["cold_parent_resume_reentered_child"] is True
    assert evidence["fork_resume"]["direct_child_input_rejected"] is True
    assert {item["phase"] for item in evidence["request_evidence"]} == {item["phase"] for item in evidence["baseline_request_evidence"]}
