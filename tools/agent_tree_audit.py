#!/usr/bin/env python3
"""Offline, read-only audit of a Codex session tree.

The tool reads native JSONL session records and optional event-bound human
annotations. It never executes logged content and never prints prompts, command
payloads, tool output, or source paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
EVENT_ANNOTATION_KINDS = {
    "workstream",
    "necessary_test",
    "duplicate_observation",
    "retry",
    "review_finding",
    "rework",
    "acceptance",
    "role_switch",
}
TOKEN_REDACT = re.compile(r"(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+\S+|https?://\S+|[a-z]:[\\/]|\\\\[^\\]+\\[^\\]+|/(?:home|users|mnt|run/user)/)")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:#-]{0,119}$")
SAFE_SOURCE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:#-]{0,119}$")
SAFE_WORKSTREAM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
NATIVE_RECORD_TYPES = frozenset({
    "session_meta",
    "response_item",
    "event_msg",
    "token_usage_record",
    "compacted",
})
NATIVE_EVENT_TYPES = frozenset({"token_count"})
CALL_ITEM_TYPES = frozenset({"function_call", "custom_tool_call"})
RESULT_ITEM_TYPES = frozenset({"function_call_output", "custom_tool_call_output"})
RESPONSE_ITEM_TYPES = CALL_ITEM_TYPES | RESULT_ITEM_TYPES | {"message", "reasoning"}


@dataclass
class ParsedFile:
    path: Path
    meta: dict[str, Any]
    records: list[dict[str, Any]]
    raw_sha256: str
    window_sha256: str
    window_records: list[dict[str, Any]]
    parse_errors: int
    unscoped_records: int
    thread_id: str | None
    parent_ids: set[str]
    parent_field_count: int
    parent_field_invalid: bool
    created_at: datetime | None
    alias: str = ""
    parent_alias: str | None = None
    children: list[str] = field(default_factory=list)


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def native_ordinal(value: Any) -> int | None:
    """Return a usable native record ordinal without trusting malformed values."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_label(value: Any, pattern: re.Pattern[str]) -> str | None:
    if not isinstance(value, str) or not pattern.fullmatch(value.strip()):
        return None
    if TOKEN_REDACT.search(value):
        return None
    return value.strip()


def safe_native_type(value: Any, allowed: frozenset[str]) -> str:
    """Keep only explicitly recognized native type labels in public reports."""
    return value if isinstance(value, str) and value in allowed else "unknown"


def parent_references(meta: dict[str, Any]) -> tuple[set[str], int, bool]:
    values: list[Any] = []
    if "parent_thread_id" in meta:
        values.append(meta.get("parent_thread_id"))

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "parent_thread_id":
                    values.append(nested)
                elif isinstance(nested, (dict, list)):
                    visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    source = meta.get("source")
    if isinstance(source, (dict, list)):
        visit(source)
    refs = {value for value in values if isinstance(value, str) and value}
    invalid = any(not isinstance(value, str) or not value for value in values)
    return refs, len(values), invalid


def read_records(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bytes, int]:
    raw = path.read_bytes()
    records: list[dict[str, Any]] = []
    parse_errors = 0
    meta: dict[str, Any] = {}
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_errors += 1
            continue
        if not isinstance(value, dict):
            parse_errors += 1
            continue
        records.append(value)
        if value.get("type") == "session_meta" and not meta:
            payload = value.get("payload")
            if isinstance(payload, dict):
                meta = payload
    return meta, records, raw, parse_errors


def make_parsed_file(
    path: Path,
    start: datetime | None,
    end: datetime | None,
) -> ParsedFile:
    meta, records, raw, parse_errors = read_records(path)
    selected: list[dict[str, Any]] = []
    selected_raw: list[bytes] = []
    unscoped = 0
    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        stamp = parse_datetime(record.get("timestamp"))
        if stamp is None:
            if start is not None or end is not None:
                unscoped += 1
                continue
            selected.append(record)
            selected_raw.append(line)
            continue
        if (start is None or stamp >= start) and (end is None or stamp < end):
            selected.append(record)
            selected_raw.append(line)
    parent_ids, parent_count, parent_invalid = parent_references(meta)
    identity = meta.get("id")
    thread_id = identity if isinstance(identity, str) and identity else None
    return ParsedFile(
        path=path,
        meta=meta,
        records=records,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        window_sha256=hashlib.sha256(b"\n".join(selected_raw)).hexdigest(),
        window_records=selected,
        parse_errors=parse_errors,
        unscoped_records=unscoped,
        thread_id=thread_id,
        parent_ids=parent_ids,
        parent_field_count=parent_count,
        parent_field_invalid=parent_invalid,
        created_at=parse_datetime(meta.get("timestamp")),
    )


def read_header(path: Path) -> tuple[dict[str, Any], int]:
    errors = 0
    try:
        with path.open("rb") as stream:
            for _ in range(128):
                line = stream.readline()
                if not line:
                    break
                try:
                    record = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    errors += 1
                    continue
                if isinstance(record, dict) and record.get("type") == "session_meta":
                    payload = record.get("payload")
                    return (payload if isinstance(payload, dict) else {}), errors
    except OSError:
        return {}, errors + 1
    return {}, errors


