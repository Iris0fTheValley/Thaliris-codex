from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

import tools.agent_tree_audit as audit_module
from tools.agent_tree_audit import main, make_parsed_file, observed_calls, parse_datetime, run_audit, usage_for


START = "2026-10-08T10:00:00.000Z"
END = "2026-10-08T11:00:00.000Z"


def write_log(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def record(ordinal: int, timestamp: str, kind: str, payload: dict, **extra: dict) -> dict:
    return {"ordinal": ordinal, "timestamp": timestamp, "type": kind, "payload": payload, **extra}


def session_meta(thread_id: str, timestamp: str, **extra: dict) -> dict:
    return record(1, timestamp, "session_meta", {"id": thread_id, "session_id": f"session-{thread_id}", "timestamp": timestamp, **extra})


def usage(thread_id: str, values: dict, ordinal: int, timestamp: str) -> dict:
    return record(
        ordinal,
        timestamp,
        "token_usage_record",
        {"thread_id": thread_id, "turn_id": f"turn-{ordinal}", "thread_token_usage": values},
    )


def counters(input_tokens: int, cached: int, output: int, reasoning: int, total: int | None = None) -> dict:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "reasoning_output_tokens": reasoning,
        "total_tokens": input_tokens + output if total is None else total,
        "cache_write_input_tokens": 0,
    }


def audit_args(root: Path, sessions: Path, end: str = END, annotations: Path | None = None) -> Namespace:
    return Namespace(root=str(root), sessions_dir=str(sessions), from_time=START, until=end, annotations=str(annotations) if annotations else None)


def test_tree_links_by_native_parent_metadata_recursively_and_keeps_orphans_unknown(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    root = write_log(sessions / "root.jsonl", [
        session_meta("root-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {"type": "message", "role": "user", "content": [{"text": "PRIVATE_PROMPT"}]}),
    ])
    child = write_log(sessions / "child.jsonl", [
        session_meta("child-id", "2026-10-08T10:02:00.000Z", parent_thread_id="root-id", source={"subagent": {"thread_spawn": {"parent_thread_id": "root-id"}}}, agent_role="ordinary"),
    ])
    grandchild = write_log(sessions / "grandchild.jsonl", [
        session_meta("grandchild-id", "2026-10-08T10:03:00.000Z", source={"subagent": {"thread_spawn": {"parent_thread_id": "child-id"}}}, agent_role="reviewer"),
    ])
    write_log(sessions / "orphan.jsonl", [session_meta("orphan-id", "2026-10-08T10:04:00.000Z", agent_role="ordinary")])
    write_log(sessions / "conflict.jsonl", [
        session_meta("conflict-id", "2026-10-08T10:05:00.000Z", parent_thread_id="root-id", source={"subagent": {"thread_spawn": {"parent_thread_id": "other-parent"}}}),
    ])
    write_log(sessions / "future.jsonl", [
        session_meta("future-id", END, parent_thread_id="root-id", agent_role="ordinary"),
    ])

    report = run_audit(audit_args(root, sessions))

    assert [row["thread_alias"] for row in report["threads"]] == ["root", "agent-001", "agent-002"]
    assert report["threads"][1]["role"] == "ordinary"
    assert report["threads"][1]["child_aliases"] == ["agent-002"]
    assert report["threads"][2]["parent_alias"] == "agent-001"
    assert report["threads"][0]["role"] == "unknown"
    assert report["tree_coverage"]["unassociated_candidate_files"] == 2
    assert report["tree_coverage"]["candidate_parent_conflict"] == 1
    assert report["tree_coverage"]["candidates_excluded_after_window"] == 1
    assert report["threads"][0]["user_message_record_count"] == 1
    assert report["threads"][0]["token_usage"]["status"] == "unknown"
    assert "no_cumulative_snapshot" in report["threads"][0]["token_usage"]["window_increment"]["reasons"]
    assert "PRIVATE_PROMPT" not in json.dumps(report)
    assert str(root) not in json.dumps(report)
    assert str(child) not in json.dumps(report)
    assert str(grandchild) not in json.dumps(report)


def test_selected_root_anchor_and_duplicate_nonroot_identities_stay_unresolved(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    root = write_log(sessions / "root.jsonl", [session_meta("root-id", START)])
    write_log(sessions / "root-collision.jsonl", [
        session_meta("root-id", "2026-10-08T10:01:00.000Z", parent_thread_id="root-id"),
    ])
    write_log(sessions / "duplicate-a.jsonl", [
        session_meta("duplicate-id", "2026-10-08T10:02:00.000Z", parent_thread_id="root-id"),
    ])
    write_log(sessions / "duplicate-b.jsonl", [
        session_meta("duplicate-id", "2026-10-08T10:03:00.000Z", parent_thread_id="root-id"),
    ])
    write_log(sessions / "descendant.jsonl", [
        session_meta("descendant-id", "2026-10-08T10:04:00.000Z", parent_thread_id="duplicate-id"),
    ])
    write_log(sessions / "missing-parent.jsonl", [
        session_meta("orphan-id", "2026-10-08T10:05:00.000Z"),
    ])
    write_log(sessions / "unknown-parent.jsonl", [
        session_meta("unknown-parent-id", "2026-10-08T10:06:00.000Z", parent_thread_id="absent-id"),
    ])

    report = run_audit(audit_args(root, sessions))
    coverage = report["tree_coverage"]

    assert [row["thread_alias"] for row in report["threads"]] == ["root"]
    assert report["threads"][0]["child_aliases"] == []
    assert coverage["selected_root_identity_conflict"] == 1
    assert coverage["duplicate_thread_id_groups"] == 2
    assert coverage["duplicate_thread_id_candidate_files"] == 3
    assert coverage["candidate_identity_conflict_files"] == 3
    assert coverage["candidate_parent_identity_ambiguous"] == 4
    assert coverage["candidate_parent_self_reference"] == 1
    assert coverage["candidate_parent_missing"] == 1
    assert coverage["unassociated_candidate_files"] == 6


def test_cumulative_usage_deduplicates_token_count_and_keeps_reasoning_as_output_subset(tmp_path: Path) -> None:
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", START),
        usage("root-id", counters(50, 40, 10, 3), 2, "2026-10-08T10:01:00.000Z"),
        usage("root-id", counters(100, 70, 20, 5), 3, "2026-10-08T10:02:00.000Z"),
        record(4, "2026-10-08T10:02:00.001Z", "event_msg", {
            "type": "token_count",
            "thread_id": "root-id",
            "info": {"total_token_usage": counters(100, 70, 20, 5), "last_token_usage": counters(100, 70, 20, 5)},
        }),
    ])
    session = make_parsed_file(root, None, None)
    report = usage_for(session)

    assert report["status"] == "observed"
    assert report["token_usage_record_snapshots"]["snapshot_count"] == 2
    assert report["event_total_snapshots"]["snapshot_count"] == 1
    assert report["metrics"] == {
        "input_tokens": 100,
        "cached_input_tokens": 70,
        "noncached_input_tokens": 30,
        "output_tokens": 20,
        "reasoning_output_tokens": 5,
        "total_tokens": 120,
    }
    assert report["metrics_scope"] == "thread_cumulative_as_of_window_end"
    assert report["thread_cumulative_as_of_window_end"]["metrics"] == report["metrics"]
    assert report["window_increment"]["status"] == "observed"
    assert report["window_increment"]["metrics"] == report["metrics"]



@pytest.mark.parametrize(
    ("event_thread_id", "include_event_thread_id", "expected_status", "expected_verified"),
    [
        (None, False, "observed", True),
        ("root-id", True, "observed", True),
        ("foreign-id", True, "unknown", False),
    ],
)
def test_token_count_identity_uses_file_anchor_only_when_event_id_is_omitted(
    tmp_path: Path,
    event_thread_id: str | None,
    include_event_thread_id: bool,
    expected_status: str,
    expected_verified: bool,
) -> None:
    event_payload = {
        "type": "token_count",
        "info": {"total_token_usage": counters(100, 70, 20, 5)},
    }
    if include_event_thread_id:
        event_payload["thread_id"] = event_thread_id
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", START),
        usage("root-id", counters(100, 70, 20, 5), 2, "2026-10-08T10:01:00.000Z"),
        record(3, "2026-10-08T10:01:00.001Z", "event_msg", event_payload),
    ])

    report = usage_for(make_parsed_file(root, None, None))

    assert report["status"] == expected_status
    assert report["thread_identity_verified"] is expected_verified
    if expected_status == "observed":
        assert report["event_total_snapshots"]["status"] == "observed"
        assert report["metrics"]["total_tokens"] == 120
    else:
        assert "usage_thread_identity_mismatch" in report["reasons"]
        assert report["metrics"] is None
        assert report["window_increment"]["metrics"] is None


