"""Real shell/argv coverage for the single native task-observe action."""
from __future__ import annotations

import json
import base64
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from thaliris import core
from thaliris_codex import cli, lifecycle, observation_transport, task_authority
from tests.test_evidence_continuity_adapter import (
    evidence_task, _identity, _observation, _opaque_request, _register_requirement,
    _preselect, _selected_message, _spawn,
)


def _request(child, command, shell="powershell"):
    return {**child, "tool_name": "Bash", "readonly": True,
            "tool_input": {"command": command, "shell": shell}}


def _route(root, request):
    result = json.loads(lifecycle.handle_hook(root, "PreToolUse", request))["hookSpecificOutput"]
    assert result["permissionDecision"] == "allow", result
    return result["updatedInput"]["command"]


def _literal(value, shell):
    return "'" + value.replace("'", "''") + "'" if shell == "powershell" else shlex.quote(value)


def _shell_entry(root, monkeypatch):
    """Real .cmd/Python dispatch, with fixture-only authority storage.

    No Host installation or immutable-package activation is claimed. The
    dispatch line matches host_run_script_bytes; the Python shim only selects
    the test's external authority directory before the real CLI entry point.
    """
    script = root / "test-cli.py"
    script.write_text(
        "from pathlib import Path\nfrom thaliris_codex import cli, task_authority\n"
        f"task_authority.directory=lambda: Path({str(task_authority.directory())!r})\n"
        "raise SystemExit(cli.main())\n", encoding="utf-8")
    runner = root / "thaliris.cmd"
    runner.write_bytes((
        '@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
        f'"{sys.executable}" "{script}" %*\r\nexit /b %ERRORLEVEL%\r\n'
    ).encode("utf-8"))
    monkeypatch.setattr(lifecycle, "_trusted_installed_runner", lambda: runner)
    return runner, script


@pytest.mark.parametrize("shell", ["powershell", "bash"])
@pytest.mark.parametrize("ending", ["", "\n", "\r\n \t\n"])
def test_first_opaque_and_nested_observations_through_real_shell(evidence_task, monkeypatch, shell, ending):
    if shell == "powershell" and os.name != "nt":
        pytest.skip("Windows .cmd boundary")
    binary = shutil.which("pwsh" if shell == "powershell" else "bash")
    if shell == "bash" and os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        binary = str(git_bash) if git_bash.is_file() else None
    if binary is None:
        pytest.skip(f"{shell} unavailable")
    root, task_id = evidence_task
    _register_requirement(root)
    _preselect(root, candidate="C-shell")
    request = _opaque_request()
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", request)
    parent = _identity("implementer", "shell-parent")
    assert lifecycle._record_subagent_start(root, parent)
    runner, script = _shell_entry(root, monkeypatch)
    nested_request = {**_opaque_request("investigator"), **parent}
    assert "deny" not in lifecycle.handle_hook(root, "PreToolUse", nested_request)
    scanner = _identity("investigator", "shell-scanner")
    assert lifecycle._record_subagent_start(root, scanner)
    for child, identifier in ((parent, "O-shell-parent"), (scanner, "O-shell-scanner")):
        body = _observation(identifier)
        body["text"] = '雪 🪷 "quoted" C:\\path\\ trailing\\ Native\'s apply_patch > source.py; $(New-Item bad) & git reset --hard --handoff-id forged %PATH% !bang! `tick` literal \\r\\n '
        body["text"] += ".context/" + "tasks/state.json"
        body["text"] += " " + "".join(chr(code) for code in range(0x2018, 0x2020))
        body["sources"][0]["locator"] = 'C:\\a\\b\\ "x"'
        inline = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if shell == "powershell":
            for code in range(0x2018, 0x2020):
                inline = inline.replace(chr(code), f"\\u{code:04x}")
        role = child["agent_type"][9:]
        if shell == "powershell":
            command = f"& '{runner}' --root '{root}' task-observe --role {role} --observation-json " + _literal(inline, shell)
        else:
            posix_runner = root / "thaliris"
            posix_runner.write_text(f'#!/bin/sh\nexec {shlex.quote(Path(sys.executable).as_posix())} {shlex.quote(script.as_posix())} "$@"\n', encoding="utf-8")
            posix_runner.chmod(0o755)
            command = f"thaliris --root {shlex.quote(str(root))} task-observe --role {role} --observation-json " + _literal(inline, shell)
        updated = _route(root, _request(child, command + ending, shell))
        assert "utf8-base64:" in updated
        assert updated.endswith(ending)
        assert "--task-id " in updated.splitlines()[0]
        assert "--handoff-id " in updated.splitlines()[0]
        assert "--agent-id-hash " in updated.splitlines()[0]
        env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"], "PYTHONUTF8": "1"}
        args = [binary, "-NoProfile", "-NonInteractive", "-Command", updated] if shell == "powershell" else [binary, "-c", updated]
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env)
        assert result.returncode == 0, (result.stdout, result.stderr, updated)
        assert json.loads(result.stdout)["ok"] is True
        stored = core.task_get(root, identifier)["object"]
        assert stored["text"] == body["text"]
        source = core.task_get(root, body["source_refs"][0])["object"]
        assert source["locator"] == body["sources"][0]["locator"]
        assert stored["candidate"] == "C-shell"
        assert stored["native_actor"] == lifecycle._identity_hash(child["agent_id"])
        assert stored["requirement_refs"] == (["R1"] if child is parent else [])
        assert task_authority.check(root) is not None
    assert not (root / "source.py").exists() and not (root / "bad").exists()
    handoffs = core.task_show(root)["state"]["evidence_continuity"]["handoffs"]
    assert handoffs[1]["parent_handoff_id"] == handoffs[0]["id"]


