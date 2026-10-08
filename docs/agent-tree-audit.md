# Offline Agent-tree audit

`tools/agent_tree_audit.py` reads saved Codex session JSONL files for a bounded,
read-only audit. It is a local analysis utility; it does not add Hooks, runtime
logging, task-state synchronization, or a Host dependency.

The tree uses `session_meta.payload.id` as the thread identity and joins child
logs only through native `parent_thread_id` metadata, including the nested
`source.subagent.thread_spawn.parent_thread_id` form. File names and role labels
do not establish parentage. Missing, conflicting, duplicate, or unassociated
identities stay in the coverage counts as unresolved.

Use an explicit end-exclusive UTC time when the log continues beyond the period
under review:

```powershell
py -3.11 tools/agent_tree_audit.py `
  --root '<root-session.jsonl>' `
  --sessions-dir '<sessions-directory>' `
  --from '2026-10-08T10:42:51.968Z' `
  --until '2026-10-08T17:27:45.987Z' `
  --out '<private-evidence-directory>/agent-tree-audit.json' `
  --format table
```

The JSON report records source hashes and aliases while omitting file paths,
prompts, commands, tool payloads, and tool output. Store it with restricted
local evidence; do not add raw session logs or machine-private paths to Git.
The table shows the observed window, tree coverage, thread-cumulative usage as
of the end cutoff, window increments, native wait results, and compaction
counts. Record type values are emitted only for a fixed set the utility
understands; all other native type values share the literal `unknown` bucket.
Unknown values are never used as report keys or annotations.

Usage summaries prefer cumulative `token_usage_record.thread_token_usage` and
cross-check `event_msg.token_count.info.total_token_usage`. Duplicate snapshots
and `last_token_usage` summaries are never added. The report computes noncached
input as input minus its cached subset, and keeps reasoning as an output subset.
Missing fields, identity mismatch, invalid subset values, counter resets,
out-of-order snapshots, or disagreement between cumulative sources leave the
affected usage `UNKNOWN`; missing data is never treated as zero. The legacy
`token_usage.metrics` field is explicitly scoped to
`thread_cumulative_as_of_window_end`: the latest reliable cumulative snapshot
before the end-exclusive cutoff, validated across the thread's observed
history. `window_increment.metrics` is a separate delta scoped to usage
snapshots after its baseline and before that cutoff; it is not a price, charge,
or exact allocation to request start times or wall-clock activity.
Both usage scopes require source file order, native ordinal order, and timestamp
order to agree. Equal timestamps use strictly increasing native ordinals;
missing, invalid, duplicate, or conflicting ordinals leave usage `UNKNOWN`.
The audit never sorts conflicting evidence into a different chronology or uses
file position as a replacement ordinal. Duplicate ordinal checks cover parsed
thread records before the end cutoff, including records from the other source.
The window delta is validated independently, including its cached-input and
reasoning-output subset relationships. Any unresolved disagreement between
cumulative sources also leaves the increment `UNKNOWN`, even when the sources'
deltas happen to match. A recognized usage record with a missing payload, or an
unparseable JSONL record whose type cannot be determined, taints the thread's
usage as `UNKNOWN` rather than treating earlier snapshots as complete.

With an explicit `--from`, the increment baseline is the latest reliable
cumulative snapshot at or before that time. A thread created inside the window
may use a zero baseline only when its native session metadata proves the
creation time is inside the window. If an older thread has no reliable
pre-window baseline, if no later cumulative snapshot was observed, or if the
counter stream or source scope cannot be reconciled, the increment is
`UNKNOWN`. Without `--from`, the cumulative value runs from that thread's
native creation time through the cutoff, and the increment uses the same
thread-creation zero baseline. The `--until` time is end-exclusive for both
scopes. A snapshot at or after that cutoff does not affect either metric.

Native call IDs pair call and result records only when the ID has one call
record and one result record across the parsed thread, and both records are in
the selected window. Pairing also requires a later result ordinal and a result
timestamp at or after the call timestamp; missing chronology or a result that
precedes its call leaves the pair unresolved. Equal timestamps are ordered by
native ordinal. The audit recognizes call and output response-item types plus
`message` and `reasoning`. All other subtype values, including empty or unknown
strings, are counted in a safe unclassified bucket without exposing their
payload. Any call ID attached to a response item outside the call/output types
remains ambiguous across the parsed thread, even outside the selected window.
Overall call and wait ambiguity counts use the same predicate; affected selected
call and result records remain in the unresolved coverage counts.
Wait summaries label call-record counts,
distinct wait IDs, ambiguous IDs, uniquely paired results, and unpaired or
ambiguous records separately. A repeated call ID or repeated result makes all
affected wait records `UNKNOWN`; unmatched results are counted separately.
Wait outcome counts conserve the observed wait records:
`timed_out + completed_without_timeout + outcome_unknown_or_unfinished =
call_count`. Result-record coverage also reports whether paired and
unmatched/ambiguous output records account for all observed outputs. The report
separates observed elapsed duration from requested timeout or yield duration,
marks categories inferred from generic `exec` code, and does not treat duration
sums as wall time. Logged commands are never executed. Workstream boundaries,
necessary versus repeated observations, retry intent, review findings, rework,
and final acceptance remain `UNKNOWN` unless the caller supplies bound
annotations; without an annotation file the audit still runs and leaves these
semantic conclusions unknown.

Optional annotation JSONL uses one object per line. Every entry binds an alias,
the report's `window_sha256`, and a native record ordinal, and cites an opaque
offline source reference:

```json
{"thread_alias":"agent-001","source_sha256":"<window_sha256>","ordinal":42,"kind":"workstream","workstream_id":"routing","label":"routing audit","decision":"accepted","source_ref":"review-note-1"}
{"thread_alias":"agent-001","source_sha256":"<window_sha256>","ordinal":87,"kind":"necessary_test","label":"focused regression","decision":"accepted","related_workstream_ids":["routing"],"source_ref":"review-note-1"}
```

Allowed event kinds are `workstream`, `necessary_test`,
`duplicate_observation`, `retry`, `review_finding`, `rework`, `acceptance`, and
`role_switch`. Conflicting workstream definitions or references to undefined
IDs remain unresolved. Annotation labels and source references are restricted
to a conservative safe character set with the same credential and private-path
screening used for every workstream ID, including IDs in
`related_workstream_ids`. Rejected or unmatched entries are counted and never
silently applied. The native record type attached to a bound annotation uses
the same fixed recognized-type mapping as the report; unknown input is emitted
only as `unknown`.
