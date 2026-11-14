# Codex Adapter: Runtime Layers and Mechanical Boundaries

Instruction distribution follows ownership: child profiles carry selected local
responsibilities, semantic endpoints, evidence and facts needed for their tool actions.
Controller resident guidance owns the full task, model/role/context selection,
successor routing and product acceptance. Adapter/lifecycle binds identity,
provenance, task, role, handoff and workchain; children do not reconstruct these
associations or the global requirement graph. Detailed Host waiting and compatibility
protocols remain in this reference and Controller guidance; delegating roles retain
event-driven direct-dependency behavior. A usable child FINAL informs semantic
judgment without another lifecycle wait; native completion and Core closure remain
separate mechanical facts.

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
Bootstrap accepts an explicit existing project directory without Git metadata and
never runs `git init`. Existing Git worktree root selection remains compatible.
Git HEAD/surface observations are locally unavailable without Git; Git evidence
freshness is UNKNOWN. Managed admission, persistent task intent and exact actor
navigation retain their existing authority checks. A parent native cwd does not
select a nested managed project by scanning descendants: exact actor associations
select it, and ambiguous or stale associations fail closed.
For a standalone recognized CLI call, one literal `--root PATH` or `--root=PATH`
selects among the session's already validated repository associations before cwd
preference. It cannot add an association or override an exact child's repository.
Missing, duplicate, expanded or conflicting roots do not supply navigation or
authority; normal task, role, owner and fence checks still apply.
For a relative shell `workdir`, the Hook resolves a relative `--root` against the
payload's stable `cwd`, so routing the same request through both Hook boundaries
does not append the workdir twice.
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
than numeric permission thresholds. Explicit user choices of `controller-direct`, `single-agent` and `adaptive` override this
efficiency default without changing task scope, read-only role limits or file protection.
`adaptive` adds no hook restriction beyond the default: the Controller may execute
directly and may dispatch any registered role.

Controller may authorize multiple independent child workstreams at once, including review
of a stable candidate while implementation waits for CI. Avoid overlapping writes in one
shared worktree; actual file conflicts need coordination, while separate worktrees support
independent changes. There is at most one pending unbound dispatch reservation per Task ID
to avoid ambiguous association, but multiple successfully bound children may be running
concurrently. Parallel dispatch is user-directed: a `parallel_dispatch` authority contract
lets the owning Controller's own top-level spawns hold several reservations at once.
Non-writing roles (Investigator, Reasoning Specialist, Reviewer and any non-writing
registered role) need no workstream and are never refused for count or overlap; a writing
role names one declared write workstream in the handoff (`thaliris-workstream: <id>`). The
adapter adds no count of its own: a missing `budget` is uncapped, and a stated one counts
live top-level writing dispatches. Domain disjointness is the one mechanical boundary: a
write workstream whose declared `scope` overlaps a live write workstream (whatever its
domain label), or that has no usable scope while another write workstream is live, is
refused with `THALIRIS_PARALLEL_DOMAIN_OVERLAP`; read work never conflicts. The Controller partitions the work into non-overlapping domains. A
workstream may be reserved again once its previous dispatch is terminal or disposed. Every
reader (close, mode switch, diagnostics, disposal, recovery, the wait guard and the degraded
preflight) treats each reservation as pending, and SubagentStart binds only the reservation
whose native identity matches exactly. `worktree` is not enforced. Nested spawns never use
the contract or a workstream; the one-Scanner-per-parent and one-unbound-dispatch rules apply
to them unchanged. Core 0.6.0 contract validation still requires a `budget` (1 to 256, at
least the number of workstreams) and rejects overlapping scopes within one domain, read
workstreams included. A reservation belongs only to its Task ID. Native capacity does not expand
delegation authority. Maximum managed depth is two. Ordinary repository work may use an
exact native Agent-to-Task mapping or an active handoff with a known role. Missing noncritical
session, turn or profile fields remain `UNKNOWN`; by themselves they do not block ordinary
work or qualify managed control. Provided identity contradictions block dependent actions.
A known read-only role remains denied Bash/MCP mutations even when Authority or optional
fields are incomplete. The isolated `0.162.0-alpha.17.2` CLI observation corroborated
SubagentStart and child PreToolUse identity; other Host/session behavior remains UNKNOWN.
Synthetic event tests do not prove a Host protocol guarantee.
The [2026-10-21 compatibility record](../../docs/codex-native-compatibility-20261019.md)
separates its alpha.11 V2 loopback Hook evidence from the real Luna run, whose
child turn completed but whose managed Start binding remains UNKNOWN.