@pytest.mark.parametrize("suffix", [" > source.py", "; New-Item bad", " && git reset --hard", " | Set-Content source.py", " $(New-Item bad)", "\nNew-Item bad\n", "\n > source.py\n", "; Set-Content " + ".context/" + "tasks/state.json bad"])
def test_payload_normalization_never_hides_executable_syntax(evidence_task, suffix):
    root, _ = evidence_task
    _register_requirement(root)
    child, _ = _spawn(root, "reviewer", "readonly-shell", marker=_selected_message())
    inline = json.dumps(_observation("O-denied"), separators=(",", ":"))
    command = f'thaliris --root "{root}" task-observe --role reviewer --observation-json \'{inline}\''
    assert "deny" in lifecycle.handle_hook(root, "PreToolUse", _request(child, command + suffix))
    assert not core.task_show(root)["state"]["evidence_continuity"]["observations"]


@pytest.mark.parametrize("suffix", [";\n", " |\n", " &&\n", " \\\n", " `\n", "\n# trailing comment\n", "\nthaliris version\n"])
def test_trailing_whitespace_does_not_admit_compound_or_incomplete_commands(suffix):
    command = "thaliris task-observe --role investigator --observation-json '{}'" + suffix
    payload = {"tool_input": {"cmd": command, "shell": "powershell"}}
    assert lifecycle._context_call(payload) == (None, [])


def test_identity_insertion_preserves_horizontal_whitespace_before_terminal_lines():
    command = "thaliris task-observe --role investigator --input existing.json\\ \n \t\n"
    payload = {"tool_input": {"cmd": command}}
    result = json.loads(lifecycle._updated_command_output(payload, "--task-id exact"))
    assert result["hookSpecificOutput"]["updatedInput"]["cmd"] == (
        "thaliris task-observe --role investigator --input existing.json\\  --task-id exact\n \t\n")


def test_transport_keeps_exact_hook_identity_rejections(evidence_task):
    root, _ = evidence_task
    _register_requirement(root)
    child, _ = _spawn(root, "reviewer", "readonly-forgery", marker=_selected_message())
    inline = json.dumps(_observation("O-forged"))
    command = f'thaliris --root "{root}" task-observe --role reviewer --observation-json \'{inline}\''
    for suffix in (" --handoff-id forged", " --agent-id-hash " + "0" * 64, " --task-id forged"):
        assert "deny" in lifecycle.handle_hook(root, "PreToolUse", _request(child, command + suffix))
    assert "deny" in lifecycle.handle_hook(root, "PreToolUse", _request(child, command.replace("--role reviewer", "--role implementer")))


def test_direct_json_and_legacy_native_escaping_are_preserved():
    body = {"id": "O1", "text": "雪"}
    assert observation_transport.decode(json.dumps(body)) == body
    legacy = r'''thaliris task-observe --role reviewer --observation-json '{\"id\":\"O1\"}' '''
    assert observation_transport.literal_object_argument(legacy, powershell=True) is None
    for value in ("utf8-base64:%%%", "utf8-base64:_w=="):
        with pytest.raises(ValueError):
            observation_transport.decode(value)


@pytest.mark.parametrize("forged", [
    {"candidate": "other"}, {"requirement_refs": ["R-other"]},
    {"producer": "controller"}, {"native_actor": "0" * 64},
    {"submitted_by": "controller"}, {"native_status": "completed"},
])
def test_encoded_observation_retains_body_provenance_checks(evidence_task, capsys, forged):
    root, _ = evidence_task
    _register_requirement(root)
    child, _ = _spawn(root, "reviewer", "encoded-forgery", marker=_selected_message())
    inline = json.dumps({**_observation("O-forged"), **forged})
    command = f'thaliris --root "{root}" task-observe --role reviewer --observation-json \'{inline}\''
    updated = _route(root, _request(child, command))
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert not core.task_show(root)["state"]["evidence_continuity"]["observations"]