@pytest.mark.parametrize("event_thread_id", [None, 7, True, [], {}, ""])
def test_token_count_explicit_malformed_identity_is_unverified_and_withholds_metrics(
    tmp_path: Path, event_thread_id,
) -> None:
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", START),
        usage("root-id", counters(100, 70, 20, 5), 2, "2026-10-08T10:01:00.000Z"),
        record(3, "2026-10-08T10:01:00.001Z", "event_msg", {
            "type": "token_count",
            "thread_id": event_thread_id,
            "info": {"total_token_usage": counters(100, 70, 20, 5)},
        }),
    ])

    report = usage_for(make_parsed_file(root, None, None))

    assert report["status"] == "unknown"
    assert report["thread_identity_verified"] is False
    assert "usage_thread_identity_mismatch" in report["reasons"]
    assert report["metrics"] is None
    assert report["window_increment"]["status"] == "unknown"
    assert report["window_increment"]["metrics"] is None


@pytest.mark.parametrize("record_thread_id", ["missing", None, 7, True, [], {}, ""])
def test_token_usage_record_requires_a_matching_string_identity_and_withholds_metrics(
    tmp_path: Path, record_thread_id,
) -> None:
    payload = {
        "turn_id": "turn-2",
        "thread_token_usage": counters(100, 70, 20, 5),
    }
    if record_thread_id != "missing":
        payload["thread_id"] = record_thread_id
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "token_usage_record", payload),
    ])

    report = usage_for(make_parsed_file(root, None, None))

    assert report["status"] == "unknown"
    assert report["thread_identity_verified"] is False
    assert "usage_thread_identity_mismatch" in report["reasons"]
    assert report["metrics"] is None
    assert report["window_increment"]["status"] == "unknown"
    assert report["window_increment"]["metrics"] is None

def test_explicit_window_increment_uses_pre_window_baseline_and_excludes_cutoff_records(tmp_path: Path) -> None:
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        usage("root-id", counters(100, 70, 20, 5), 2, "2026-10-08T09:59:00.000Z"),
        usage("root-id", counters(110, 76, 24, 6), 3, "2026-10-08T10:30:00.000Z"),
        usage("root-id", counters(150, 100, 30, 8), 4, END),
    ])
    session = make_parsed_file(root, parse_datetime(START), parse_datetime(END))

    report = usage_for(session, parse_datetime(START), parse_datetime(END), explicit_start=True)

    assert report["status"] == "observed"
    assert report["metrics"]["total_tokens"] == 134
    assert report["window_increment"]["status"] == "observed"
    assert report["window_increment"]["metrics"] == {
        "input_tokens": 10,
        "cached_input_tokens": 6,
        "noncached_input_tokens": 4,
        "output_tokens": 4,
        "reasoning_output_tokens": 1,
        "total_tokens": 14,
    }
    assert report["window_increment"]["baseline_at"] == "2026-10-08T09:59:00.000Z"
    assert report["window_increment"]["latest_snapshot_at"] == "2026-10-08T10:30:00.000Z"


def test_equal_timestamp_usage_snapshots_use_native_ordinal_for_latest_delta(tmp_path: Path) -> None:
    explicit = write_log(tmp_path / "explicit-tie.jsonl", [
        session_meta("explicit-tie-id", "2026-10-08T09:00:00.000Z"),
        usage("explicit-tie-id", counters(5, 2, 0, 0), 2, "2026-10-08T09:59:00.000Z"),
        usage("explicit-tie-id", counters(10, 5, 0, 0), 3, "2026-10-08T10:30:00.000Z"),
        usage("explicit-tie-id", counters(20, 8, 0, 0), 4, "2026-10-08T10:30:00.000Z"),
    ])
    explicit_report = usage_for(
        make_parsed_file(explicit, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START),
        parse_datetime(END),
        explicit_start=True,
    )
    assert explicit_report["metrics"]["total_tokens"] == 20
    assert explicit_report["window_increment"]["metrics"]["total_tokens"] == 15

    created_in_window = write_log(tmp_path / "creation-tie.jsonl", [
        session_meta("creation-tie-id", START),
        usage("creation-tie-id", counters(10, 5, 0, 0), 2, "2026-10-08T10:30:00.000Z"),
        usage("creation-tie-id", counters(20, 8, 0, 0), 3, "2026-10-08T10:30:00.000Z"),
    ])
    created_report = usage_for(
        make_parsed_file(created_in_window, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START),
        parse_datetime(END),
        explicit_start=True,
    )
    assert created_report["window_increment"]["metrics"]["total_tokens"] == 20
    assert created_report["window_increment"]["latest_snapshot_at"] == "2026-10-08T10:30:00.000Z"


