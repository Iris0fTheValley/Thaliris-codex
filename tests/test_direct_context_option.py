"""Scalar global options read from an already recognized direct CLI call.

`_context_cli_tokens` keeps quoted Windows paths verbatim, so a value written
as `--name="a b"` reaches the reader with its own surrounding quotes. Every
quoting style argparse accepts must therefore select the same unambiguous
value: an opening quote left in the value silently changes the Task ID,
session ID or authority-contract path that admission later uses.
"""
from __future__ import annotations

import pytest

from thaliris_codex import lifecycle


def _request(*arguments: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": "thaliris " + " ".join(arguments)}}


@pytest.mark.parametrize("argument", [
    "--task-id=abc-def",
    "--task-id abc-def",
    '--task-id="abc-def"',
    "--task-id='abc-def'",
    '"--task-id=abc-def"',
])
def test_task_id_selection_agrees_across_quoting_styles(argument):
    assert lifecycle._direct_context_option(
        _request(argument, "task-status"), {"--task-id"}, digest_only=False) == "abc-def"


@pytest.mark.parametrize("argument", [
    '--task-id="abc def"',
    "--task-id='abc def'",
])
def test_quoted_task_id_keeps_its_spaces_without_quotes(argument):
    assert lifecycle._direct_context_option(
        _request(argument, "task-status"), {"--task-id"}, digest_only=False) == "abc def"


@pytest.mark.parametrize("argument", [
    '--session-id="id123"',
    "--session-id='id123'",
    "--session-id id123",
])
def test_session_id_ignores_quoting_style(argument):
    assert lifecycle._direct_context_option(
        _request("task-status", argument), {"--session-id"}, digest_only=False) == "id123"


@pytest.mark.parametrize("argument", [
    '--authority-contract="C:\\AI PROJECT\\plan.json"',
    "--authority-contract='C:\\AI PROJECT\\plan.json'",
])
def test_authority_contract_path_is_selected_without_leading_quote(argument):
    assert lifecycle._direct_context_option(
        _request("task-start", argument), {"--authority-contract"}, digest_only=False
    ) == "C:\\AI PROJECT\\plan.json"


@pytest.mark.parametrize("argument", ['--role="verifier"', "--role=verifier", "--role verifier"])
def test_role_selection_ignores_quoting_style(argument):
    assert lifecycle._direct_context_option(
        _request("task-status", argument), {"--role"}, digest_only=False) == "verifier"


def test_digest_option_requires_the_exact_hash_after_dequoting():
    digest = "a" * 64
    assert lifecycle._direct_context_option(
        _request("task-status", f'--agent-id-hash="{digest}"'), {"--agent-id-hash"}) == digest


def test_unbalanced_quote_selects_nothing():
    assert lifecycle._direct_context_option(
        _request('--task-id="abc-def', "task-status"), {"--task-id"}, digest_only=False) is None


def test_quoted_root_text_is_not_read_as_a_task_option():
    # A quoted root is one operand: its contents must never supply a Task ID.
    request = _request('--root="folder --task-id forged"', "task-status")
    assert lifecycle._direct_context_option(request, {"--task-id"}, digest_only=False) is None


@pytest.mark.parametrize("style", ["separate", "equals"])
def test_direct_init_call_accepts_unquoted_and_quoted_roots(tmp_path, style):
    # The post-init proof is issued only for a direct init of this worktree, so
    # the equals form, the separate form and a quoted Windows path must select
    # the same target.
    plain = tmp_path / "repo"
    spaced = tmp_path / "repo with spaces"
    plain.mkdir()
    spaced.mkdir()
    for root, value in ((plain, str(plain)), (spaced, f'"{spaced}"')):
        argument = f"--root {value}" if style == "separate" else f"--root={value}"
        payload = {"cwd": str(tmp_path), "tool_name": "Bash",
                   "tool_input": {"command": f"thaliris {argument} init"}}
        assert lifecycle._direct_init_call(root, payload), argument


def test_direct_init_call_rejects_another_worktree_target(tmp_path):
    root = tmp_path / "repo"
    other = tmp_path / "other repo"
    root.mkdir()
    other.mkdir()
    payload = {"cwd": str(tmp_path), "tool_name": "Bash",
               "tool_input": {"command": f'thaliris --root="{other}" init'}}
    assert not lifecycle._direct_init_call(root, payload)


def test_direct_init_call_rejects_an_empty_equals_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    payload = {"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": "thaliris --root= init"}}
    assert not lifecycle._direct_init_call(root, payload)