def test_legacy_existing_input_file_retains_child_binding(evidence_task, capsys):
    root, _ = evidence_task
    _register_requirement(root)
    child, handoff = _spawn(root, "reviewer", "legacy-input", marker=_selected_message())
    source = root / "already-selected.json"
    source.write_text(json.dumps(_observation("O-input")), encoding="utf-8")
    command = f'thaliris --root "{root}" task-observe --role reviewer --input "{source}"'
    updated = _route(root, _request(child, command))
    assert "utf8-base64:" not in updated
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert core.task_get(root, "O-input")["object"]["handoff_id"] == handoff


def test_readonly_reviewer_records_write_refusal_as_literal_data(evidence_task, capsys):
    root, _ = evidence_task
    _register_requirement(root)
    child, _ = _spawn(root, "reviewer", "readonly-report", marker=_selected_message())
    body = _observation("O-write-refusal")
    body["text"] = "apply_patch was denied; Set-Content did not execute > probe.txt"
    command = f'thaliris --root "{root}" task-observe --role reviewer --observation-json \'{json.dumps(body)}\''
    updated = _route(root, _request(child, command))
    assert "apply_patch" not in updated
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert core.task_get(root, "O-write-refusal")["object"]["text"] == body["text"]
    fenced = {**_request(child, command), "fenced": True}
    assert "THALIRIS_FENCED_ACTOR" in lifecycle.handle_hook(root, "PreToolUse", fenced)


@pytest.mark.parametrize("quote", [chr(code) for code in range(0x2018, 0x2020)])
def test_powershell_smart_quotes_refused_before_inline_normalization(evidence_task, quote):
    root, _ = evidence_task
    _register_requirement(root)
    child, _ = _spawn(root, "reviewer", "smart-quote", marker=_selected_message())
    # U+2019 is the exact reported boundary: native PowerShell sees Get-Date
    # as a second command, even though ASCII-only readers see one JSON literal.
    inline = json.dumps({"id": "O1", "text": "a" + quote + " ; Get-Date; " + quote + "b",
                         "source_refs": ["S1"]}, ensure_ascii=False, separators=(",", ":"))
    command = "thaliris task-observe --role reviewer --observation-json '" + inline + "'"
    with pytest.raises(observation_transport.UnsupportedShellQuote):
        observation_transport.literal_object_argument(command, powershell=True)
    result = json.loads(lifecycle.handle_hook(root, "PreToolUse", _request(child, command)))["hookSpecificOutput"]
    assert result["permissionDecision"] == "deny"
    assert "THALIRIS_UNSUPPORTED_SHELL_QUOTE" in result["permissionDecisionReason"]
    assert "updatedInput" not in result
    assert not core.task_show(root)["state"]["evidence_continuity"]["observations"]
    # POSIX gives the same Unicode text literal semantics, so it remains data.
    normalized = observation_transport.literal_object_argument(command, powershell=False)
    assert observation_transport.decode(normalized.rsplit(" ", 1)[1]) == json.loads(inline)


def test_escaped_smart_quotes_keep_single_powershell_observation(evidence_task, capsys):
    root, _ = evidence_task
    _register_requirement(root)
    child, _ = _spawn(root, "reviewer", "escaped-smart-quote", marker=_selected_message())
    body = _observation("O-escaped-smart")
    body["text"] = "".join(chr(code) for code in range(0x2018, 0x2020)) + " ; Get-Date"
    command = f'thaliris --root "{root}" task-observe --role reviewer --observation-json \'' + json.dumps(body) + "'"
    updated = _route(root, _request(child, command))
    tokens = [token.strip("\"'") for token in shlex.split(updated, posix=False)]
    assert cli.main(tokens[1:]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert core.task_get(root, body["id"])["object"]["text"] == body["text"]


@pytest.mark.parametrize("quote", [chr(code) for code in range(0x2018, 0x201C)])
def test_native_powershell_ast_exposes_smart_apostrophe_command_without_execution(quote):
    binary = shutil.which("pwsh") or shutil.which("powershell")
    if binary is None:
        pytest.skip("PowerShell parser unavailable")
    inline = json.dumps({"id": "O1", "text": "a" + quote + " ; Get-Date; " + quote + "b",
                         "source_refs": ["S1"]}, ensure_ascii=False, separators=(",", ":"))
    command = "thaliris task-observe --role reviewer --observation-json '" + inline + "'"
    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    script = (
        "$source=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'));"
        "$tokens=$null;$errors=$null;"
        "$ast=[System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors);"
        "$commands=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]},$true));"
        "@{commands=@($commands|ForEach-Object{$_.GetCommandName()});errors=@($errors|ForEach-Object{$_.ErrorId})}|ConvertTo-Json -Compress"
    )
    result = subprocess.run([binary, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                             base64.b64encode(script.encode("utf-16le")).decode("ascii")],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed == {"commands": ["thaliris", "Get-Date"], "errors": []}