def test_cross_source_native_ordinal_conflict_taints_both_usage_scopes(tmp_path: Path) -> None:
    root = write_log(tmp_path / "cross-source-ordinal-conflict.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        usage("root-id", counters(5, 0, 0, 0), 2, "2026-10-08T09:58:00.000Z"),
        record(3, "2026-10-08T09:59:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(5, 0, 0, 0)},
        }),
        usage("root-id", counters(20, 0, 0, 0), 5, "2026-10-08T10:30:00.000Z"),
        record(4, "2026-10-08T10:30:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(20, 0, 0, 0)},
        }),
    ])
    report = usage_for(
        make_parsed_file(root, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START), parse_datetime(END), explicit_start=True,
    )

    assert report["status"] == report["window_increment"]["status"] == "unknown"
    assert report["metrics"] is report["window_increment"]["metrics"] is None
    assert "snapshot_native_ordinal_out_of_order" in report["reasons"]
    assert "snapshot_native_ordinal_out_of_order" in report["window_increment"]["reasons"]


def test_cross_source_timestamp_conflict_taints_both_usage_scopes(tmp_path: Path) -> None:
    root = write_log(tmp_path / "cross-source-timestamp-conflict.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        usage("root-id", counters(5, 0, 0, 0), 2, "2026-10-08T09:58:00.000Z"),
        record(3, "2026-10-08T09:59:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(5, 0, 0, 0)},
        }),
        usage("root-id", counters(20, 0, 0, 0), 4, "2026-10-08T10:30:00.000Z"),
        record(5, "2026-10-08T10:29:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(20, 0, 0, 0)},
        }),
    ])
    report = usage_for(
        make_parsed_file(root, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START), parse_datetime(END), explicit_start=True,
    )

    assert report["status"] == report["window_increment"]["status"] == "unknown"
    assert report["metrics"] is report["window_increment"]["metrics"] is None
    assert "snapshot_time_out_of_order" in report["reasons"]
    assert "snapshot_time_out_of_order" in report["window_increment"]["reasons"]


def test_cross_source_legal_interleaving_remains_observed(tmp_path: Path) -> None:
    root = write_log(tmp_path / "cross-source-legal-interleaving.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        usage("root-id", counters(5, 0, 0, 0), 2, "2026-10-08T09:59:00.000Z"),
        record(3, "2026-10-08T09:59:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(5, 0, 0, 0)},
        }),
        usage("root-id", counters(20, 0, 0, 0), 4, "2026-10-08T10:30:00.000Z"),
        record(5, "2026-10-08T10:30:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(20, 0, 0, 0)},
        }),
    ])
    report = usage_for(
        make_parsed_file(root, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START), parse_datetime(END), explicit_start=True,
    )

    assert report["status"] == report["window_increment"]["status"] == "observed"
    assert report["metrics"]["total_tokens"] == 20
    assert report["window_increment"]["metrics"]["total_tokens"] == 15


def test_cross_source_order_conflict_at_excluded_cutoff_does_not_taint_usage(tmp_path: Path) -> None:
    root = write_log(tmp_path / "cross-source-cutoff-conflict.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        usage("root-id", counters(5, 0, 0, 0), 2, "2026-10-08T09:59:00.000Z"),
        record(3, "2026-10-08T09:59:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(5, 0, 0, 0)},
        }),
        usage("root-id", counters(20, 0, 0, 0), 4, "2026-10-08T10:30:00.000Z"),
        record(5, "2026-10-08T10:30:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(20, 0, 0, 0)},
        }),
        usage("root-id", counters(999, 0, 0, 0), 7, END),
        record(6, END, "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(999, 0, 0, 0)},
        }),
    ])
    report = usage_for(
        make_parsed_file(root, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START), parse_datetime(END), explicit_start=True,
    )

    assert report["status"] == report["window_increment"]["status"] == "observed"
    assert report["metrics"]["total_tokens"] == 20
    assert report["window_increment"]["metrics"]["total_tokens"] == 15


@pytest.mark.parametrize("source", ["token_usage_record", "event_msg"])
def test_conflicting_file_and_native_usage_order_taints_both_scopes(tmp_path: Path, source: str) -> None:
    def snapshot(ordinal: int, value: int, stamp: str) -> dict:
        if source == "token_usage_record":
            return usage("root-id", counters(value, 0, 0, 0), ordinal, stamp)
        return record(ordinal, stamp, source, {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(value, 0, 0, 0)},
        })

    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        snapshot(2, 5, "2026-10-08T09:59:00.000Z"),
        snapshot(4, 10, "2026-10-08T10:30:00.000Z"),
        snapshot(3, 20, "2026-10-08T10:30:00.000Z"),
    ])
    report = usage_for(make_parsed_file(root, parse_datetime(START), parse_datetime(END)),
                       parse_datetime(START), parse_datetime(END), explicit_start=True)

    assert report["status"] == "unknown"
    assert report["metrics"] is None
    assert report["window_increment"]["status"] == "unknown"
    assert report["window_increment"]["metrics"] is None
    assert "snapshot_native_ordinal_out_of_order" in report["reasons"]
    assert "snapshot_native_ordinal_out_of_order" in report["window_increment"]["reasons"]