Managed Start binding requires a corroborated native child ID even for a fresh owner.
Current V2 `task_name` results supply navigation only. The adapter reads official
`thread/items/list` for the exact
parent native thread and spawn turn: a unique `subAgentActivity(kind=started)` item
must have `id` equal to the Hook's spawn `tool_use_id` and a valid `agentThreadId`.
The initialized home must match; a CLI version is provenance rather than admission.
Optional `model` and `reasoningEffort` fields record routing match, mismatch or UNKNOWN
independently of identity and authorization. The returned path is checked for consistency without becoming identity proof. Missing
or conflicting evidence leaves the child unbound. The legacy exact `{agent_id,nickname}`
response remains supported independently. No session-file tail, UI reader, polling,
model call or production Host configuration mutation supplies this edge. See the
[observed native lifecycle contract](../../docs/codex-native-lifecycle-20261018.md).

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
and optional Task ID match, withholds while a declared check is not green unless
`--override-reason` is recorded, then records `DONE`; it does not inspect the candidate's
product behavior. The Codex adapter protects residual execution and authorization risk: pending,
running, unknown or conflicting identities/statuses block closure. Exact native terminal
evidence resolves execution without requiring complete historical handoff/Start/Stop
records or success of the latest handoff. No issued child requires no child proof,
including in delegated mode. The Controller integrates the original objective,
acceptance criteria and available evidence to decide whether product work is complete, and
whether to route repair, request useful extra verification or record mechanical closure. A
Reviewer is an optional independent read-only challenge. No closing handoff or new Agent is
required. Test `PASS`, Reviewer `READY`, native `Completed` and mechanical `DONE` remain distinct.

Evidence continuity uses Core append-only records, not a lifecycle or approval state machine.
Controller registers opaque requirements and selected handoff edges using
`task-evidence-register --role controller --base-revision N --input FILE`.
The input contains `requirements: [{id, workchain_ref}]` and
`handoffs: [{id, parent_handoff_id, candidate, producer, requirement_refs}]`.
For new work, Controller preselects the next top-level managed dispatch in that same
registration operation (or after requirements are already registered):
`"next_dispatch":{"role":"investigator","expected_agent_type":"thaliris-investigator","candidate":"C1","requirement_refs":["R1"]}`.
The existing task lock and authority protect this one selection. The Hook supplies the
Controller's existing session association. A matching owning Controller reservation
consumes it once and registers the newly generated exact handoff
before Native execution, including opaque Host messages. A wrong profile/role/owner or
conflicting readable marker refuses without consuming it; nested children inherit their
already associated parent's provenance and cannot consume the top-level selection.
Only the owning Controller withdraws an unconsumed selection, with
`"cancel_next_dispatch":{"reason":"..."}` alone or with a replacement `next_dispatch`.
The ledger keeps the withdrawn selection in `evidence_dispatch_cancellations`.
Model/effort defaults and permitted explicit overrides are independent of this metadata.
Optionally include the identical association in an own-line spawn marker
`thaliris-evidence: {"candidate":"C1","requirement_refs":["R1"]}`;
Curator may also receive exact `durable_paths`. The adapter binds provenance from existing
lifecycle/native association. Nested Scanner retains parent lineage and logical candidate,
with empty requirement refs; its marker cannot select global relevance. Controller later
cites those observations in selected requirement judgments. Register nonempty requirement
refs before a top-level spawn. Native Hosts may expose an opaque spawn message to Hooks;
an intended plaintext marker then does not establish an association. Ordinary Controller
result delivery reports bounded exact `unassociated_handoffs`. For selected work use the
existing Controller `task-evidence-register` with that native-bound handoff ID, original
parent ID, candidate, producer and selected refs for legacy/history recovery. That
postspawn recovery cannot prevent a first observation from racing association; use
preselection for new work. Do not decrypt payloads or infer
global relevance. Unmarked handoffs remain compatible, but observation persistence refuses
missing provenance; return the fact and sources for exact association instead of storing
unlinked evidence. See the [Native ownership and evidence acceptance plan](../../docs/delegated-ownership-native-acceptance.md).

