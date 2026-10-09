# Codex Adapter: Runtime Layers and Mechanical Boundaries

`thaliris_codex.roles` owns native role prompts and binding facts. Inherited global
and project managed spans contain shared boundaries. Normal Controller procedures
are delivered into Controller context by the already-required bootstrap response,
sourced from the package's `controller_instructions.md`; shared inherited spans do
not inject that full routine into every fresh child. Exceptional recovery/Host maintenance and missing
context use the pinned runner's `controller-instructions --section <name>` on demand.
The bare command returns the procedure index, without the full Controller manual.
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
Controller keeps direction and acceptance, while fresh roles perform open-ended or repeated
investigation and stable implementation. A few precise reads of known evidence and an
explicit diagnostic are allowed; continuous small queries remain one investigation to
delegate. Explicit user choices of `controller-direct` and `single-agent` override this
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
conflicts and fence late results. The Controller independently accepts result meaning and
quality.

V1 wait_agent status maps use the exact spawned agent ID; V2 list_agents status
entries use canonical task names. Both establish execution evidence without
requiring V2 or another completion check. The accepted Completed payload is exactly
the one-key `{"completed": <string or null>}` variant. Null supplies no result text.
Other value types, extra-field and otherwise unsupported payload shapes remain
UNKNOWN. Contradictory native statuses block operations that depend on that child evidence,
not unrelated ordinary reads or independent work.
An unbound spawn can be recovered only from exact
trusted name-bound native failure or spawn-failure callback, not timeout/not_found.

Choose waiting by current capability, meaningful event and necessary dependency, with
native notifications preferred. Controller waits only for a known unfinished child result
that remains necessary; after child FINAL or a decision-changing unknown, that slice ends
and the Controller does not keep waiting for it. Tool maximum is capacity, never a default
duration; higher-level limits take precedence. The Hook preserves caller wait arguments
rather than promoting them to a capacity limit. Executors observe/wait on their own tests,
processes and CI, reporting substantive changes or terminal evidence; Controller does not
duplicate those observations. No status-only
reasoning round is justified by a timeout or unchanged deterministic state alone.
No new controlled comparison measures wait cost; a five-minute monitoring cadence is
only an optional observation alternative, not a current feature or requirement.

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

Native model defaults come from registry binding facts. Astra variants preserve role
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

The [native execution contract](../../docs/codex-native-execution-design.md) preserves
feature defaults. V2 event waiting signals mailbox activity; list supplies exact
names/statuses. Native messaging/completion is used only for concrete needs. No new
scheduler, polling loop, execution-state mirror or World State Hook API is introduced.