@pytest.mark.parametrize("bad_ordinal", [None, True, -1, "3", {}, 2])
def test_usage_missing_invalid_or_duplicate_native_ordinal_never_supplies_chronology(tmp_path: Path, bad_ordinal) -> None:
    last = usage("root-id", counters(20, 0, 0, 0), bad_ordinal, "2026-10-08T10:30:00.000Z")
    if bad_ordinal is None:
        last.pop("ordinal")
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", START),
        usage("root-id", counters(10, 0, 0, 0), 2, "2026-10-08T10:20:00.000Z"),
        last,
    ])
    report = usage_for(make_parsed_file(root, None, None))
    assert report["status"] == report["window_increment"]["status"] == "unknown"
    assert report["metrics"] is report["window_increment"]["metrics"] is None
    expected = "snapshot_native_ordinal_duplicate" if bad_ordinal == 2 else "snapshot_native_ordinal_unavailable"
    assert expected in report["reasons"]


def test_cross_source_duplicate_ordinal_is_unknown_but_distinct_repeated_snapshots_are_observed(tmp_path: Path) -> None:
    records = [
        session_meta("root-id", START),
        usage("root-id", counters(10, 0, 0, 0), 2, "2026-10-08T10:20:00.000Z"),
        record(2, "2026-10-08T10:20:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "root-id",
            "info": {"total_token_usage": counters(10, 0, 0, 0)},
        }),
    ]
    path = write_log(tmp_path / "duplicate.jsonl", records)
    duplicate = usage_for(make_parsed_file(path, None, None))
    assert duplicate["status"] == duplicate["window_increment"]["status"] == "unknown"
    assert "snapshot_native_ordinal_duplicate" in duplicate["reasons"]

    records[-1]["ordinal"] = 3
    records.append(usage("root-id", counters(10, 0, 0, 0), 4, "2026-10-08T10:20:00.000Z"))
    records.append(usage("root-id", counters(999, 0, 0, 0), 4, END))
    path = write_log(tmp_path / "valid.jsonl", records)
    valid = usage_for(make_parsed_file(path, None, parse_datetime(END)), end=parse_datetime(END))
    assert valid["status"] == valid["window_increment"]["status"] == "observed"
    assert valid["metrics"]["total_tokens"] == valid["window_increment"]["metrics"]["total_tokens"] == 10


def test_until_only_and_unbounded_audits_report_thread_lifetime_cumulative_scope(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    root = write_log(sessions / "root.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        usage("root-id", counters(100, 70, 20, 5), 2, "2026-10-08T09:59:00.000Z"),
        usage("root-id", counters(110, 76, 24, 6), 3, "2026-10-08T10:30:00.000Z"),
        usage("root-id", counters(150, 100, 30, 8), 4, END),
    ])
    args = Namespace(
        root=str(root), sessions_dir=str(sessions), from_time=None, until=END, annotations=None,
    )

    report = run_audit(args)
    token_usage = report["threads"][0]["token_usage"]

    assert report["window"]["root_header_start_used_when_from_omitted"] is True
    assert token_usage["metrics"]["total_tokens"] == 134
    assert token_usage["window_increment"]["metrics"]["total_tokens"] == 134
    assert token_usage["window_increment"]["baseline_scope"] == "native_thread_creation_zero"
    assert token_usage["metrics_scope"] == "thread_cumulative_as_of_window_end"


def test_window_increment_requires_baseline_unless_native_creation_proves_zero(tmp_path: Path) -> None:
    no_anchor = write_log(tmp_path / "no-anchor.jsonl", [
        session_meta("old-id", "2026-10-08T09:00:00.000Z"),
        usage("old-id", counters(20, 10, 5, 1), 2, "2026-10-08T10:30:00.000Z"),
    ])
    no_anchor_report = usage_for(
        make_parsed_file(no_anchor, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START),
        parse_datetime(END),
        explicit_start=True,
    )
    assert no_anchor_report["status"] == "observed"
    assert no_anchor_report["window_increment"]["status"] == "unknown"
    assert "no_reliable_baseline_at_window_start" in no_anchor_report["window_increment"]["reasons"]

    new_thread = write_log(tmp_path / "new-thread.jsonl", [
        session_meta("new-id", "2026-10-08T10:15:00.000Z"),
        usage("new-id", counters(20, 10, 5, 1), 2, "2026-10-08T10:30:00.000Z"),
    ])
    new_thread_report = usage_for(
        make_parsed_file(new_thread, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START),
        parse_datetime(END),
        explicit_start=True,
    )
    assert new_thread_report["window_increment"]["status"] == "observed"
    assert new_thread_report["window_increment"]["baseline_scope"] == "native_thread_creation_zero"
    assert new_thread_report["window_increment"]["metrics"]["total_tokens"] == 25


def test_window_increment_rejects_invalid_subset_deltas(tmp_path: Path) -> None:
    cases = [
        (counters(100, 50, 20, 5), counters(101, 52, 20, 5), "window_delta_cached_input_exceeds_input"),
        (counters(100, 50, 20, 5), counters(100, 50, 21, 7), "window_delta_reasoning_exceeds_output"),
    ]
    for index, (baseline, latest, expected_reason) in enumerate(cases):
        path = write_log(tmp_path / f"invalid-delta-{index}.jsonl", [
            session_meta(f"delta-{index}", "2026-10-08T09:00:00.000Z"),
            usage(f"delta-{index}", baseline, 2, "2026-10-08T09:59:00.000Z"),
            usage(f"delta-{index}", latest, 3, "2026-10-08T10:30:00.000Z"),
        ])
        report = usage_for(
            make_parsed_file(path, parse_datetime(START), parse_datetime(END)),
            parse_datetime(START),
            parse_datetime(END),
            explicit_start=True,
        )
        assert report["status"] == "observed"
        assert report["window_increment"]["status"] == "unknown"
        assert expected_reason in report["window_increment"]["reasons"]


def test_cumulative_source_conflict_taints_equal_window_deltas(tmp_path: Path) -> None:
    path = write_log(tmp_path / "offset-conflict.jsonl", [
        session_meta("offset-id", "2026-10-08T09:00:00.000Z"),
        usage("offset-id", counters(100, 0, 0, 0), 2, "2026-10-08T09:59:00.000Z"),
        record(3, "2026-10-08T09:59:00.001Z", "event_msg", {
            "type": "token_count", "thread_id": "offset-id",
            "info": {"total_token_usage": counters(200, 0, 0, 0)},
        }),
        usage("offset-id", counters(110, 0, 0, 0), 4, "2026-10-08T10:30:00.000Z"),
        record(5, "2026-10-08T10:30:00.001Z", "event_msg", {
            "type": "token_count", "thread_id": "offset-id",
            "info": {"total_token_usage": counters(210, 0, 0, 0)},
        }),
    ])
    report = usage_for(
        make_parsed_file(path, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START),
        parse_datetime(END),
        explicit_start=True,
    )

    assert report["status"] == "unknown"
    assert report["window_increment"]["status"] == "unknown"
    assert "cumulative_sources_disagree" in report["window_increment"]["reasons"]