### Verification-first wiring (Core 0.6.0)

Mechanism may withhold; only a model may grant. The adapter declares, runs, records,
withholds and surfaces. It never marks a requirement satisfied, dismisses evidence or
closes a task; every refusal below is Core's and the Controller lifts it with a recorded reason.

- `task-check --role controller --base-revision N (--input FILE | --json '<object>') [--supersede]`
  declares checks. It is Controller-only: the hook denies it to every child, and the CLI
  refuses another role. The declaration is checkpointed like `task-judge`.
- `task-verify --role ROLE --check ID [--base-revision N]` runs one declared check. The
  Controller runs it as `controller`. A bound managed child runs it under its own role;
  PreToolUse adds its exact `--task-id`, `--handoff-id` and `--agent-id-hash`, and the CLI
  requires that exact live binding again before and after the run, recording the result as
  producer `handoff:<id>`. Read-only roles may run it; a redirect or other visible write on
  the same command line is still denied. Core runs the argv outside the task lock; the
  adapter then re-checks the authority anchor, appends the result and checkpoints the anchor
  in one locked transaction, so a ledger edit made during the run is an authority conflict.
- `task-judge --override-reason TEXT` and `task-close --override-reason TEXT` pass the
  reason to Core's withholding gate. A refusal is `VERIFICATION_WITHHELD` and writes nothing.
- Requirement `kind` and `surface` travel in the existing `task-evidence-register` payload.
- `task-status` passes the authority contract to Core, so an adaptive task shows
  `Advisories`. It stays read-only and never records tamper; verify, judge and close do.
- SubagentStop: after the exact child match (agent, profile, session, turn, managed) the
  adapter gives `last_assistant_message` to Core's claim ingest for that child's registered
  handoff, under the task lock, and checkpoints the anchor. A message without a block, or
  no message field, leaves Core's `missing` marker; no claim is invented. A disposed or
  identity-conflicted child, and a handoff with no evidence association, ingest nothing.
  Terminal reconciliation (`wait_agent`, `list_agents`, `interrupt_agent`, `close_agent`)
  ingests a `{"completed": <text>}` status only when the text holds a `thaliris-claims`
  block. Ingest is idempotent. Any ingest or write failure becomes the bounded
  `claim_ingest` diagnostic on the lifecycle child record and a `Claims.ingest_errors`
  packet entry; the hook itself never fails.
- Usage is recorded on the handoff at the same two points and at dependency disposal:
  `model` from the child's own Stop payload, `effort` only from an explicit spawn argument,
  `duration_ms` from the reservation time to the first observation, and `outcome`
  (`completed` or `failed` only from an exact native terminal status, `disposed` from a
  disposal, otherwise `unknown`). No hook payload carries tokens, cost or tool-use counts:
  those fields stay null.
- Adaptive tasks only: each owning-Controller PostToolUse adds `ceil(len(tool_response)/4)`
  to Core's lane counter sidecar, which changes neither the revision nor anchored bytes.
- The PostToolUse packet and Controller write responses carry bounded `Verification`,
  `Claims` and `Advisories` lines. A not-green or uncovered check, a handoff without a
  readable claim block and an advisory are shown even when no observation is open.

Claim ingest and usage move the selected ledger to task-state schema 9 at the first child
Stop, including for a task that declares no check; an older Core refuses schema 9 as newer.
Whether a live Host delivers `last_assistant_message`, and what a terminal `completed`
string contains, are Host facts this repository cannot establish: they remain `UNKNOWN`.

### Common command errors

- **`TASK_OBJECT_NOT_FOUND` from `task-get`.** `task-get` takes the exact ID of one
  current-task object. The selected Task ID chooses the ledger; it is not an object ID.
  When the requested ID is the selected Task ID, Core keeps the stable error code and
  `details.id`/`details.matches` and adds a recovery hint. Use `task-status` to review the
  selected task, `task-show` for explicit diagnostics, then retry `task-get` with the
  current object's exact ID. A different missing ID keeps the bounded not-found response;
  no broad object search is performed.
