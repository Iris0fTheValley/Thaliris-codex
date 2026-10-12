# Codex Adapter: Runtime Layers and Mechanical Boundaries

`thaliris_codex.roles` owns native role prompts and binding facts. Inherited global
and project managed spans contain shared boundaries. Normal Controller procedures
are delivered into Controller context by the already-required bootstrap response,
sourced from the package's `controller_instructions.md`; shared inherited spans do
not inject that full routine into every fresh child. Exceptional recovery/Host maintenance and missing
context use the pinned runner's `controller-instructions --section <name>` on demand.
The bare command returns the procedure index, without the full Controller manual.
`controller-instructions --resident` returns the complete normal guidance when a
bootstrap response is interrupted or truncated. Complete guidance is enclosed by
BEGIN/END markers. Bootstrap JSON serializes the compact workspace status before
receipt metadata and the guidance body, leaving the diagnosis readable if the output
is truncated. The missing END marker still means no digest can be acknowledged. A
same-context bootstrap for another workspace may pass
`--controller-guidance-sha256 <digest>` to omit that duplicate. This acknowledgement
is caller-provided, is not inferred from emitted stdout, and is not persisted. New
sessions and fresh children do not reuse it. A changed digest or omitted acknowledgement
returns the full current guidance.
The [repository Controller document](../../docs/thaliris-controller.md) is rendered
from that source, including registry bindings. Retrieval grants no authority; other
roles may retrieve rules on demand within their existing authority.
Generated native TOMLs, role docs, Controller docs and managed project spans
are derived outputs. Edit canonical sources and render them; do not maintain a second
prompt authority. Shared semantics and research motivation live in the
[Core prompt design](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-prompt-design.md)
and [routing protocol](../../docs/thaliris-routing-protocol.md).

## Handoff and role isolation

Authorized parent native spawn carries the sole task-specific input. Core does not
construct or inject a child projection. Fresh roles use V2 fork_turns="none" or
V1 fork_context=false. The default Controller work method is delegated: a long-lived
Controller keeps direction and acceptance criteria, while fresh roles perform open-ended or repeated
investigation and stable implementation. Ordinary Controller reads, Git and diagnostics
are legal within the task boundary; delegation follows purpose and working set rather
than numeric permission thresholds. Explicit user choices of `controller-direct` and `single-agent` override this
efficiency default without changing task scope, read-only role limits or file protection.

Controller may authorize multiple independent child workstreams at once, including review
of a stable candidate while implementation waits for CI. Avoid overlapping writes in one
shared worktree; actual file conflicts need coordination, while separate worktrees support
independent changes. There is at most one pending unbound dispatch reservation per Task ID
to avoid ambiguous association, but multiple successfully bound children may be running
concurrently. A reservation belongs only to its Task ID. Native capacity does not expand
delegation authority. Maximum managed depth is two. Ordinary repository work may use an
exact native Agent-to-Task mapping or an active handoff with a known role. Missing noncritical
session, turn or profile fields remain `UNKNOWN`; by themselves they do not block ordinary
work or qualify managed control. Provided identity contradictions block dependent actions.
A known read-only role remains denied Bash/MCP mutations even when Authority or optional
fields are incomplete. Current real Host stability of identity fields across SubagentStart
and PreToolUse is UNKNOWN; synthetic event tests do not prove a Host protocol guarantee.

An active child may receive follow-up evidence or correction within its existing Workstream.
Communication cannot change its role or task goal. After a child returns FINAL, new work
uses a fresh child rather than reusing the ended executor. Native child status is execution
evidence, not semantic acceptance or task disposition. A supported native `Completed`
observation can establish execution termination; `SubagentStop` remains optional, and Stop,
wake signals or child prose alone cannot prove termination. Missing or malformed evidence
keeps status `UNKNOWN`. The Controller can explicitly cancel or abandon the associated task
through its bounded path without claiming child `Completed`; preserve possible shared-write
conflicts and fence late results.

Core `task-close` checks that the selected task is active and that its expected revision
and optional Task ID match, then records `DONE`; it does not inspect the candidate's product
behavior. The Codex adapter can also enforce identity-bound native `Completed` and the absence
of unresolved managed work when its lifecycle rules require those facts. That is execution
qualification, not product acceptance. The Controller integrates the original objective,
acceptance criteria and available evidence to decide whether product work is complete, and
whether to route repair, request useful extra verification or record mechanical closure. A
Reviewer is an optional independent read-only challenge. No closing handoff or new Agent is
required. Test `PASS`, Reviewer `READY`, native `Completed` and mechanical `DONE` remain distinct.