def test_incomplete_usage_payload_and_unparseable_jsonl_taint_usage(tmp_path: Path) -> None:
    null_payload = write_log(tmp_path / "null-payload.jsonl", [
        session_meta("null-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "token_usage_record", None),
        usage("null-id", counters(10, 5, 3, 1), 3, "2026-10-08T10:02:00.000Z"),
    ])
    null_report = usage_for(
        make_parsed_file(null_payload, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START),
        parse_datetime(END),
        explicit_start=True,
    )
    assert null_report["status"] == "unknown"
    assert "usage_payload_missing" in null_report["token_usage_record_snapshots"]["reasons"]

    truncated = write_log(tmp_path / "truncated-usage.jsonl", [
        session_meta("truncated-id", "2026-10-08T09:00:00.000Z"),
        usage("truncated-id", counters(10, 5, 3, 1), 2, "2026-10-08T10:02:00.000Z"),
    ])
    with truncated.open("a", encoding="utf-8") as stream:
        stream.write('{"type":"token_usage_record","payload":')
    truncated_report = usage_for(
        make_parsed_file(truncated, parse_datetime(START), parse_datetime(END)),
        parse_datetime(START),
        parse_datetime(END),
        explicit_start=True,
    )
    assert truncated_report["status"] == "unknown"
    assert truncated_report["metrics"] is None
    assert "unparseable_session_record" in truncated_report["reasons"]
    assert truncated_report["window_increment"]["status"] == "unknown"
    assert "unparseable_session_record" in truncated_report["window_increment"]["reasons"]


def test_unknown_native_types_and_annotation_ids_are_sanitized_in_json_and_table(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    secret_type = "sk-secretcredential-C:\\Users\\private\\session\u0001"
    root = write_log(sessions / "root.jsonl", [
        session_meta("root-id", START),
        record(2, "2026-10-08T10:01:00.000Z", secret_type, {"text": "PRIVATE_PAYLOAD"}),
        record(3, "2026-10-08T10:02:00.000Z", "event_msg", {"type": secret_type}),
        record(4, "2026-10-08T10:03:00.000Z", {"raw": secret_type}, {"text": "PRIVATE_PAYLOAD_2"}),
        record(5, "2026-10-08T10:04:00.000Z", "event_msg", {"type": [secret_type]}),
    ])
    baseline = run_audit(audit_args(root, sessions))
    source_sha = baseline["threads"][0]["window_sha256"]
    annotation_path = tmp_path / "annotations.jsonl"
    annotations = [
        {
            "thread_alias": "root", "source_sha256": source_sha, "ordinal": 2,
            "kind": "acceptance", "label": "safe label", "decision": "accepted", "source_ref": "review-note",
        },
        {
            "thread_alias": "root", "source_sha256": source_sha, "ordinal": 3,
            "kind": "necessary_test", "label": "safe label", "decision": "accepted", "source_ref": "review-note",
            "related_workstream_ids": ["sk-secretcredential"],
        },
        {
            "thread_alias": "root", "source_sha256": source_sha, "ordinal": 3,
            "kind": "workstream", "label": "safe label", "decision": "accepted", "source_ref": "review-note",
            "workstream_id": "sk-secretcredential",
        },
        {
            "thread_alias": "root", "source_sha256": source_sha, "ordinal": 3,
            "kind": "acceptance", "label": "safe label", "decision": "accepted", "source_ref": "sk-secretcredential",
        },
        {
            "thread_alias": "root", "source_sha256": source_sha, "ordinal": 3,
            "kind": "acceptance", "label": "sk-secretcredential", "decision": "accepted", "source_ref": "review-note",
        },
    ]
    annotation_path.write_text("".join(json.dumps(item) + "\n" for item in annotations), encoding="utf-8")

    args = audit_args(root, sessions, annotations=annotation_path)
    report = run_audit(args)

    serialized = json.dumps(report)
    assert secret_type not in serialized
    assert "PRIVATE_PAYLOAD" not in serialized
    assert "PRIVATE_PAYLOAD_2" not in serialized
    assert report["threads"][0]["record_type_counts"]["unknown"] == 2
    assert report["threads"][0]["native_event_type_counts"]["unknown"] == 2
    assert report["annotations"]["bound"] == 1
    assert report["annotations"]["unmatched_or_invalid"] == 4
    assert report["threads"][0]["annotations"][0]["record_type"] == "unknown"

    for output_format in ("json", "table"):
        assert main([
            "--root", str(root), "--sessions-dir", str(sessions), "--from", START,
            "--until", END, "--annotations", str(annotation_path), "--format", output_format,
        ]) == 0
        output = capsys.readouterr().out
        assert secret_type not in output
        assert "PRIVATE_PAYLOAD" not in output
        assert "PRIVATE_PAYLOAD_2" not in output
        assert str(root) not in output


def test_malformed_response_item_schema_is_bucketed_without_cli_traceback(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    root = write_log(sessions / "root.jsonl", [
        session_meta("root-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {"type": ["function_call"], "call_id": "PRIVATE_CALL_ID"}),
        record(3, "2026-10-08T10:02:00.000Z", "response_item", {"type": {"raw": "PRIVATE_TYPE"}, "call_id": "other-private-id"}),
        record(4, "2026-10-08T10:03:00.000Z", "response_item", ["PRIVATE_PAYLOAD"]),
        record(5, "2026-10-08T10:04:00.000Z", "response_item", {
            "type": "function_call", "call_id": ["PRIVATE_BAD_ID"], "name": "wait_agent", "arguments": "{}",
        }),
        record(6, "2026-10-08T10:05:00.000Z", "response_item", {
            "type": "function_call", "call_id": "duplicate-malformed", "name": "wait_agent", "arguments": "{}",
        }),
        record(7, "2026-10-08T10:06:00.000Z", "response_item", {
            "type": ["future_native_type"], "call_id": "duplicate-malformed",
        }),
        record(8, "2026-10-08T10:07:00.000Z", "response_item", {
            "type": "function_call_output", "call_id": "duplicate-malformed", "output": json.dumps({"timed_out": False}),
        }),
    ])

    assert main([
        "--root", str(root), "--sessions-dir", str(sessions), "--from", START,
        "--until", END, "--format", "json",
    ]) == 0
    output = capsys.readouterr().out
    calls = json.loads(output)["threads"][0]["calls"]
    assert calls["unclassified_response_item_count"] == 4
    assert calls["started_call_count"] == 2
    assert calls["ambiguous_call_id_count"] == 1
    assert calls["result_observed_count"] == 0
    assert calls["unfinished_or_ambiguous_count"] == 2
    for private_value in ("PRIVATE_CALL_ID", "PRIVATE_TYPE", "PRIVATE_PAYLOAD", "PRIVATE_BAD_ID"):
        assert private_value not in output
    assert "Traceback" not in output


@pytest.mark.parametrize("unknown_kind", ["", "PRIVATE_UNKNOWN_SUBTYPE_sk-123456789", None, [], {}])
@pytest.mark.parametrize("conflict_in_window", [True, False])
def test_unclassified_response_item_id_conflicts_agree_across_call_wait_and_record_coverage(
    tmp_path: Path, unknown_kind, conflict_in_window: bool,
) -> None:
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", "2026-10-08T09:00:00.000Z"),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "good", "arguments": "{}",
        }),
        record(3, "2026-10-08T10:01:01.000Z", "response_item", {
            "type": "function_call_output", "call_id": "good", "output": json.dumps({"timed_out": False}),
        }),
        record(4, "2026-10-08T10:02:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "conflict", "arguments": "{}",
        }),
        record(5, "2026-10-08T10:02:01.000Z", "response_item", {
            "type": "function_call_output", "call_id": "conflict", "output": json.dumps({"timed_out": False}),
        }),
        record(6, "2026-10-08T10:03:00.000Z" if conflict_in_window else END, "response_item", {
            "type": unknown_kind, "call_id": "conflict", "payload": "PRIVATE_PAYLOAD",
        }),
        record(7, "2026-10-08T10:04:00.000Z", "response_item", {
            "type": "message", "role": "assistant", "content": "PRIVATE_MESSAGE",
        }),
    ])
    report = run_audit(audit_args(root, tmp_path))
    calls = report["threads"][0]["calls"]
    waits = calls["native_waits"]

    assert calls["unclassified_response_item_count"] == int(conflict_in_window)
    assert calls["ambiguous_call_id_count"] == waits["ambiguous_call_id_count"] == 1
    assert calls["result_observed_count"] == waits["results_observed"] == 1
    assert calls["unfinished_or_ambiguous_count"] == waits["unpaired_or_ambiguous_call_records"] == 1
    assert calls["observed_result_records"] == waits["result_records_for_wait_call_ids"] == 2
    assert calls["unmatched_or_ambiguous_result_record_count"] == waits["unmatched_or_ambiguous_result_records"] == 1
    assert waits["completed_without_timeout_observed"] == 1
    assert waits["outcome_unknown_or_unfinished"] == 1
    assert waits["elapsed_ms_observed"]["count"] == 1
    assert calls["result_record_coverage_conserves"] is True
    assert waits["result_record_coverage_conserves"] is True
    assert waits["call_record_coverage_conserves"] is True
    rendered = json.dumps(report)
    for private_value in ("PRIVATE_UNKNOWN_SUBTYPE", "PRIVATE_PAYLOAD", "PRIVATE_MESSAGE"):
        assert private_value not in rendered