- **`dispatch selection or reservation already pending`.** Read the selected task's
  existing state before retrying registration. The owning Controller may withdraw an
  unconsumed selection with
  `task-evidence-register --role controller --base-revision N --json
  '{"cancel_next_dispatch":{"reason":"..."}}'`. That operation cancels only the
  unconsumed `next_dispatch` selection. Resolve an existing pending spawn reservation
  through its recorded native lifecycle; do not treat it as an unconsumed selection.
- **Missing handoff association on `task-observe`.** Supply the exact selected handoff
  with `task-observe --role ROLE --handoff-id ID --observation-json '<JSON>'`. If that
  handoff has no evidence association, return the observation and sources to Controller;
  Controller registers the exact native-bound handoff association with
  `task-evidence-register`. Do not substitute the Task ID or infer a handoff ID.
- **Invalid `task-close --role` or guidance section `task-close`.** The supported command
  is `task-close --base-revision N`; the Hook supplies the selected role and task binding.
  For Controller procedure retrieval, use the exact section name
  `controller-instructions --section completion` (or `--section task-recovery` for that
  procedure). The available section names are listed by `controller-instructions`.

For the historical cases and their evidence limits, see
[`codex-history-errors-20261111.md`](../../docs/codex-history-errors-20261111.md).

When an already discovered fact changes local conclusion, local acceptance or critical UNKNOWN,
record it with source refs and selected provenance. This adds no search duty, global-importance
judgment, model call or acceptance gate. `task-observe --role ROLE --observation-json '<JSON>'`
uses the existing Hook binding to supply its exact Task ID, `--handoff-id ID --agent-id-hash HASH`.
Read or validate selected sources in a separate read-only tool call, then invoke the installed
runner directly for the observation. Terminal newlines are supported; variables, script wrappers
and compound shell statements do not receive the direct invocation's identity rewrite.
The Hook carries a literal JSON object as UTF-8/base64 within that same option before
native shell dispatch; the CLI decodes it inside `task-observe`. This preserves quotes,
backslashes and Unicode through Windows PowerShell and the pinned `.cmd` runner, and
keeps control-looking payload text separate from executable shell syntax. Pass ordinary
JSON, for example `--observation-json '{"id":"O1","text":"local fact","source_refs":["S1"]}'`.
PowerShell single-quoted literals double embedded apostrophes (`Native''s`); POSIX uses
normal shell quoting. JSON `\u0027` also works. The Host must apply `updatedInput`.
PowerShell inline commands conservatively refuse raw smart quotes U+2018–U+201F;
use JSON Unicode escapes such as `\u2019`. POSIX literals retain these Unicode characters.
Executable syntax outside the payload retains readonly/control-state checks. Existing
direct JSON and correctly native-escaped argv remain supported.
Readonly children need no payload file write; `--input FILE` also accepts an existing file. Its minimal body is
`{"id":"O1","text":"local fact","source_refs":["S1"]}`. If S1 is not already registered, add
`sources: [{"id":"S1","kind":"local","locator":"tests/result.txt","summary":"exact output"}]`.
Source refs must be nonempty and resolve to sources. The adapter fills candidate, handoff and
requirement refs from the selected binding; conflicting explicit fields are rejected.
No Controller revision CAS is required. A child's `id` and the ids of its embedded `sources`
(with `source_refs` to them) are prefixed with its handoff id (`HANDOFF_ID.O1`), so parallel
children may all report `O1`; an already-qualified id is kept and the response lists the stored
`appended` ids. The stored id is bounded to 64 characters, so local ids stay short. A Controller
historical import keeps its chosen id. `task-status` is compact by default (routing header,
counts and the Core open-evidence summary: totals always, a bounded item list paged with
`--evidence-offset N`); `task-status --view full` returns the full Evidence Continuity page and
`--since-revision N` adds a bounded, non-exact `Changes Since` review hint. `task-get` retrieves
exact records. Controller state-operation outputs carry the same compact `evidence` summary
(not the full page), also on successful closure. Child observation acknowledgements do not
receive unrelated global evidence bodies.
Controller writes are strict compare-and-set. A stale `--base-revision` is refused with
`error: "task revision conflict"`, `code: TASK_REVISION_CONFLICT` and `details.current_revision`
plus `details.changes_since` (revision gap, newer records, recent handoffs/observations/judgments
and the open-evidence summary); review it and retry once with the current revision. Other Core
errors expose `code`, `recovery` and `details` beside the unchanged `error` text.
`task-update`, `task-evidence-register` and `task-judge` accept `--input FILE|-` or one inline
`--json '<object>'` (single-quoted literals use the same Hook UTF-8/base64 transport as
`--observation-json`; a `utf8-base64:` value is also accepted).
`task-judge --role controller --base-revision N --input FILE` records `id`, `candidate`,
`requirement_ref`, exact `observation_refs`, `outcome` and `reasoning`. The input is one judgment
or an atomic ordered batch `{"judgments":[...]}` (1 to 64) committed in one revision. Outcomes are
`satisfied`, `unknown`, `repair` and `no-current-impact`. An observation retains its immutable
logical handoff candidate label C1, not a spawn-time repository identity; source refs and
optional producer-selected `observed_state` identify the local observation (otherwise actual
state identity is UNKNOWN). A judgment may assess it against current candidate C2 with reasoning
about its present applicability. Read/ack is not incorporation; incorporated unknown/repair
remains unresolved. Prior records survive handoff, update and close as history; mechanical
DONE does not decide current requirement satisfaction.