Core `task-promote` stores only Controller-selected Markdown records under `.agent-memory/`.
Records require `id`, `path` and `text`; `title` defaults to the ID and `source_refs` defaults
to an empty list. They create new non-INDEX Markdown files; Core refuses to overwrite an existing
durable target. Optional legacy `status` is opaque. Text is limited to 16,384 characters and
source references to 64. The promotion transaction uses current Task ID and task revision CAS.
Promotion records cannot target `.milestones/`, though an optional INDEX update can target
`.milestones/INDEX.md`. INDEX updates are full-content replacements; Core checks the expected
digest, allowed path and links, while the Controller or selected Curator supplies the semantic
content.

V1 wait_agent status maps use the exact spawned agent ID; V2 list_agents status
entries use canonical task names. Both establish execution evidence without
requiring V2 or another completion check. The accepted Completed payload is exactly
the one-key `{"completed": <string or null>}` variant. Null supplies no result text.
Other value types, extra-field and otherwise unsupported payload shapes remain
UNKNOWN. Contradictory native statuses block operations that depend on that child evidence,
not unrelated ordinary reads or independent work.
An unbound spawn can be recovered only from exact
trusted name-bound native failure or spawn-failure callback, not timeout/not_found.

First continue independent work that should take priority, then decide whether a necessary
dependency needs waiting. This applies at every authorized parent layer, including an
Implementer, Focused Implementer or Reviewer waiting for an Investigator Scanner; each
observes only direct dependencies. Executors own observation of their tests, processes
and CI, using the corresponding tools' actual waiting capabilities. A parent waits only
for an unfinished necessary direct child when no higher-priority work remains. After a
complete handoff, children advance without parent patrol and report completion, key
blockers, decision-changing discoveries or necessary upper-level decisions. Child FINAL
or a decision-changing unknown ends that slice.

Event-driven waiting takes precedence. First confirm the current Host's actual tool
maximum, meaningful-event early return, user interruption and child notifications;
unconfirmed capabilities remain UNKNOWN. When event early return and user interruption
are confirmed and there is no interim decision, normally use the supported 60-minute
window (`timeout_ms=3600000`). This is a maximum window; meaningful events can wake the
parent early. Shorten it only for a necessary brief stage check, such as 60 seconds for a
very short task, 10–60 minutes for an ordinary task, or about 30 minutes for a long-task
stage check. These are contextual recommendations for necessary stage checks or unreliable
early return, not hard limits. Follow actual tool limits and explicit applicable higher-
level limits; do not change or bypass Host behavior to extend them.

Native terminal events, ordinary child messages, timeouts, exceptions and UNKNOWN are
distinct evidence. Messages and timeouts do not prove completion; exceptions do not
fabricate terminal evidence. Do not substitute `sleep`, patrol, progress pollers or
per-child timed loops for meaningful events. After timeout, reassess necessary direct
dependencies and available independent work. A wake-only V2 `wait_agent` result is not
completion evidence; use one exact native status check after a meaningful wake. Proved
completion needs no second confirmation. The Hook preserves caller wait arguments and
does not automatically extend or take over a timeout. Tests, builds, CI and external
processes use their corresponding tools' actual waiting capabilities, not `wait_agent`
parameters; the Controller does not duplicate those observations. Waiting windows are
not execution deadlines.

Production Hook/maintenance diagnostics emit only allowlisted failed boundary labels
on stderr: receive, decode, JSON syntax/shape, dispatch, maintenance-contract and
runtime-identity. Stdout decisions stay separate. No payload, credential, raw contract
or exception contents are serialized, and diagnostic sink failure cannot alter refusal.
Labels describe observed boundaries, not an inferred root cause. Hook input still uses
strict utf-8-sig: one document-leading BOM is accepted; repeated or misplaced
signatures outside JSON content and malformed UTF-8 retain their prior rejection
behavior. U+FEFF inside valid JSON strings/field names remains exact content.

## Enforcement and assurance