def test_cli_unexpected_parse_failure_does_not_print_exception_or_path(tmp_path: Path, capsys, monkeypatch) -> None:
    private_path = tmp_path / "private" / "session.jsonl"

    def fail_with_private_details(_args):
        raise RuntimeError(f"parse failed at {private_path}: private payload")

    monkeypatch.setattr(audit_module, "run_audit", fail_with_private_details)
    assert main(["--root", str(private_path), "--sessions-dir", str(tmp_path), "--format", "json"]) == 2
    error = capsys.readouterr().err
    assert error == "audit failed: unexpected data or processing error\n"
    assert str(private_path) not in error
    assert "private payload" not in error
    assert "Traceback" not in error


def test_duplicate_unpaired_and_conflicting_wait_call_ids_conserve_wait_records(tmp_path: Path) -> None:
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "duplicate-wait", "arguments": "{}",
        }),
        record(3, "2026-10-08T10:01:01.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "duplicate-wait", "arguments": "{}",
        }),
        record(4, "2026-10-08T10:01:02.000Z", "response_item", {
            "type": "function_call_output", "call_id": "duplicate-wait", "output": json.dumps({"timed_out": False}),
        }),
        record(5, "2026-10-08T10:02:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_threads", "call_id": "conflicting-wait", "arguments": "{}",
        }),
        record(6, "2026-10-08T10:02:01.000Z", "response_item", {
            "type": "function_call_output", "call_id": "conflicting-wait", "output": json.dumps({"timed_out": True}),
        }),
        record(7, "2026-10-08T10:02:02.000Z", "response_item", {
            "type": "function_call_output", "call_id": "conflicting-wait", "output": json.dumps({"timed_out": False}),
        }),
        record(8, "2026-10-08T10:03:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "unpaired-wait", "arguments": "{}",
        }),
        record(9, "2026-10-08T10:04:00.000Z", "response_item", {
            "type": "function_call_output", "call_id": "orphan-output", "output": "{}",
        }),
    ])

    waits = run_audit(audit_args(root, tmp_path))["threads"][0]["calls"]["native_waits"]

    assert waits["call_count"] == 4
    assert waits["unique_call_id_count"] == 3
    assert waits["ambiguous_call_id_count"] == 2
    assert waits["calls_with_unique_result"] == 0
    assert waits["unpaired_or_ambiguous_call_records"] == 4
    assert waits["results_observed"] == 0
    assert waits["timed_out_observed"] == 0
    assert waits["completed_without_timeout_observed"] == 0
    assert waits["outcome_unknown_or_unfinished"] == 4
    assert waits["call_record_coverage_conserves"] is True
    assert waits["result_records_for_wait_call_ids"] == 3
    assert waits["unmatched_or_ambiguous_result_records"] == 3
    calls = run_audit(audit_args(root, tmp_path))["threads"][0]["calls"]
    assert calls["unmatched_or_ambiguous_result_record_count"] == 4
    assert calls["result_record_coverage_conserves"] is True