Judgments may include exact prior `judgment_refs` for the same requirement. Controller
explains how it addresses that prior basis without reciting its full observation history.
Unaddressed model-authored repair/unknown basis remains in `unresolved_judgments` even
after a later satisfied judgment cites only fresh observations. Complete legacy recitation
of the earlier observation basis also establishes a mechanical continuity link.
Ordinary Controller PostToolUse results reintroduce the bounded evidence summary, the current task
revision and local excerpts before the next broad completion judgment. This uses existing result delivery, no polling,
fixed final stage or semantic close gate. Children never receive that global packet.

Explicit task admission/association publishes exact actor navigation beside external task
authority. From a parent native cwd, the Hook validates repository-local session/agent
associations before applying the original task Authority and lifecycle checks. Multiple
nested repositories remain independent. Ambiguous/stale navigation grants no managed
binding; no descendant marker discovery chooses a repository. Generic unmanaged work
keeps its passthrough behavior. Profile compatibility uses actual native cwd layers,
including a parent workspace, rather than assuming child-repository profiles were loaded.

Controller may import selected historical child results with `task-observe --role controller
--handoff-id ID --observation-json '<JSON>'`, registering a missing exact association first.
The observation retains original native provenance and records Controller as `submitted_by`.
History import grants no child permissions, reactivation, execution completion or current truth.

`document-maintain --role controller|curator --base-revision N --input FILE` atomically
maintains exact selected Markdown documents and INDEX links. Curator also selects its
`--handoff-id ID` from the existing Hook binding. Input contains `writes: [{path, base_sha256, content}]`,
`deletes: [{path, base_sha256}]`, and optional `index_update: {path, base_sha256, content}`.
The digest is null only for a new file. Core validates path ownership, links and CAS; the
model decides whether to edit, merge, split, replace or delete selected entries. Curator
has no corpus scan, delegation, architecture/product acceptance or real-time evidence duty.

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
An exact V1 `close_agent` snapshot or V2 `interrupt_agent` previous Completed status
is also native execution evidence; a running previous status proves no completion.
Completed describes a turn, not permanent identity destruction. Closed task authority
does not reactivate when the same native identity is reused.
Other value types, extra-field and otherwise unsupported payload shapes remain
UNKNOWN. Contradictory native statuses block operations that depend on that child evidence,
not unrelated ordinary reads or independent work.
Execution-dependent checks use the native observation directly, without a second
terminal-state or stopped-state mirror. `not_found` does not prove termination and
cannot erase a prior terminal fact or a recorded contradiction.
Exact native terminal evidence retires an unbound reservation without granting managed
permissions and retains dispatch provenance against delayed Start callbacks. A canonical
V2 task name does not identify the Start's native agent ID; ambiguous association remains
unprivileged. A generic spawn error can follow native thread creation and asynchronous
cleanup; even an exact call match proves neither no child nor termination. Such errors
keep the reservation pending and cannot justify explicit pending recovery. Use exact
native terminal evidence or the existing Controller dependency disposition/fence path.
Timeout and not_found prove neither completion nor execution closure.
Status callbacks with native call IDs must match an allowed PreToolUse recorded
by the same task, actor, session, turn, tool and call. Reused sessions require this
correlation even for sparse results; an old task's delayed status cannot consume
a new reservation through a matching task name. Missing evidence remains UNKNOWN.

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

