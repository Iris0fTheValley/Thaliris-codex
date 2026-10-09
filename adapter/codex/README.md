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
V1 fork_context=false. Controller
routes registered roles; only Implementer, Focused Implementer and Reviewer may delegate
one active/pending nested Investigator doing Scanner work under the one active/pending
top-level child. The Scanner slot is simultaneous, not a lifetime quota; after proved
terminal completion it can serve another necessary uncovered gap in the same boundary.
Native capacity does not expand that authorization. Maximum managed depth is two; exact bound
parent agent/role/session/turn is required. Missing/conflicting identity fails closed.
Exact identity-bound native Completed establishes execution completion independently of
optional SubagentStop observations. Missing/delayed Stop cannot block proved completion;
Stop, wake signals and child prose alone cannot prove it. The latest authorized
handoff/identity relation and no pending/active descendants are required for close,
including Controller-direct auxiliary handoffs. Unbound/conflicting identities and
missing/malformed native evidence fail closed. Controller accepts result meaning and
quality independently; native Completed never supplies semantic acceptance.
V1 wait_agent status maps use the exact spawned agent ID; V2 list_agents status
entries use canonical task names. Both establish execution evidence without
requiring V2 or another completion check. The accepted Completed payload is exactly
the one-key `{"completed": <string or null>}` variant. Null supplies no result text.
Other value types, extra-field and otherwise unsupported payload shapes remain
UNKNOWN. Contradictory native statuses block new managed handoffs and closure.
An unbound spawn can be recovered only from exact
trusted name-bound native failure or spawn-failure callback, not timeout/not_found.

Choose waiting by current capability, meaningful event and necessary dependency, with
native notifications preferred. Tool maximum is capacity, never a required duration;
higher-level limits take precedence. The Hook preserves caller wait arguments rather
than promoting them to a capacity limit. Executors observe/wait on their own tests,
processes and CI, reporting substantive changes or terminal evidence; Controller waits
for the necessary child result without duplicating the same observations. No status-only
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

Project bootstrap `READY` means definitions are available, not that a Host actor is authenticated. An explicit Controller-selected UTF-8 contract (`human_instruction`, `boundary`, `invariants`, `acceptance`, and `execution_mode`) admits task intent without requiring a bootstrap receipt or one-shot Hook bearer. Optional legacy proofs remain strictly checked when supplied. The contract is governance, not universal authentication; Host Root assurance remains `UNKNOWN`.

An intact ACTIVE anchor reconnects without fresh session proof. Missing contract, historical ACTIVE state without an anchor, and known child/readonly/fenced/retired or conflicting state cannot admit or expand authority. Native execution association remains exact and separate from semantic acceptance. `task-status` is a bounded routing observation; use `task-show` only for explicit diagnostics.

Task intent is an external governance anchor; Host Root identity can remain UNKNOWN.
Known child/readonly/fenced identities cannot establish or expand authority. Delegated
ACTIVE Root uses native coordination and explicit trusted-command allow-set. Children
cannot mutate Controller state or resume another native child with follow-up/send tools.
Reviewer/Verifier readonly is instruction plus obvious-write guard, not a native sandbox.
Execution-role extra reads are telemetry; selected notice roles produce bounded aggregate
notices. INVALID_STATE denies recognized control mutations while other diagnostics/source
work stay available under the role router. No degraded branch grants child duties to Root.

Authority recovery restores recorded bytes/security baseline and fences known children;
it cannot bless changed security or unfence. Reviewed offline recovery while integration
is disconnected archives evidence and releases only the old slot under operator-asserted
administration. It supplies no Host identity/task-start exemption. See
[task authority](../../docs/thaliris-task-authority.md) and
[runtime recovery](../../docs/thaliris-runtime-recovery.md) for exact operations.

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