def test_wait_pairing_uses_whole_thread_identity_and_chronology(tmp_path: Path) -> None:
    duplicate = write_log(tmp_path / "duplicate-before-window.jsonl", [
        session_meta("duplicate-before-id", "2026-10-08T09:00:00.000Z"),
        record(2, "2026-10-08T09:59:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "same-id", "arguments": "{}",
        }),
        record(3, "2026-10-08T10:01:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "same-id", "arguments": "{}",
        }),
        record(4, "2026-10-08T10:02:00.000Z", "response_item", {
            "type": "function_call_output", "call_id": "same-id", "output": json.dumps({"timed_out": False}),
        }),
    ])
    duplicate_waits = run_audit(audit_args(duplicate, tmp_path))["threads"][0]["calls"]["native_waits"]
    assert duplicate_waits["call_count"] == 1
    assert duplicate_waits["ambiguous_call_id_count"] == 1
    assert duplicate_waits["calls_with_unique_result"] == 0
    assert duplicate_waits["completed_without_timeout_observed"] == 0
    assert duplicate_waits["outcome_unknown_or_unfinished"] == 1
    assert duplicate_waits["call_record_coverage_conserves"] is True

    cross_window = write_log(tmp_path / "cross-window-result.jsonl", [
        session_meta("cross-window-id", "2026-10-08T09:00:00.000Z"),
        record(2, "2026-10-08T10:59:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "cross-window", "arguments": "{}",
        }),
        record(3, END, "response_item", {
            "type": "function_call_output", "call_id": "cross-window", "output": json.dumps({"timed_out": False}),
        }),
    ])
    cross_waits = run_audit(audit_args(cross_window, tmp_path))["threads"][0]["calls"]["native_waits"]
    assert cross_waits["call_count"] == 1
    assert cross_waits["calls_with_unique_result"] == 0
    assert cross_waits["completed_without_timeout_observed"] == 0
    assert cross_waits["outcome_unknown_or_unfinished"] == 1
    assert cross_waits["call_record_coverage_conserves"] is True

    reversed_chronology = write_log(tmp_path / "reversed-wait-result.jsonl", [
        session_meta("reversed-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "reversed", "arguments": "{}",
        }),
        record(3, "2026-10-08T10:00:59.000Z", "response_item", {
            "type": "function_call_output", "call_id": "reversed", "output": json.dumps({"timed_out": False}),
        }),
    ])
    reversed_waits = run_audit(audit_args(reversed_chronology, tmp_path))["threads"][0]["calls"]["native_waits"]
    assert reversed_waits["calls_with_unique_result"] == 0
    assert reversed_waits["completed_without_timeout_observed"] == 0
    assert reversed_waits["outcome_unknown_or_unfinished"] == 1
    assert reversed_waits["elapsed_ms_observed"]["count"] == 0
    assert reversed_waits["call_record_coverage_conserves"] is True


def test_wait_pairing_uses_native_ordinal_for_equal_or_missing_timestamps(tmp_path: Path) -> None:
    same_time_later_ordinal = write_log(tmp_path / "same-time-later-ordinal.jsonl", [
        session_meta("same-time-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "same-time", "arguments": "{}",
        }),
        record(3, "2026-10-08T10:01:00.000Z", "response_item", {
            "type": "function_call_output", "call_id": "same-time", "output": json.dumps({"timed_out": False}),
        }),
    ])
    observed = run_audit(audit_args(same_time_later_ordinal, tmp_path))["threads"][0]["calls"]
    assert observed["result_observed_count"] == 1
    assert observed["elapsed_ms_observed_all_calls"]["min"] == 0
    assert observed["native_waits"]["elapsed_ms_observed"]["min"] == 0
    assert observed["native_waits"]["completed_without_timeout_observed"] == 1

    for name, call_ordinal, result_ordinal, call_time, result_time in (
        ("same-time-earlier-ordinal", 3, 2, "2026-10-08T10:01:00.000Z", "2026-10-08T10:01:00.000Z"),
        ("later-time-earlier-ordinal", 3, 2, "2026-10-08T10:01:00.000Z", "2026-10-08T10:02:00.000Z"),
        ("missing-call-ordinal", None, 3, "2026-10-08T10:01:00.000Z", "2026-10-08T10:02:00.000Z"),
    ):
        call_record = record(call_ordinal or 0, call_time, "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": name, "arguments": "{}",
        })
        if call_ordinal is None:
            call_record.pop("ordinal")
        path = write_log(tmp_path / f"{name}.jsonl", [
            session_meta(f"{name}-id", START),
            call_record,
            record(result_ordinal, result_time, "response_item", {
                "type": "function_call_output", "call_id": name, "output": json.dumps({"timed_out": False}),
            }),
        ])
        calls = run_audit(audit_args(path, tmp_path))["threads"][0]["calls"]
        waits = calls["native_waits"]
        assert calls["result_observed_count"] == 0
        assert waits["outcome_unknown_or_unfinished"] == 1
        assert waits["call_record_coverage_conserves"] is True
        assert calls["result_record_coverage_conserves"] is True

    missing_time = write_log(tmp_path / "missing-time.jsonl", [
        session_meta("missing-time-id", START),
        {"ordinal": 2, "type": "response_item", "payload": {
            "type": "function_call", "name": "wait_agent", "call_id": "missing-time", "arguments": "{}",
        }},
        {"ordinal": 3, "type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "missing-time", "output": json.dumps({"timed_out": False}),
        }},
    ])
    missing_time_calls = observed_calls(make_parsed_file(missing_time, None, None), None, None)
    assert missing_time_calls["result_observed_count"] == 0
    assert missing_time_calls["native_waits"]["outcome_unknown_or_unfinished"] == 1