Project identity is the optional Core plane under tracked `.project-identity/` (see the
[Core reference](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-project-identity.md)). The Adapter exposes `identity-status`, `identity-get`
and `identity-trace REF` as read-only commands that need no role or task. `identity-amend`,
`identity-challenge` and `identity-relate` are Controller-only and follow `task-update`:
`--role controller`, explicit `--task-id` or an associated `--session-id`, `--base-revision N`,
`--input FILE`, a Task Authority check before and a checkpoint after an ok result; they do not
change the task revision. Hooks classify the mutations with the Controller-owned control
operations (a child session is denied) and the reads with the other read-only context
operations. When an identity exists, `codex-bootstrap` (`project_identity_summary`) and
`task-status` (`Project Identity`) give the Controller Core's one-line summary; with no identity
both outputs are unchanged, and no identity text is ever injected into children (SubagentStart
output stays empty). The identity files are not Task Authority protected paths, so a checked
amendment never changes the task security baseline. The obvious-path control-state guard also
denies an apparent direct write to the identity record files (`IDENTITY.md`, `ledger.json`,
`versions/`, `amendments/`, `challenges/`, `relations/`), for children and for the Controller;
like the other guards it is not a sandbox. Detection of any other change relies on Core's
`UNRECORDED_CHANGE`/`INVALID` status plus Git diff.

Natural formation (Core 0.5.2): `identity-note --role controller` records (`--input FILE|-` or
`--json`, `{"quote": ..., "kind"?, "context"?, "refs"?}`), retracts (`{"retract": "N-000k",
"reason": ...}`) or lists (`--list [--include-retracted]`) the user's verbatim long-term
statements; `identity-suggest --role controller --on|--off|--clear --scope
session|workspace|project|global` sets the offer preference. Both are Controller-only (children
are denied like `identity-amend`) but need neither an ACTIVE task nor `--base-revision`, and
their storage is outside the repository (`THALIRIS_HOME`, default `~/.thaliris`). A successful
`task-close` adds `identity_offer` to its result when Core has a new pending basis note and
offers are enabled (Core records it as shown, so it appears once per new note); a failure leaves
the field absent. The session key is derived mechanically: the sha256 of the global `--session-id`
when supplied, otherwise the selected task's recorded Controller owner hash (set at `task-start`),
so suggest, status and the `task-close` offer share one key without the flag; with neither,
session scope is unavailable. Raw Core `identity-offer|identity-note|identity-suggest` is denied
to children. Nothing is added to bootstrap or SessionStart.

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
Auxiliary restoration failures retain explicit stderr diagnostics and preserve
unproven bytes. After startup validation, project discovery still runs and the
original SessionStart receiver gets the exact input once, with its stdout,
stderr and exit result preserved. Runtime identity, Hook ABI, malformed native
actor input and pending Host transitions retain their startup rejection.
The accepted transaction boundary preserves user changes observed by the final
byte comparison and keeps the backing catalog file. A non-cooperating writer can
still race between that comparison and atomic replacement; this limit is disclosed
and is not a pending decision.

Catalog provenance, content admission, receipt/recovery details, and the distinction
between disk writes, the running process, and sessions already in progress are recorded
in the [model-catalog maintenance report](../../docs/model-catalog-maintenance-report.md).
### Host compatibility is capability and hook-shape based

No Codex version string decides support anywhere in the adapter. A version line is
recorded as provenance only; a missing or unparseable one is provenance `UNKNOWN`,
never a block. Support is shown by the resolved binary's behaviour and by the hook
shape it declares, so a new upstream or locally updated build needs no allowlist
entry. The binary is resolved as everywhere else in the adapter:
`THALIRIS_CODEX_EXECUTABLE`, then `codex` on `PATH`.

Catalog compatibility is based on the selected source's model roster and content. Online
freshness takes the cache key from the isolated cache's own `client_version` after the
fetch; a parsed CLI version only corroborates it, and a contradiction stays
`ONLINE_FRESHNESS_UNVERIFIED`. Catalog reuse stays bound to the binary's SHA-256, and a
`.cmd`/`.ps1`/`.js` or `#!` launcher, whose bytes do not identify the real binary,
never qualifies for reuse. The opt-in runtime capture on
`codex-cli 0.162.0-alpha.17.2` reached a local mock with the installed CLI and observed
catalog/request behavior; it does not prove a fresh online fetch or activation in a
user's live process, and it records two separate native fork/resume delivery limitations.