def is_in_window(stamp: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    return stamp is not None and (start is None or stamp >= start) and (end is None or stamp < end)


def discover_tree(root_path: Path, sessions_dir: Path, start: datetime | None, end: datetime | None) -> tuple[list[ParsedFile], dict[str, int]]:
    root = make_parsed_file(root_path, start, end)
    counts: Counter[str] = Counter()
    if root.thread_id is None:
        raise ValueError("root session identity is unavailable")
    if not root.meta:
        raise ValueError("root session metadata is unavailable")

    candidates: list[tuple[Path, dict[str, Any], datetime | None, set[str], int, bool]] = []
    try:
        paths = sorted(p for p in sessions_dir.rglob("*.jsonl") if p.is_file())
    except OSError as exc:
        raise ValueError("sessions directory could not be enumerated") from exc
    counts["candidate_files_scanned"] = len(paths)
    for path in paths:
        if path.resolve() == root_path.resolve():
            continue
        meta, errors = read_header(path)
        counts["candidate_header_errors"] += errors
        if not meta:
            counts["candidate_metadata_missing"] += 1
            continue
        created = parse_datetime(meta.get("timestamp"))
        if end is not None and created is not None and created >= end:
            counts["candidates_excluded_after_window"] += 1
            continue
        if created is None:
            counts["candidate_time_unknown"] += 1
            continue
        refs, field_count, invalid = parent_references(meta)
        candidates.append((path, meta, created, refs, field_count, invalid))

    id_groups: dict[str, list[tuple[Path, dict[str, Any], datetime | None, set[str], int, bool] | None]] = defaultdict(list)
    # Reserve the selected root identity before considering candidate files. A
    # candidate cannot silently replace this anchor by reusing its native ID.
    id_groups[root.thread_id].append(None)
    for candidate in candidates:
        thread_id = candidate[1].get("id")
        if isinstance(thread_id, str) and thread_id:
            id_groups[thread_id].append(candidate)
    duplicate_ids = {key for key, group in id_groups.items() if len(group) > 1}
    counts["duplicate_thread_id_groups"] = len(duplicate_ids)
    counts["duplicate_thread_id_candidate_files"] = sum(
        sum(candidate is not None for candidate in group)
        for group in id_groups.values()
        if len(group) > 1
    )
    counts["selected_root_identity_conflict"] = int(root.thread_id in duplicate_ids)
    counts["candidate_sessions_in_window"] = len(candidates)
    counts["candidate_parent_missing"] = sum(not refs and not invalid for _, _, _, refs, _, invalid in candidates)
    counts["candidate_parent_conflict"] = sum(len(refs) > 1 or invalid for _, _, _, refs, _, invalid in candidates)

    root_key = root.thread_id
    parsed_by_id: dict[str, ParsedFile] = {root_key: root}
    pending = list(candidates)
    progress = True
    while progress:
        progress = False
        remaining = []
        for candidate in pending:
            path, meta, _, refs, field_count, invalid = candidate
            if len(refs) != 1 or invalid:
                remaining.append(candidate)
                continue
            parent_id = next(iter(refs))
            thread_id = meta.get("id")
            if isinstance(thread_id, str) and thread_id in duplicate_ids:
                remaining.append(candidate)
                continue
            if parent_id in duplicate_ids:
                remaining.append(candidate)
                continue
            if isinstance(thread_id, str) and parent_id == thread_id:
                remaining.append(candidate)
                continue
            if parent_id not in parsed_by_id:
                remaining.append(candidate)
                continue
            if not isinstance(thread_id, str) or not thread_id or thread_id in duplicate_ids:
                remaining.append(candidate)
                continue
            child = make_parsed_file(path, start, end)
            child.parent_field_count = field_count
            child.parent_field_invalid = invalid
            child.parent_ids = refs
            child.parent_alias = parsed_by_id[parent_id].alias or "root"
            parsed_by_id[thread_id] = child
            progress = True
        pending = remaining
    counts["unassociated_candidate_files"] = len(pending)
    counts["candidate_identity_conflict_files"] = sum(
        isinstance(meta.get("id"), str) and meta.get("id") in duplicate_ids
        for _, meta, _, _, _, _ in candidates
    )
    counts["candidate_parent_identity_ambiguous"] = sum(
        len(refs) == 1 and next(iter(refs)) in duplicate_ids
        for _, _, _, refs, _, _ in candidates
    )
    counts["candidate_parent_self_reference"] = sum(
        len(refs) == 1 and meta.get("id") == next(iter(refs))
        for _, meta, _, refs, _, _ in candidates
    )
    counts["reachable_threads"] = len(parsed_by_id)

    parsed = list(parsed_by_id.values())
    root.alias = "root"
    children = [item for item in parsed if item is not root]
    children.sort(key=lambda item: (isoformat(item.created_at) or "", item.thread_id or ""))
    aliases: dict[str, str] = {root_key: "root"}
    for index, item in enumerate(children, start=1):
        item.alias = f"agent-{index:03d}"
        aliases[item.thread_id or ""] = item.alias
    for item in children:
        if item.parent_ids and next(iter(item.parent_ids)) not in duplicate_ids:
            parent_id = next(iter(item.parent_ids))
            item.parent_alias = aliases.get(parent_id)
            if item.parent_alias:
                parent = parsed_by_id[parent_id]
                parent.children.append(item.alias)
    for item in parsed:
        item.children.sort()
    return parsed, dict(counts)


def parse_counter_map(raw: Any) -> tuple[dict[str, int] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "counter_map_missing"
    result: dict[str, int] = {}
    for key in TOKEN_FIELDS:
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            return None, "counter_type_or_field_missing"
        if value < 0:
            return None, "negative_counter"
        result[key] = value
    if result["cached_input_tokens"] > result["input_tokens"]:
        return None, "cached_input_exceeds_input"
    if result["reasoning_output_tokens"] > result["output_tokens"]:
        return None, "reasoning_exceeds_output"
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        return None, "total_inconsistent"
    return result, None


def validate_counter_stream(
    values: list[tuple[datetime | None, dict[str, int] | None, str | None]],
    ordinals: list[int | None] | None = None,
    ordinal_counts: Counter[int] | None = None,
) -> dict[str, Any]:
    if not values:
        return {"status": "missing", "snapshot_count": 0, "unique_snapshot_count": 0, "reasons": ["no_cumulative_snapshot"]}
    reasons: set[str] = set()
    if ordinals is not None:
        previous_ordinal: int | None = None
        for ordinal in ordinals:
            if ordinal is None:
                reasons.add("snapshot_native_ordinal_unavailable")
                continue
            if ordinal_counts is not None and ordinal_counts[ordinal] > 1:
                reasons.add("snapshot_native_ordinal_duplicate")
            if previous_ordinal is not None and ordinal <= previous_ordinal:
                reasons.add("snapshot_native_ordinal_out_of_order")
            previous_ordinal = ordinal
    previous_time: datetime | None = None
    previous_values: dict[str, int] | None = None
    unique: set[tuple[tuple[str, int], ...]] = set()
    for stamp, counters, issue in values:
        if issue:
            reasons.add(issue)
            continue
        if counters is None:
            reasons.add("counter_map_missing")
            continue
        if stamp is not None and previous_time is not None and stamp < previous_time:
            reasons.add("snapshot_time_out_of_order")
        if previous_values is not None:
            if any(counters[key] < previous_values[key] for key in TOKEN_FIELDS):
                reasons.add("cumulative_counter_reset_or_out_of_order")
        unique.add(tuple(sorted(counters.items())))
        if stamp is not None:
            previous_time = stamp
        previous_values = counters
    valid = [counters for _, counters, issue in values if counters is not None and issue is None]
    final = valid[-1] if valid else None
    return {
        "status": "observed" if final is not None and not reasons else "unknown",
        "snapshot_count": len(values),
        "unique_snapshot_count": len(unique),
        "duplicate_snapshot_count": max(0, len(values) - len(unique)),
        "reasons": sorted(reasons),
        "final": final,
    }


def validate_usage_chronology(snapshots: list[tuple[datetime | None, int | None]]) -> set[str]:
    """Require file order, native ordinals, and timestamps to agree across usage sources."""
    reasons: set[str] = set()
    previous_ordinal: int | None = None
    previous_time: datetime | None = None
    for stamp, ordinal in snapshots:
        if ordinal is not None:
            if previous_ordinal is not None and ordinal <= previous_ordinal:
                reasons.add("snapshot_native_ordinal_out_of_order")
            previous_ordinal = ordinal
        if stamp is not None:
            if previous_time is not None and stamp < previous_time:
                reasons.add("snapshot_time_out_of_order")
            previous_time = stamp
    return reasons


def usage_for(
    session: ParsedFile,
    start: datetime | None = None,
    end: datetime | None = None,
    *,
    explicit_start: bool = False,
) -> dict[str, Any]:
    record_stream: list[tuple[datetime | None, dict[str, int] | None, str | None]] = []
    event_stream: list[tuple[datetime | None, dict[str, int] | None, str | None]] = []
    record_stream_ordinals: list[int | None] = []
    event_stream_ordinals: list[int | None] = []
    usage_chronology: list[tuple[datetime | None, int | None]] = []
    ordinal_counts = Counter(
        ordinal for record in session.records
        if (ordinal := native_ordinal(record.get("ordinal"))) is not None
        and (end is None or (stamp := parse_datetime(record.get("timestamp"))) is None or stamp < end)
    )
    record_thread_ids: set[str] = set()
    event_thread_ids: set[str] = set()
    turn_ids: set[str] = set()
    for record in session.records:
        stamp = parse_datetime(record.get("timestamp"))
        ordinal = native_ordinal(record.get("ordinal"))
        if end is not None and stamp is not None and stamp >= end:
            continue
        kind = record.get("type")
        payload = record.get("payload")
        if kind == "token_usage_record" and not isinstance(payload, dict):
            issue = "usage_payload_missing"
            if stamp is None:
                issue = "snapshot_timestamp_unavailable"
            elif session.created_at is not None and stamp < session.created_at:
                issue = "snapshot_before_thread_creation"
            record_stream.append((stamp, None, issue))
            record_stream_ordinals.append(ordinal)
            usage_chronology.append((stamp, ordinal))
            continue
        if not isinstance(payload, dict):
            continue
        if kind == "token_usage_record":
            thread_id = payload.get("thread_id")
            if isinstance(thread_id, str):
                record_thread_ids.add(thread_id)
            counters, issue = parse_counter_map(payload.get("thread_token_usage"))
            if not isinstance(thread_id, str) or thread_id != session.thread_id:
                issue = "usage_thread_identity_mismatch"
            if stamp is None:
                issue = "snapshot_timestamp_unavailable"
            elif session.created_at is not None and stamp < session.created_at:
                issue = "snapshot_before_thread_creation"
            record_stream.append((stamp, counters, issue))
            record_stream_ordinals.append(ordinal)
            usage_chronology.append((stamp, ordinal))
        elif kind == "event_msg" and payload.get("type") == "token_count":
            thread_id = payload.get("thread_id")
            if isinstance(thread_id, str):
                event_thread_ids.add(thread_id)
            info = payload.get("info")
            counters, issue = parse_counter_map(info.get("total_token_usage") if isinstance(info, dict) else None)
            # Native token_count events can omit thread_id because they are
            # serialized in the session file anchored by session_meta. Reject
            # an explicit identity only when it conflicts with that anchor.
            if "thread_id" in payload and (not isinstance(thread_id, str) or thread_id != session.thread_id):
                issue = "usage_thread_identity_mismatch"
            if stamp is None:
                issue = "snapshot_timestamp_unavailable"
            elif session.created_at is not None and stamp < session.created_at:
                issue = "snapshot_before_thread_creation"
            event_stream.append((stamp, counters, issue))
            event_stream_ordinals.append(ordinal)
            usage_chronology.append((stamp, ordinal))

    for record in session.window_records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "token_usage_record":
            turn_id = payload.get("turn_id")
            if isinstance(turn_id, str) and turn_id:
                turn_ids.add(turn_id)

    record_summary = validate_counter_stream(record_stream, record_stream_ordinals, ordinal_counts)
    event_summary = validate_counter_stream(event_stream, event_stream_ordinals, ordinal_counts)
    common_chronology_reasons = validate_usage_chronology(usage_chronology)
    if common_chronology_reasons:
        for stream, summary in ((record_stream, record_summary), (event_stream, event_summary)):
            if stream:
                summary["reasons"] = sorted(set(summary.get("reasons", [])) | common_chronology_reasons)
                summary["status"] = "unknown"
    sources = [summary for summary in (record_summary, event_summary) if summary.get("status") != "missing"]
    reasons = set(reason for summary in sources for reason in summary.get("reasons", []))
    if session.parse_errors:
        reasons.add("unparseable_session_record")
    finals = [summary.get("final") for summary in sources if summary.get("final") is not None]
    if len(finals) > 1 and any(final != finals[0] for final in finals[1:]):
        reasons.add("cumulative_sources_disagree")
    if not sources:
        status = "unknown"
        reasons.add("no_cumulative_snapshot")
        final = None
        source = "unknown"
    else:
        final = finals[0] if finals else None
        status = "observed" if final is not None and not reasons and all(item.get("status") == "observed" for item in sources) else "unknown"
        source_parts = []
        if record_stream:
            source_parts.append("token_usage_record.thread_token_usage")
        if event_stream:
            source_parts.append("event_msg.token_count.info.total_token_usage")
        source = "+".join(source_parts) or "unknown"
    def metrics_for(values: dict[str, int] | None) -> dict[str, int] | None:
        if values is None:
            return None
        return {
            "input_tokens": values["input_tokens"],
            "cached_input_tokens": values["cached_input_tokens"],
            "noncached_input_tokens": values["input_tokens"] - values["cached_input_tokens"],
            "output_tokens": values["output_tokens"],
            "reasoning_output_tokens": values["reasoning_output_tokens"],
            "total_tokens": values["total_tokens"],
        }

    as_of_metrics = metrics_for(final) if status == "observed" else None
    if session.created_at is None:
        reasons.add("thread_creation_time_unavailable")
        status = "unknown"
        as_of_metrics = None

    window_start = session.created_at if not explicit_start else start
    created_in_window = session.created_at is not None and (
        (not explicit_start)
        or (
            start is not None
            and session.created_at >= start
            and (end is None or session.created_at < end)
        )
    )
    window_sources: list[tuple[str, dict[str, int], dict[str, int], datetime | None, datetime]] = []
    window_reasons: set[str] = set()
    window_baseline_scope: str | None = None
    if session.parse_errors:
        window_reasons.add("unparseable_session_record")
    if not record_stream and not event_stream:
        window_reasons.add("no_cumulative_snapshot")
    for label, stream, summary in (
        ("token_usage_record.thread_token_usage", record_stream, record_summary),
        ("event_msg.token_count.info.total_token_usage", event_stream, event_summary),
    ):
        if not stream:
            continue
        if summary.get("status") != "observed" or summary.get("final") is None:
            window_reasons.update(summary.get("reasons", []))
            if not summary.get("reasons"):
                window_reasons.add("cumulative_source_unreliable")
            continue
        # Both scopes use this same stream, whose file, native ordinal and
        # timestamp order have already been required to agree. Never reorder
        # conflicting evidence to make a different final snapshot look valid.
        timestamped = [
            (stamp, values)
            for stamp, values, issue in stream
            if stamp is not None and values is not None and issue is None
        ]
        if created_in_window:
            baseline = {key: 0 for key in TOKEN_FIELDS}
            baseline_stamp = session.created_at
            baseline_scope = "native_thread_creation_zero"
            after = [item for item in timestamped if session.created_at is not None and item[0] >= session.created_at]
        else:
            if window_start is None:
                window_reasons.add("window_start_unavailable")
                continue
            prior = [item for item in timestamped if item[0] <= window_start]
            prior_summary = validate_counter_stream([(stamp, values, None) for stamp, values in prior])
            if prior_summary.get("status") != "observed" or prior_summary.get("final") is None:
                window_reasons.update(prior_summary.get("reasons", []))
                if not prior:
                    window_reasons.add("no_reliable_baseline_at_window_start")
                continue
            baseline = prior[-1][1]
            baseline_stamp = prior[-1][0]
            baseline_scope = "latest_cumulative_snapshot_at_or_before_window_start"
            after = [item for item in timestamped if item[0] > baseline_stamp]
        if not after:
            window_reasons.add("no_cumulative_snapshot_after_baseline_in_window")
            continue
        latest = after[-1]
        # The stream itself is already required to be monotonic and reliable.
        latest_values = latest[1]
        delta = {key: latest_values[key] - baseline[key] for key in TOKEN_FIELDS}
        _, delta_issue = parse_counter_map(delta)
        if delta_issue:
            window_reasons.add(f"window_delta_{delta_issue}")
            continue
        window_sources.append((label, delta, latest_values, baseline_stamp, latest[0]))
        if window_baseline_scope is None:
            window_baseline_scope = baseline_scope

    delta_finals = [item[1] for item in window_sources]
    if "cumulative_sources_disagree" in reasons:
        window_reasons.add("cumulative_sources_disagree")
    if len(delta_finals) > 1 and any(value != delta_finals[0] for value in delta_finals[1:]):
        window_reasons.add("cumulative_sources_disagree")
    if len(window_sources) < len([stream for stream in (record_stream, event_stream) if stream]):
        window_reasons.add("cumulative_source_window_scope_unavailable")
    window_metrics = metrics_for(delta_finals[0]) if window_sources and not window_reasons else None
    window_status = "observed" if window_metrics is not None else "unknown"
    window_source = "+".join(item[0] for item in window_sources) or "unknown"
    baseline_timestamps = [item[3] for item in window_sources if item[3] is not None]
    end_timestamps = [item[4] for item in window_sources]
    baseline_at = isoformat(baseline_timestamps[0]) if baseline_timestamps and len(set(baseline_timestamps)) == 1 else None
    end_snapshot_at = isoformat(end_timestamps[0]) if end_timestamps and len(set(end_timestamps)) == 1 else None
    window_summary = {
        "status": window_status,
        "scope": "cumulative_snapshot_time_delta",
        "source": window_source,
        "metrics": window_metrics,
        "baseline_scope": locals().get("window_baseline_scope", "unknown"),
        "baseline_at": baseline_at,
        "baseline_snapshots": [
            {"source": item[0], "at": isoformat(item[3])}
            for item in window_sources
        ],
        "latest_snapshot_at": end_snapshot_at,
        "latest_snapshots": [
            {"source": item[0], "at": isoformat(item[4])}
            for item in window_sources
        ],
        "reasons": sorted(window_reasons),
    }

    as_of_summary = {
        "status": status,
        "scope": "thread_cumulative_as_of_window_end",
        "source": source,
        "metrics": as_of_metrics,
        "reasons": sorted(reasons),
    }
    return {
        "status": status,
        "source": source,
        "metrics": as_of_metrics,
        "metrics_scope": "thread_cumulative_as_of_window_end",
        "thread_cumulative_as_of_window_end": as_of_summary,
        "window_increment": window_summary,
        "reasons": sorted(reasons),
        "token_usage_record_snapshots": record_summary,
        "event_total_snapshots": event_summary,
        "unique_turn_count": len(turn_ids),
        "thread_identity_verified": (not record_thread_ids or record_thread_ids == {session.thread_id}) and (not event_thread_ids or event_thread_ids == {session.thread_id}),
    }


def output_text(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts = [item.get("text") for item in payload if isinstance(item, dict) and isinstance(item.get("text"), str)]
        if parts:
            return "\n".join(parts)
    return None


def safe_result_object(payload: Any) -> dict[str, Any] | None:
    raw = output_text(payload)
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def tool_name(item: dict[str, Any]) -> str:
    name = item.get("name") or item.get("tool_name")
    return name if isinstance(name, str) else ""


def tool_arguments(item: dict[str, Any]) -> dict[str, Any] | None:
    raw = item.get("arguments")
    if raw is None:
        raw = item.get("input")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def classify_tool(name: str, item: dict[str, Any]) -> tuple[str, str]:
    lowered = name.lower()
    if lowered in {"sleep", "clock.sleep", "clock__sleep", "functions.sleep"} or lowered.endswith("__sleep"):
        return "sleep", "observed"
    if "wait_agent" in lowered or "wait_threads" in lowered or "get_handoff_status" in lowered or lowered == "wait":
        return "native_wait", "observed"
    if "spawn_agent" in lowered or lowered == "spawn_agent":
        return "agent_spawn", "observed"
    if "send_message" in lowered:
        return "agent_message", "observed"
    if lowered == "exec" or lowered.endswith("__exec"):
        raw = item.get("input")
        code = raw if isinstance(raw, str) else ""
        if re.search(r"\b(pytest|unittest|tox|nox)\b", code, re.I):
            return "test", "inferred"
        if re.search(r"\b(gh\s+run|workflow|github\s+actions|ci\.yml)\b", code, re.I):
            return "ci_observation", "inferred"
        if re.search(r"\b(sleep|clock__sleep)\b", code, re.I):
            return "sleep", "inferred"
        if re.search(r"\b(exec_command|subprocess|powershell|cmd\.exe|\bgit\b|\bpython\b|\buv\s+)", code, re.I):
            return "shell", "inferred"
        return "exec_or_code", "observed"
    if lowered in {"exec_command", "shell", "terminal"}:
        return "shell", "observed"
    return "other_tool", "observed"


def observed_calls(session: ParsedFile, start: datetime | None, end: datetime | None) -> dict[str, Any]:
    starts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_call_counts: Counter[str] = Counter()
    all_result_counts: Counter[str] = Counter()
    unclassified_call_ids: set[str] = set()
    for record in session.records:
        payload = record.get("payload")
        if record.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        call_id = payload.get("call_id")
        if not isinstance(kind, str) or kind not in CALL_ITEM_TYPES | RESULT_ITEM_TYPES:
            if isinstance(call_id, str) and call_id:
                unclassified_call_ids.add(call_id)
            continue
        if not isinstance(call_id, str) or not call_id:
            continue
        if kind in CALL_ITEM_TYPES:
            all_call_counts[call_id] += 1
        elif kind in RESULT_ITEM_TYPES:
            all_result_counts[call_id] += 1
    calls_by_record: list[dict[str, Any]] = []
    result_records_without_id = 0
    unclassified_response_item_count = 0
    for record in session.window_records:
        payload = record.get("payload")
        if record.get("type") != "response_item":
            continue
        if not isinstance(payload, dict):
            unclassified_response_item_count += 1
            continue
        kind = payload.get("type")
        if not isinstance(kind, str) or kind not in RESPONSE_ITEM_TYPES:
            unclassified_response_item_count += 1
            continue
        call_id = payload.get("call_id")
        if kind in CALL_ITEM_TYPES:
            name = tool_name(payload)
            category, evidence = classify_tool(name, payload)
            args = tool_arguments(payload)
            timeout = args.get("timeout_ms", args.get("timeoutMs")) if args else None
            yield_ms = args.get("yield_time_ms", args.get("yieldTimeMs")) if args else None
            row = {
                "call_id": call_id if isinstance(call_id, str) and call_id else None,
                "name": name,
                "category": category,
                "category_evidence": evidence,
                "timestamp": parse_datetime(record.get("timestamp")),
                "ordinal": native_ordinal(record.get("ordinal")),
                "requested_timeout_ms": timeout if isinstance(timeout, int) and not isinstance(timeout, bool) and timeout >= 0 else None,
                "requested_yield_ms": yield_ms if isinstance(yield_ms, int) and not isinstance(yield_ms, bool) and yield_ms >= 0 else None,
                "wait": category == "native_wait",
                "kind": kind,
            }
            calls_by_record.append(row)
            if row["call_id"] is not None:
                starts[row["call_id"]].append(row)
        elif kind in RESULT_ITEM_TYPES:
            result = {
                "timestamp": parse_datetime(record.get("timestamp")),
                "ordinal": native_ordinal(record.get("ordinal")),
                "payload": payload.get("output"),
            }
            if isinstance(call_id, str) and call_id:
                results[call_id].append(result)
            else:
                result_records_without_id += 1
    categories: Counter[tuple[str, str]] = Counter()
    requested_timeouts: Counter[str] = Counter()
    requested_yields: Counter[str] = Counter()
    complete_elapsed: list[int] = []
    timeout_true = timeout_false = paired_wait_results = 0
    result_observed = unfinished = 0
    pending_intervals: list[tuple[datetime, datetime]] = []
    wait_elapsed: list[int] = []
    wait_records = [item for item in calls_by_record if item["wait"]]
    paired_call_ids: set[str] = set()
    paired_result_records = 0
    duplicate_start_id_count = sum(all_call_counts[call_id] > 1 for call_id in starts)
    def ambiguous_id(call_id: str) -> bool:
        return (
            all_call_counts[call_id] > 1
            or all_result_counts[call_id] > 1
            or call_id in unclassified_call_ids
        )

    ambiguous_call_id_count = 0
    for call_id, items in starts.items():
        result_items = results.get(call_id, [])
        if ambiguous_id(call_id):
            ambiguous_call_id_count += 1
        for item in items:
            categories[(item["category"], item["category_evidence"])] += 1
            if item["wait"] and item["requested_timeout_ms"] is not None:
                requested_timeouts[str(item["requested_timeout_ms"])] += 1
            if item["wait"] and item["requested_yield_ms"] is not None:
                requested_yields[str(item["requested_yield_ms"])] += 1
        if (
            len(items) != 1
            or len(result_items) != 1
            or ambiguous_id(call_id)
        ):
            unfinished += len(items)
            continue
        item = items[0]
        result = result_items[0]
        call_ordinal = item["ordinal"]
        result_ordinal = result["ordinal"]
        if (
            call_ordinal is None
            or result_ordinal is None
            or result_ordinal <= call_ordinal
            or item["timestamp"] is None
            or result["timestamp"] is None
        ):
            unfinished += len(items)
            continue
        elapsed: int | None = None
        delta = (result["timestamp"] - item["timestamp"]).total_seconds() * 1000
        if delta < 0:
            unfinished += len(items)
            continue
        if is_in_window(item["timestamp"], start, end) and is_in_window(result["timestamp"], start, end):
            elapsed = int(delta)
            complete_elapsed.append(elapsed)
            pending_intervals.append((item["timestamp"], result["timestamp"]))
            if item["wait"]:
                wait_elapsed.append(elapsed)
        paired_call_ids.add(call_id)
        result_observed += 1
        paired_result_records += 1
        if item["wait"]:
            paired_wait_results += 1
            result_object = safe_result_object(result["payload"])
            timed_out = result_object.get("timed_out") if result_object else None
            if isinstance(timed_out, bool):
                if timed_out:
                    timeout_true += 1
                else:
                    timeout_false += 1
    for item in calls_by_record:
        if item["call_id"] is None:
            categories[(item["category"], item["category_evidence"])] += 1
            if item["wait"] and item["requested_timeout_ms"] is not None:
                requested_timeouts[str(item["requested_timeout_ms"])] += 1
            if item["wait"] and item["requested_yield_ms"] is not None:
                requested_yields[str(item["requested_yield_ms"])] += 1
            unfinished += 1
    unmatched_result_records = result_records_without_id + sum(
        len(items) for call_id, items in results.items()
        if call_id not in paired_call_ids
    )
    observed_result_records = paired_result_records + unmatched_result_records
    unique_wait_ids = {item["call_id"] for item in wait_records if item["call_id"] is not None}
    ambiguous_wait_ids = sum(ambiguous_id(call_id) for call_id in unique_wait_ids)
    unpaired_wait_records = len(wait_records) - paired_wait_results
    timeout_unknown = len(wait_records) - timeout_true - timeout_false
    wait_result_record_count = sum(len(results.get(call_id, [])) for call_id in unique_wait_ids)
    wait_result_records_unmatched = wait_result_record_count - paired_wait_results
    max_concurrent = 0
    active: list[datetime] = []
    for left, right in sorted(pending_intervals):
        active = [finish for finish in active if finish > left]
        active.append(right)
        max_concurrent = max(max_concurrent, len(active))
    return {
        "unclassified_response_item_count": unclassified_response_item_count,
        "started_call_count": len(calls_by_record),
        "observed_call_records": len(calls_by_record),
        "unique_started_call_id_count": len(starts),
        "ambiguous_call_id_count": ambiguous_call_id_count,
        "duplicate_call_id_count": duplicate_start_id_count,
        "result_observed_count": result_observed,
        "observed_result_records": observed_result_records,
        "paired_result_record_count": paired_result_records,
        "unmatched_or_ambiguous_result_record_count": unmatched_result_records,
        "result_record_coverage_conserves": paired_result_records + unmatched_result_records == sum(len(items) for items in results.values()) + result_records_without_id,
        "unfinished_or_ambiguous_count": unfinished,
        "categories": [
            {"category": category, "evidence": evidence, "count": count}
            for (category, evidence), count in sorted(categories.items())
        ],
        "native_waits": {
            "call_count": len(wait_records),
            "observed_call_records": len(wait_records),
            "unique_call_id_count": len(unique_wait_ids),
            "ambiguous_call_id_count": ambiguous_wait_ids,
            "calls_with_unique_result": paired_wait_results,
            "unpaired_or_ambiguous_call_records": unpaired_wait_records,
            "result_records_for_wait_call_ids": wait_result_record_count,
            "unmatched_or_ambiguous_result_records": wait_result_records_unmatched,
            "results_observed": paired_wait_results,
            "timed_out_observed": timeout_true,
            "completed_without_timeout_observed": timeout_false,
            "outcome_unknown_or_unfinished": timeout_unknown,
            "call_record_coverage_conserves": timeout_true + timeout_false + timeout_unknown == len(wait_records),
            "result_record_coverage_conserves": paired_wait_results + wait_result_records_unmatched == wait_result_record_count,
            "requested_timeout_ms_histogram": dict(requested_timeouts),
            "requested_yield_ms_histogram": dict(requested_yields),
            "elapsed_ms_observed": {
                "count": len(wait_elapsed),
                "min": min(wait_elapsed) if wait_elapsed else None,
                "median": statistics.median(wait_elapsed) if wait_elapsed else None,
                "max": max(wait_elapsed) if wait_elapsed else None,
                "sum_is_not_wall_time": True,
            },
        },
        "elapsed_ms_observed_all_calls": {
            "count": len(complete_elapsed),
            "min": min(complete_elapsed) if complete_elapsed else None,
            "median": statistics.median(complete_elapsed) if complete_elapsed else None,
            "max": max(complete_elapsed) if complete_elapsed else None,
            "sum_is_not_wall_time": True,
        },
        "max_simultaneous_observed_call_intervals": max_concurrent,
    }


def token_coverage(record: dict[str, Any]) -> bool:
    return bool(record.get("token_usage_record_snapshots", {}).get("snapshot_count") or record.get("event_total_snapshots", {}).get("snapshot_count"))


def validate_annotations(
    annotation_path: Path | None,
    sessions: list[ParsedFile],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counts: Counter[str] = Counter()
    if annotation_path is None:
        return [], {"provided": 0, "bound": 0, "unmatched_or_invalid": 0}
    aliases = {session.alias: session for session in sessions}
    bound: list[dict[str, Any]] = []
    try:
        lines = annotation_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("annotation file could not be read") from exc
    for line in lines:
        if not line.strip():
            continue
        counts["provided"] += 1
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            counts["unmatched_or_invalid"] += 1
            continue
        if not isinstance(item, dict):
            counts["unmatched_or_invalid"] += 1
            continue
        alias = item.get("thread_alias")
        session = aliases.get(alias) if isinstance(alias, str) else None
        ordinal = item.get("ordinal")
        kind = item.get("kind")
        label = safe_label(item.get("label"), SAFE_LABEL)
        source_ref = safe_label(item.get("source_ref"), SAFE_SOURCE_REF)
        raw_workstream_id = item.get("workstream_id")
        workstream_id = safe_label(raw_workstream_id, SAFE_WORKSTREAM_ID) if raw_workstream_id is not None else None
        workstream_id_invalid = raw_workstream_id is not None and workstream_id is None
        related_ids = item.get("related_workstream_ids", [])
        related_ids_valid = (
            isinstance(related_ids, list)
            and all(safe_label(value, SAFE_WORKSTREAM_ID) is not None for value in related_ids)
        )
        safe_related_ids = [safe_label(value, SAFE_WORKSTREAM_ID) for value in related_ids] if related_ids_valid else []
        if (
            session is None
            or not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or not isinstance(kind, str)
            or kind not in EVENT_ANNOTATION_KINDS
            or label is None
            or source_ref is None
            or workstream_id_invalid
            or (kind == "workstream" and workstream_id is None)
            or not related_ids_valid
            or item.get("source_sha256") != session.window_sha256
        ):
            counts["unmatched_or_invalid"] += 1
            continue
        matching_records = [row for row in session.window_records if row.get("ordinal") == ordinal]
        if len(matching_records) != 1:
            counts["unmatched_or_invalid"] += 1
            continue
        record = matching_records[0]
        decision = item.get("decision")
        if not isinstance(decision, str) or decision not in {"accepted", "rejected", "unknown"}:
            decision = "unknown"
        bound.append({
            "thread_alias": alias,
            "source_sha256": session.window_sha256,
            "ordinal": ordinal,
            "record_type": safe_native_type(record.get("type"), NATIVE_RECORD_TYPES),
            "kind": kind,
            "label": label,
            "workstream_id": workstream_id,
            "related_workstream_ids": safe_related_ids if kind != "workstream" else [],
            "decision": decision,
            "source_ref": source_ref,
        })
        counts["bound"] += 1
    counts.setdefault("provided", 0)
    counts.setdefault("bound", 0)
    counts.setdefault("unmatched_or_invalid", 0)
    declared: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for annotation in bound:
        if annotation["kind"] == "workstream":
            declared[annotation["workstream_id"]].append(annotation)
    accepted_workstreams: list[dict[str, Any]] = []
    conflicted_workstream_ids: set[str] = set()
    for workstream_id, declarations in sorted(declared.items()):
        outcomes = {(row["label"], row["decision"]) for row in declarations}
        if len(outcomes) != 1:
            conflicted_workstream_ids.add(workstream_id)
            continue
        label, decision = next(iter(outcomes))
        if decision == "accepted":
            accepted_workstreams.append({"workstream_id": workstream_id, "label": label, "decision": decision})
    accepted_ids = {row["workstream_id"] for row in accepted_workstreams}
    declared_ids = set(declared)
    unknown_refs = 0
    for annotation in bound:
        if annotation["kind"] == "workstream":
            continue
        statuses = []
        for workstream_id in annotation["related_workstream_ids"]:
            if workstream_id not in declared_ids:
                statuses.append("unknown_workstream_id")
                unknown_refs += 1
            elif workstream_id in conflicted_workstream_ids:
                statuses.append("conflicting_workstream_definition")
            elif workstream_id not in accepted_ids:
                statuses.append("workstream_not_accepted")
            else:
                statuses.append("accepted_workstream")
        annotation["workstream_link_status"] = statuses
    counts.setdefault("provided", 0)
    counts.setdefault("bound", 0)
    counts.setdefault("unmatched_or_invalid", 0)
    counts["unknown_workstream_reference_count"] = unknown_refs
    counts["conflicting_workstream_id_count"] = len(conflicted_workstream_ids)
    counts["accepted_workstreams"] = accepted_workstreams
    return bound, dict(counts)


def session_summary(
    session: ParsedFile,
    start: datetime | None,
    end: datetime | None,
    *,
    explicit_start: bool = False,
) -> dict[str, Any]:
    role = session.meta.get("agent_role")
    role = safe_label(role, SAFE_LABEL)
    role_observed = role is not None
    nickname = safe_label(session.meta.get("agent_nickname"), SAFE_LABEL)
    timestamps = [parse_datetime(row.get("timestamp")) for row in session.window_records]
    stamps = [stamp for stamp in timestamps if stamp is not None]
    usage = usage_for(session, start, end, explicit_start=explicit_start)
    call_summary = observed_calls(session, start, end)
    counts = Counter(safe_native_type(row.get("type"), NATIVE_RECORD_TYPES) for row in session.window_records)
    event_counts = Counter()
    user_messages = 0
    for row in session.window_records:
        payload = row.get("payload")
        if row.get("type") == "event_msg" and isinstance(payload, dict):
            event_counts[safe_native_type(payload.get("type"), NATIVE_EVENT_TYPES)] += 1
        if row.get("type") == "response_item" and isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "user":
            user_messages += 1
    span_ms = None
    if len(stamps) >= 2:
        span_ms = int((max(stamps) - min(stamps)).total_seconds() * 1000)
    return {
        "thread_alias": session.alias,
        "parent_alias": session.parent_alias,
        "child_aliases": session.children,
        "role": role if role_observed else "unknown",
        "role_evidence": "native_metadata" if role_observed else "unknown",
        "agent_nickname": nickname,
        "source_sha256": session.raw_sha256,
        "window_sha256": session.window_sha256,
        "window_record_count": len(session.window_records),
        "source_file_parse_error_count": session.parse_errors,
        "unscoped_record_count": session.unscoped_records,
        "first_observed_record_at": isoformat(min(stamps)) if stamps else None,
        "last_observed_record_at": isoformat(max(stamps)) if stamps else None,
        "observed_record_span_ms": span_ms,
        "record_type_counts": dict(sorted(counts.items())),
        "native_event_type_counts": dict(sorted(event_counts.items())),
        "user_message_record_count": user_messages,
        "compaction_record_count": counts.get("compacted", 0),
        "native_turn_id_count": usage["unique_turn_count"],
        "token_usage": usage,
        "calls": call_summary,
    }


def role_token_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["role"]].append(row)
    result = []
    for role, members in sorted(grouped.items()):
        token_rows = [member["token_usage"] for member in members]
        complete = all(value.get("status") == "observed" and isinstance(value.get("metrics"), dict) for value in token_rows)
        totals = None
        if complete:
            metrics = [value["metrics"] for value in token_rows]
            totals = {key: sum(item[key] for item in metrics) for key in metrics[0]}
        result.append({
            "role": role,
            "thread_count": len(members),
            "token_status": "observed" if complete else "unknown",
            "tokens": totals,
            "threads_with_missing_usage": sum(value.get("status") != "observed" for value in token_rows),
        })
    return result


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    root_path = Path(args.root)
    try:
        root_meta, _ = read_header(root_path)
    except OSError as exc:
        raise ValueError("root log could not be read") from exc
    start = parse_datetime(args.from_time) if args.from_time else parse_datetime(root_meta.get("timestamp"))
    end = parse_datetime(args.until) if args.until else None
    if args.from_time and start is None:
        raise ValueError("from time must be an ISO-8601 timestamp with a timezone")
    if args.until and end is None:
        raise ValueError("until time must be an ISO-8601 timestamp with a timezone")
    if start is not None and end is not None and end <= start:
        raise ValueError("until time must be later than from time")
    sessions, tree_counts = discover_tree(root_path, Path(args.sessions_dir), start, end)
    explicit_start = bool(args.from_time)
    summaries = [session_summary(session, start, end, explicit_start=explicit_start) for session in sessions]
    annotations, annotation_counts = validate_annotations(Path(args.annotations) if args.annotations else None, sessions)
    annotations_by_alias: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for annotation in annotations:
        annotations_by_alias[annotation["thread_alias"]].append(annotation)
    for row in summaries:
        values = annotations_by_alias.get(row["thread_alias"], [])
        row["annotations"] = values
        row["accepted_workstream_annotation_count"] = sum(item["kind"] == "workstream" and item["decision"] == "accepted" for item in values)
    reachable_tokens = sum(
        row["token_usage"]["metrics"]["total_tokens"]
        for row in summaries
        if row["token_usage"]["status"] == "observed" and row["token_usage"]["metrics"] is not None
    )
    unknown_token_threads = sum(row["token_usage"]["status"] != "observed" for row in summaries)
    observed_window_increment_threads = sum(
        row["token_usage"]["window_increment"]["status"] == "observed" for row in summaries
    )
    unknown_window_increment_threads = len(summaries) - observed_window_increment_threads
    reachable_window_increment_tokens = sum(
        row["token_usage"]["window_increment"]["metrics"]["total_tokens"]
        for row in summaries
        if row["token_usage"]["window_increment"]["metrics"] is not None
    )
    record_counts = Counter()
    parse_errors = 0
    unscoped_records = 0
    for session in sessions:
        record_counts.update(safe_native_type(row.get("type"), NATIVE_RECORD_TYPES) for row in session.window_records)
        parse_errors += session.parse_errors
        unscoped_records += session.unscoped_records
    return {
        "schema_version": 1,
        "mode": "offline_read_only",
        "window": {
            "start_inclusive_utc": isoformat(start),
            "end_exclusive_utc": isoformat(end),
            "root_header_start_used_when_from_omitted": not bool(args.from_time),
            "timestamped_records_only_when_window_is_set": True,
            "usage_as_of_window_end_excludes_end_timestamp": True,
            "window_increment_basis": "cumulative native usage snapshots after the selected baseline and before the end-exclusive cutoff",
            "explicit_start_requested": explicit_start,
        },
        "privacy": {
            "input_paths_redacted": True,
            "prompts_commands_tool_payloads_and_tool_output_omitted": True,
            "source_sha256_in_report_is_for_external_private_evidence_storage": True,
        },
        "tree_coverage": {
            **tree_counts,
            "root_and_reachable_threads": len(summaries),
            "parent_linkage_source": "session_meta.payload.id plus parent_thread_id fields in session_meta.payload and nested source metadata",
            "unassociated_and_conflicting_candidates_remain_unknown": True,
        },
        "usage_coverage": {
            "threads_with_observed_tokens": len(summaries) - unknown_token_threads,
            "threads_with_unknown_tokens": unknown_token_threads,
            "summed_observed_total_tokens_only": reachable_tokens,
            "summed_observed_total_tokens_scope": "thread_cumulative_as_of_window_end",
            "all_thread_cumulative_totals_observed": unknown_token_threads == 0,
            "summed_observed_window_increment_total_tokens_only": reachable_window_increment_tokens,
            "summed_observed_window_increment_total_tokens_scope": "window_increment",
            "threads_with_observed_window_increment": observed_window_increment_threads,
            "threads_with_unknown_window_increment": unknown_window_increment_threads,
            "all_window_increments_observed": unknown_window_increment_threads == 0,
            "missing_or_invalid_usage_is_not_zero": True,
            "event_token_count_is_reconciliation_only_and_never_added_to_cumulative_records": True,
            "reasoning_tokens_are_an_output_subset": True,
        },
        "record_coverage": {
            "record_type_counts": dict(sorted(record_counts.items())),
            "jsonl_source_file_parse_error_count": parse_errors,
            "records_without_usable_timestamp_count": unscoped_records,
            "compaction_records": record_counts.get("compacted", 0),
        },
        "annotations": {
            "binding": "thread alias plus source window SHA-256 plus native record ordinal",
            **annotation_counts,
            "events_without_annotations_remain_semantically_unknown": True,
        },
        "threads": summaries,
        "role_token_totals": role_token_summary(summaries),
        "semantic_unknowns": [
            "workstream boundaries unless explicitly annotated",
            "necessary versus repeated test, CI, process, wait, or shell observations unless explicitly annotated",
            "retry intent, review-finding validity, rework, and final semantic acceptance unless explicitly annotated",
            "human identity, authority, and control-plane status",
        ],
        "limitations": [
            "Logged content is never executed or emitted.",
            "Elapsed call intervals are observations; their sums are not wall time and do not establish useful work or waste.",
            "Call category labels inferred from generic exec input are marked inferred.",
            "Thread roles are taken from native agent_role metadata; missing roles remain unknown.",
            "Token values are reported only when cumulative snapshots are valid, monotonic, identity-consistent, and reconciled.",
        ],
    }


def print_table(report: dict[str, Any]) -> None:
    window = report["window"]
    coverage = report["tree_coverage"]
    print(f"Agent-tree audit window: {window['start_inclusive_utc']} through {window['end_exclusive_utc'] or 'latest'} (end exclusive)")
    print(f"Reachable threads: {coverage['root_and_reachable_threads']} / candidate files: {coverage['candidate_files_scanned']}; unassociated candidates: {coverage['unassociated_candidate_files']}")
    print("alias       role                     thread cumulative as of end (input/cached/noncached/output/reasoning) [status]")
    for row in report["threads"]:
        usage = row["token_usage"]
        metrics = usage.get("metrics") or {}
        role = str(row["role"])[:24]
        print(
            f"{row['thread_alias']:<11} {role:<24} "
            f"{metrics.get('input_tokens', 'UNKNOWN')}/"
            f"{metrics.get('cached_input_tokens', 'UNKNOWN')}/"
            f"{metrics.get('noncached_input_tokens', 'UNKNOWN')}/"
            f"{metrics.get('output_tokens', 'UNKNOWN')}/"
            f"{metrics.get('reasoning_output_tokens', 'UNKNOWN')} [{usage['status']}]"
        )
        increment = usage["window_increment"]
        increment_metrics = increment.get("metrics") or {}
        print(
            f"  window_increment_total={increment_metrics.get('total_tokens', 'UNKNOWN')} "
            f"status={increment['status']} baseline={increment['baseline_at'] or increment['baseline_scope']}"
        )
        waits = row["calls"]["native_waits"]
        elapsed = waits["elapsed_ms_observed"]
        print(
            f"  wait_records={waits['call_count']} unique_ids={waits['unique_call_id_count']} "
            f"ambiguous_ids={waits['ambiguous_call_id_count']} results={waits['results_observed']} "
            f"timed_out={waits['timed_out_observed']} "
            f"completed={waits['completed_without_timeout_observed']} "
            f"unknown={waits['outcome_unknown_or_unfinished']} elapsed_samples={elapsed['count']} "
            f"compactions={row['compaction_record_count']}"
        )
    print("Role totals:")
    for row in report["role_token_totals"]:
        tokens = row["tokens"]
        total = tokens["total_tokens"] if tokens is not None else "UNKNOWN"
        print(f"  {row['role']}: {row['thread_count']} threads, total_tokens={total}, status={row['token_status']}")
    print("Thread cumulative and window increment have separate scopes; unannotated semantic conclusions remain UNKNOWN; interval sums are not wall time.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Root session JSONL file")
    parser.add_argument("--sessions-dir", required=True, help="Directory containing candidate session JSONL files")
    parser.add_argument("--from", dest="from_time", help="Inclusive ISO-8601 start time; defaults to root session start")
    parser.add_argument("--until", help="Exclusive ISO-8601 end time")
    parser.add_argument("--annotations", help="Optional offline JSONL annotations bound to source hash and ordinal")
    parser.add_argument("--format", choices=("json", "table"), default="table")
    parser.add_argument("--out", help="Optional destination for sanitized JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = run_audit(args)
    except OSError:
        print("audit failed: file access failed", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("audit failed: unexpected data or processing error", file=sys.stderr)
        return 2
    if args.out:
        destination = Path(args.out)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            print("audit failed: report output could not be written", file=sys.stderr)
            return 2
    if args.format == "json":
        if args.out:
            print("Sanitized JSON report saved.")
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