Project bootstrap `READY` means definitions are available, not that a Host actor is authenticated. An explicit Controller-selected UTF-8 contract (`human_instruction`, `boundary`, `invariants`, `acceptance`, and optional `execution_mode`, defaulting to `delegated`) admits task intent without requiring a bootstrap receipt or one-shot Hook bearer. Optional legacy proofs remain strictly checked when supplied. The contract is governance, not universal authentication; Host Root assurance remains `UNKNOWN`.

Every Task ID owns its state, Authority anchor, child bindings, lifecycle reservations and recovery evidence. A new task gets a new ID and can start while an older task remains `ACTIVE`, `UNKNOWN`, has an orphan reservation, or has damaged Authority. It does not inherit old state from a matching repository path. The current session is associated explicitly by Task ID; `task-associate` records navigation with an Authority digest/revision CAS and leaves Host actor assurance `UNKNOWN`. Hooks use that mapping or an exact Task ID selector. Missing or damaged Authority blocks only managed control operations that depend on it; ordinary work, bounded reads and diagnostics remain available. `task-status` is a bounded routing observation; `task-show` is available for explicit diagnostics.

Task intent is an external governance anchor; Host Root identity can remain UNKNOWN.
Known child/readonly/fenced identities cannot establish or expand authority. Children
cannot mutate Controller state or start an unauthorized child. Reviewer/Verifier readonly
is instruction plus obvious-write guard, not a native sandbox. Execution-role extra reads
are telemetry; selected notice roles produce bounded aggregate notices. INVALID_STATE
denies recognized control mutations while other diagnostics/source work stays available
under the role router. No degraded branch grants child duties to Root.

Authority recovery preserves the selected task's recorded bytes/security baseline and
fences known children; it cannot bless changed security or unfence. `task-recover-state`
requires `--task-id` or a `--session-id` already associated with that task. An unselected
legacy singleton is visible only to read-only diagnostics; explicit legacy recovery never
auto-adopts it, and unselected bytes remain untouched. Reviewed offline recovery uses the
Task ID in its exact recovery packet and retains its revision/hash/CAS, original bytes and
disconnected-integration requirements; it cannot restore or release a different task.
An extractable fenced native ID may create missing agent-to-task navigation or reuse an exact
existing mapping for the same Task ID; it cannot grant managed qualification. Foreign,
malformed or directory-valued associations reject recovery rather than being overwritten.
See
[task authority](../../docs/thaliris-task-authority.md) and
[runtime recovery](../../docs/thaliris-runtime-recovery.md) for exact operations.

Maintenance replay follows the task/session association already present in its payload.
It does not infer an association from an old workspace `ACTIVE` task or another task's
fence when the session is unassociated; Host immutable intent is checked independently.

Ordinary native profiles omit model and effort, allowing native spawn, configuration
and user selection while retaining role instructions and readonly boundaries. Historical
fixed profiles remain fixed in a running Host until a separately authorized update is
loaded. Astra selection requires current-task human opt-in; Hook restrictions on known
child selection do not mechanically prove that human authorization. Astra variants preserve role
identity and require current-task human authorization before Controller selection.
Luna-only freezes task constraint/profile/config identities, forbids Astra, and checks
Host-reported child model; missing/mismatch stays unbound and later tools are denied.
SubagentStart cannot prevent the already invoked model call. Project .codex/agents
shadows remain rejected with EXECUTION_PROFILE_PROJECT_SHADOW; tracked copies are
review fixtures, not an admission exemption. Exact historical generated bytes migrate
by filename-bound hashes; unknown edits stay user-owned. Duplicate/damaged managed
markers fail closed and surrounding global/project user content is preserved.

Disk snapshots/registration do not prove loaded Host instructions, CLI overrides,
role catalog or native wire equality. Current-session activation and unknown new-role
identity remain explicit UNKNOWN/fail-closed observations. Do not substitute a config
snapshot for native activation proof. One Codex Desktop probe on CLI
`0.155.0-alpha.9.2` recorded a nested Investigator/Scanner start, matching lifecycle
child hashes in SubagentStart/PreToolUse, the Scanner result and the Focused
Implementer's continuation. The [2026-09-25 nested Scanner probe record](../../docs/codex-nested-scanner-live-20260925.md)
preserves that evidence and its limits: it does not establish native child `Completed`,
raw Host wire-byte equality, or behavior across other builds and workspaces. This probe
and Desktop list observations do not validate every Host build or the Desktop task-close
path.

## Supported source and installation closure

