from __future__ import annotations

import json

from thaliris_codex import model_catalog_config as catalog

SUPPORTED_CLI_VERSION = "codex-cli 0.162.0-alpha.17.2"


def observed_catalog(source="online", extra=False):
    common_next = (
        "- When declaring env vars or script variables, always avoid common system options. "
        "Never repurpose \x60$HOME\x60, \x60$home\x60, or \x60$CODEX_HOME\x60. Instead, use a task-specific variable name."
    )
    multiline_previous = (
        "- For multiline PR descriptions, issue bodies, and comments, prefer a structured tool argument. "
        "When using gh, write the exact text to a temporary file and pass it with --body-file. "
        "Preserve actual newlines and intentional literal escapes."
    )
    escaping_previous = (
        "- Exercise caution when escaping text for exec_command calls - backticks and \x60$()\x60 passed to the "
        "\x60cmd\x60 argument will still execute. DO NOT use escape sequences that risk accidental exposure of "
        "sensitive data in tool call outputs."
    )
    matched = {
        "online": [
            "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-reserve",
            "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "codex-auto-review",
        ],
        "bundled": [
            "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna",
            "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
            "gpt-daybreak-blue-latest", "gpt-daybreak-red-latest", "codex-auto-review",
        ],
    }[source]
    models = []
    for slug in matched:
        previous = multiline_previous if slug in {"gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"} else escaping_previous
        template = previous + "\n" + catalog.TARGET + "\n" + common_next + "\n"
        models.append({"slug": slug, "model_messages": {"instructions_template": template}})
    models.append({"slug": "gpt-5.5", "model_messages": {"instructions_template": "known target-absent template\n"}})
    if extra:
        models.append({"slug": "new-model", "model_messages": {"instructions_template": "new model\n" + catalog.TARGET + "\nend\n"}})
    return json.dumps({"models": models, "metadata": {"keep": True}}).encode()


def bundled_compatible_catalog():
    return observed_catalog("bundled")


def supply(monkeypatch, raw=None):
    monkeypatch.setattr(catalog, "export_upstream", lambda _home, **_kwargs: (raw or observed_catalog(), {"kind": "online", "cli_version": SUPPORTED_CLI_VERSION}))


def without_managed_fragment(contents: bytes, record: dict | None) -> bytes:
    """Remove only the fixture receipt's exact catalog field from comparisons."""
    if not isinstance(record, dict) or not isinstance(record.get("fragment"), str):
        return contents
    fragment = record["fragment"].encode()
    if contents.count(fragment) != 1:
        return contents
    return contents.replace(fragment, b"", 1)