def test_usage_reset_missing_fields_invalid_subsets_and_source_disagreement_are_unknown(tmp_path: Path) -> None:
    reset = write_log(tmp_path / "reset.jsonl", [
        session_meta("reset-id", START),
        usage("reset-id", counters(100, 50, 20, 5), 2, "2026-10-08T10:01:00.000Z"),
        usage("reset-id", counters(50, 20, 10, 2), 3, "2026-10-08T10:02:00.000Z"),
    ])
    assert usage_for(make_parsed_file(reset, None, None))["status"] == "unknown"
    assert "cumulative_counter_reset_or_out_of_order" in usage_for(make_parsed_file(reset, None, None))["reasons"]
    assert usage_for(make_parsed_file(reset, None, None))["window_increment"]["status"] == "unknown"

    invalid_values = [
        counters(10, 11, 3, 1),
        {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3, "reasoning_output_tokens": 1},
        counters(-1, 0, 1, 0),
        counters(10, 2, 3, 4),
    ]
    for index, values in enumerate(invalid_values):
        path = write_log(tmp_path / f"invalid-{index}.jsonl", [session_meta(f"invalid-{index}", START), usage(f"invalid-{index}", values, 2, "2026-10-08T10:01:00.000Z")])
        assert usage_for(make_parsed_file(path, None, None))["status"] == "unknown"

    disagree = write_log(tmp_path / "disagree.jsonl", [
        session_meta("disagree-id", START),
        usage("disagree-id", counters(100, 50, 20, 5), 2, "2026-10-08T10:01:00.000Z"),
        record(3, "2026-10-08T10:02:00.000Z", "event_msg", {
            "type": "token_count", "thread_id": "disagree-id", "info": {"total_token_usage": counters(90, 50, 20, 5)},
        }),
    ])
    usage_report = usage_for(make_parsed_file(disagree, None, None))
    assert usage_report["status"] == "unknown"
    assert "cumulative_sources_disagree" in usage_report["reasons"]
    assert usage_report["window_increment"]["status"] == "unknown"
    assert "cumulative_sources_disagree" in usage_report["window_increment"]["reasons"]


def test_wait_elapsed_is_observed_separately_from_requested_timeout_and_exec_kind_is_inferred(tmp_path: Path) -> None:
    root = write_log(tmp_path / "root.jsonl", [
        session_meta("root-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {
            "type": "function_call", "name": "wait_agent", "call_id": "wait-1", "arguments": json.dumps({"timeout_ms": 1000, "yield_time_ms": 200}),
        }),
        record(3, "2026-10-08T10:01:00.500Z", "response_item", {
            "type": "function_call_output", "call_id": "wait-1", "output": json.dumps({"timed_out": False}),
        }),
        record(4, "2026-10-08T10:02:00.000Z", "response_item", {
            "type": "custom_tool_call", "name": "exec", "call_id": "exec-1", "input": "python -m pytest tests/example.py",
        }),
        record(5, "2026-10-08T10:02:01.000Z", "response_item", {
            "type": "custom_tool_call_output", "call_id": "exec-1", "output": "ignored output",
        }),
        record(6, "2026-10-08T10:03:00.000Z", "compacted", {"message": "PRIVATE_COMPACTION_TEXT"}),
    ])
    report = run_audit(audit_args(root, tmp_path))
    thread = report["threads"][0]
    waits = thread["calls"]["native_waits"]

    assert waits["call_count"] == 1
    assert waits["requested_timeout_ms_histogram"] == {"1000": 1}
    assert waits["requested_yield_ms_histogram"] == {"200": 1}
    assert waits["elapsed_ms_observed"]["median"] == 500
    assert waits["completed_without_timeout_observed"] == 1
    assert waits["timed_out_observed"] == 0
    assert thread["calls"]["categories"] == [
        {"category": "native_wait", "evidence": "observed", "count": 1},
        {"category": "test", "evidence": "inferred", "count": 1},
    ]
    assert thread["compaction_record_count"] == 1
    assert "PRIVATE_COMPACTION_TEXT" not in json.dumps(report)


def test_report_write_failure_is_sanitized_and_returns_failure(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    root = write_log(sessions / "root.jsonl", [session_meta("root-id", START)])
    destination = tmp_path / "existing-directory"
    destination.mkdir()

    result = main([
        "--root", str(root),
        "--sessions-dir", str(sessions),
        "--from", START,
        "--until", END,
        "--out", str(destination),
        "--format", "json",
    ])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err.strip() == "audit failed: report output could not be written"
    assert str(tmp_path) not in captured.err
    assert "Traceback" not in captured.err


def test_annotations_bind_to_source_window_hash_and_native_ordinal(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    root = write_log(sessions / "root.jsonl", [
        session_meta("root-id", START),
        record(2, "2026-10-08T10:01:00.000Z", "response_item", {"type": "message", "role": "assistant", "content": "PRIVATE_TEXT"}),
        record(3, "2026-10-08T10:02:00.000Z", "response_item", {"type": "function_call", "name": "pytest", "call_id": "test-call", "arguments": "{}"}),
    ])
    base_report = run_audit(audit_args(root, sessions))
    source_sha = base_report["threads"][0]["window_sha256"]
    annotation_path = tmp_path / "annotations.jsonl"
    annotations = [
        {
            "thread_alias": "root",
            "source_sha256": source_sha,
            "ordinal": 2,
            "kind": "workstream",
            "workstream_id": "audit-1",
            "label": "offline audit",
            "decision": "accepted",
            "source_ref": "review-note-1",
        },
        {
            "thread_alias": "root",
            "source_sha256": source_sha,
            "ordinal": 3,
            "kind": "necessary_test",
            "label": "audit fixture regression",
            "related_workstream_ids": ["audit-1"],
            "decision": "accepted",
            "source_ref": "review-note-2",
        },
    ]
    annotation_path.write_text("".join(json.dumps(item) + "\n" for item in annotations), encoding="utf-8")

    report = run_audit(audit_args(root, sessions, annotations=annotation_path))

    assert report["annotations"]["bound"] == 2
    assert report["annotations"]["accepted_workstreams"] == [
        {"workstream_id": "audit-1", "label": "offline audit", "decision": "accepted"}
    ]
    assert report["threads"][0]["accepted_workstream_annotation_count"] == 1
    assert report["threads"][0]["annotations"][1]["workstream_link_status"] == ["accepted_workstream"]
    assert "PRIVATE_TEXT" not in json.dumps(report)

    annotation_path.write_text(json.dumps({
        "thread_alias": "root",
        "source_sha256": "0" * 64,
        "ordinal": 999,
        "kind": "acceptance",
        "label": "bad binding",
        "decision": "accepted",
        "source_ref": "review-note-2",
    }) + "\n", encoding="utf-8")
    unbound = run_audit(audit_args(root, sessions, annotations=annotation_path))
    assert unbound["annotations"]["unmatched_or_invalid"] == 1
    assert unbound["annotations"]["bound"] == 0