Host install, upgrade and uninstall follow [the public maintenance contract](../../docs/thaliris-host-maintenance.md): actual human intent selects the exact Host operation and immutable executor/candidate, independently of project generation and task admission. Prior authorized installation receipts establish ownership; candidate rendering, matching markers and manifests do not. Unknown bytes are preserved. Legacy migration requires independent installation evidence or specific exact-byte human approval. Supported cleanup and normal reinstall preserve user configuration and recovery evidence. All identity/isolation/ABI/ownership/control checks precede Host writes, including profiles.

Project bootstrap preserves unknown role documentation as manual follow-up; unknown authority/security/activation control blocks remain fail-closed. An exact project managed span can be approved separately with init's --accept-managed-instruction-sha256. A Host maintenance grant does not approve it. Restart when required and observe native admission/catalog status; disk equality and Host hook trust are distinct from activation proof.

Ordinary closure owns broader regression/build/docs/generated sync, installation and
Git after Focused semantic convergence. Installation/smoke exposing a semantic defect
requires a new Controller decision about reopening the core candidate. This source
change has no live Host activation or compression benchmark claim.

## Host-wide model-catalog maintenance

The native model catalog is Host-global configuration: `model_catalog_json` points to a
managed catalog in `CODEX_HOME`, shared across models and projects. It is separate from
generated Thaliris role profiles. The explicit `codex-install` maintenance contract
covers installation, upgrades and intentional low-frequency refresh; online data is the
default, while bundled data requires explicit selection. Do not treat a managed copy or
a normal CLI self-export as a newly fetched upstream catalog. An existing online catalog
is not silently downgraded to bundled data.

The `native_model_catalog` receipt binds the managed path, prior-absence state, exact
managed fragment, catalog hash and source evidence. Catalog receipts use an explicit
v2 capability marker; the current reader accepts valid legacy v1 receipts and an
authorized install/upgrade migrates them, while an older reader rejects v2 instead of
ignoring the managed field. Management removes only the exact full-line sentence in its
source-specific model context. Missing, moved, rewritten, split/partial, embedded or
repeated targets fail compatibility and preserve the prior catalog. A source refresh
that produces identical output writes no catalog, configuration or receipt bytes.
Online/source failures preserve the existing generation before transition writes; a
user-owned catalog may be preserved while other authorized Host work proceeds, with
`catalog_goal_met: false` and manual follow-up. Changes use the existing version journal.

An install contract may explicitly bind project-loss recovery to a selected project
root and optional source root. At a real Host `SessionStart`, the validated pinned
runtime restores only the exact owned `model_catalog_json` field to its prior absent
state after the selected activation marker/source is gone and the receipt field and
catalog digest still match. The physical backing catalog is never deleted. Legacy
receipts without a recovery policy and detected changed or unproven user bytes remain
preserved. Uninstall archives exact ownership evidence; a later upgrade may reclaim a
retained catalog only from a matching committed archive or a completed restoration
receipt, with the configuration field absent. Recovery records restoration provenance
only after it removes the exact owned field. If the field is already absent without
prior proof, it reports `RECOVERY_PROVENANCE_UNKNOWN` and does not authorize reclaim.
A successful restoration-backed upgrade clears that receipt marker. See the
[model-catalog maintenance report](../../docs/model-catalog-maintenance-report.md).
The accepted transaction boundary preserves user changes observed by the final
byte comparison and keeps the backing catalog file. A non-cooperating writer can
still race between that comparison and atomic replacement; this limit is disclosed
and is not a pending decision.

Catalog provenance, version admission, receipt/recovery details, and the distinction
between disk writes, the running process, and sessions already in progress are recorded
in the [model-catalog maintenance report](../../docs/model-catalog-maintenance-report.md).
The current source gate accepts only `codex-cli 0.162.0-alpha.17.2`; its opt-in runtime
capture reached a local mock with the installed CLI and observed catalog/request behavior.
That capture does not prove a fresh online fetch or activation in a user's live process,
and it records two separate native fork/resume delivery limitations.
`HostIntegration=ready` and matching disk bytes do not prove catalog compatibility or
effective session activation; those observations remain independent and may be
`UNKNOWN`. This source change does not perform live Host maintenance.

The [native execution contract](../../docs/codex-native-execution-design.md) preserves
feature defaults. V2 event waiting signals mailbox activity; list supplies exact
names/statuses. Native messaging/completion is used only for concrete needs. No new
scheduler, polling loop, execution-state mirror or World State Hook API is introduced.
