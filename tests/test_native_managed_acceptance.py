from __future__ import annotations

import hashlib
import json
from pathlib import Path

from thaliris_codex import lifecycle


RECEIPT = Path(__file__).parent / "fixtures" / "codex-0163-alpha10-native-c1-managed-candidate.json"


def test_managed_acceptance_receipt_records_isolated_native_hook_evidence() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert receipt["status"] == "CANDIDATE_HOOKS_DISPATCHED_IN_ISOLATED_NATIVE_HOST"
    assert receipt["cli_version"] == "codex-cli 0.163.0-alpha.10.2"
    assert receipt["cli_sha256"] == "f6dbf48cb70f62649c645f26c87dc9bf84cc36986202dfad8e12fb5b8ca70312"
    assert receipt["native_config_hooks_effective"] is True
    assert receipt["native_hook_discovery"]["handler_count"] == 8
    assert receipt["native_hook_discovery"]["warnings"] == [[]]
    assert receipt["native_hook_discovery"]["errors"] == [[]]
    assert receipt["candidate_hook_trust"]["dispatchable_count"] == 7
    assert set(receipt["candidate_hook_binding"]["observed_events"]) == {
        "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart",
    }
    assert all(field["status"] == "MATCH" for field in
        receipt["candidate_hook_binding"]["actual_native_edge_routing"].values())
    assert all(receipt["reused_session_stale_and_wrong_identity_refusals"].values())
    assert receipt["local_responses_requests"] == 3
    assert receipt["external_model_requests"] == 0
    assert receipt["production_host_activation"] == "UNKNOWN"
    assert receipt["effective_wait_runtime"] == "UNKNOWN"
    assert "C:\\Users\\" not in RECEIPT.read_text(encoding="utf-8")


def test_host_hook_merge_preserves_unknown_bytes_but_emits_supported_root_shape(tmp_path: Path) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    executable = tmp_path / "thaliris.exe"
    executable.write_bytes(b"isolated test executable identity")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    user_hook = {"type": "command", "command": "user-owned-hook", "timeout": 19}

    valid_original = {
        "description": "User-owned fixture",
        "hooks": {"UserPromptSubmit": [{"hooks": [user_hook]}]},
    }
    installed, changed, manual = lifecycle.merge_host_hooks(valid_original, home, executable, digest)

    assert changed is True
    assert manual == []
    assert set(installed) <= {"description", "hooks"}
    assert installed["hooks"]["UserPromptSubmit"][0]["hooks"] == [user_hook]
    assert len(lifecycle.host_hook_spec(home, executable, digest)["hooks"]) == 7

    # The merger must retain caller-owned bytes, although Codex's strict Host
    # parser rejects unknown top-level fields and this object is not installed.
    extension = {"opaque": ["preserve", "exactly"]}
    opaque_original = {**valid_original, "user_owned_extension": extension}
    opaque_merged, _, opaque_manual = lifecycle.merge_host_hooks(
        opaque_original, home, executable, digest,
    )
    assert opaque_manual == []
    assert opaque_merged["user_owned_extension"] == extension