The separate `multi_agent_mode_hint_text` and optional Controller wait-guidance
compatibility paths have no version fast path. Every build undergoes an isolated
prompt/type capability check, and a definitive `SUPPORTED` or `INCOMPATIBLE` result is
cached in `~/.thaliris/host-capability/`, keyed by the binary's SHA-256, the config leaf
and the probe's own source. A replaced binary is probed again, `UNKNOWN` is never
cached, and a launcher script is probed each time. The check runs in a disposable
`CODEX_HOME` and workspace, using a loopback Responses sink. It does not copy the
current user's configuration or authentication. On Windows it resolves the
ProgramData known folder and checks `OpenAI/Codex/config.toml` and
`requirements.toml`; on Linux it checks
`/etc/codex/{config,requirements,managed_config}.toml`. Existing paths, lookup
errors or a platform whose managed configuration cannot be proven absent block
`exec` and leave support `UNKNOWN`; macOS managed preferences therefore remain
UNKNOWN. When clear, it passes `--disable hooks --disable plugins`; those flags
do not disable managed hooks on their own, which is why this preflight is
required. The probe CLI gets a closed stdin, because `exec` otherwise waits on an
inherited pipe. The sentinel and empty-string prompt effects are the positive
evidence that the leaf is recognised. Wrong-type rejection is shown by behaviour: the
integer run differs from the accepted runs only in that leaf and must exit non-zero
before any Responses request, and a final repeat of the accepted run must still
succeed. Error text is corroboration only; a failure that Codex attributes to an
unrelated config location is not credited to the leaf. Complete consistent evidence is
required before planning a write. Contradictory evidence reports `CAPABILITY_INCOMPATIBLE`,
while missing or ambiguous evidence reports `VERSION_SUPPORT_UNKNOWN`, a persisted
status name kept for receipt compatibility that now means "capability not shown".
Either way the user's config is preserved.

`doctor` reports `host_hook_shape`, and `codex-install` returns it as install-time
evidence. The check reads the generated hook input schemas that Codex embeds in its
binary (`codex-rs/hooks/schema/generated`) without running the binary, and confirms
that each of the seven registered events exists and declares every input key the
adapter reads. Observed multi-agent tool names are checked against the PostToolUse
matcher, and a custom `features.multi_agent_v2.tool_namespace` is flagged when the
matcher cannot select its names. The result is `COMPATIBLE`, `INCOMPATIBLE` with the
missing items, or `UNKNOWN` when no schema is observable. It is never a runtime
refusal. When a live hook payload lacks a key the adapter needs, the existing
fail-closed handling is unchanged and the session's audit records a bounded
`host_hook_shape: UNKNOWN` entry that names the event and the keys.
The [hook-shape compatibility record](../../docs/codex-host-compatibility-20261114.md)
lists the builds observed so far. They are evidence, not requirements.
Native wait capabilities are separate from these configuration probes. A selected
session's actual tool schema can establish argument limits, including a 3,600,000 ms
schema ceiling, without certifying effective duration. CLI versions do not establish
wait capability. Bounded duration, completion wake, message wake, user interruption
and automatic resume each require their own runtime evidence. Without selected schema
transport these facts remain `UNKNOWN`; effective runtime maximum stays `UNAVAILABLE`.
Unknown waiting optimizations select `STAGED_WAIT` using the native tool's ordinary
documented wait behavior and preserve normal task admission and identity checks.
The [Codex host compatibility record](../../docs/codex-host-compatibility-20261008.md)
preserves the source comparison and runtime-evidence limits.
`HostIntegration=ready` and matching disk bytes do not prove catalog compatibility or
effective session activation; those observations remain independent and may be
`UNKNOWN`. This source change does not perform live Host maintenance.

The [native execution contract](../../docs/codex-native-execution-design.md) preserves
feature defaults. V2 event waiting signals mailbox activity; list supplies exact
names/statuses. Native messaging/completion is used only for concrete needs. No new
scheduler, polling loop, execution-state mirror or World State Hook API is introduced.
