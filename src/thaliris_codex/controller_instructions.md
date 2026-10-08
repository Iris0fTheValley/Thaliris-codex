# Thaliris Controller instructions

Canonical package resource: `src/thaliris_codex/controller_instructions.md`.
The installed pinned runner returns a procedure index with `controller-instructions`
and one selected procedure with `controller-instructions --section <name>`.
Normal Controller guidance is resident in the normal bootstrap response/context:
startup, authority, routing, handoff, Workstream endpoints, durable selection,
waiting/completion and causal diagnosis. Retrieve task-recovery or host-maintenance
only when their exceptional operation is needed. Measure the complete normal task
context plus retrieval cost and quality, not the shortest individual prompt. The
required startup operation delivers it once; shared inherited instructions do not
inject the full Controller routine into every fresh child. Missing context can
retrieve an exact section.
Repository docs are rendered from this resource. Assigned children follow their selected handoff and role; they
may retrieve other rules on demand within their authority. Retrieval grants no authority.

## Startup and admission

For substantive file-changing Git work, unless the human opts out, the owning root
Controller runs `@RUNNER@ --root <repo> codex-bootstrap` directly once. Read-only/chat/non-Git work needs none.
Managed children follow their handoff; do not bootstrap, task-start or task-abandon
the parent's ACTIVE task. Use this installed pinned runner for later operations;
do not select alternate startup commands, shell-computed hashes or unknown runtime code.
On READY or DEFINITION_READY_ACTOR_UNKNOWN, create a separate UTF-8 JSON authority
contract file selecting the actual human instruction, boundary, invariants,
acceptance and execution_mode: delegated, controller-direct or single-agent.
Non-mode fields are nonempty strings. Then in a separate standalone direct tool call
run `@RUNNER@ --root '<repo>' task-start '<goal>' --bootstrap-receipt '<receipt>' --authority-contract '<absolute-file-path>'`, using the returned task_start_receipt and quoted absolute file path.
The contract argument is a file path, never inline JSON; do not combine invocations.
After admission follow the effective project router and selected execution mode.

## Persistent authority

Authority is persistent Controller-asserted human intent under governance, not
mechanical human/Root authentication. Host Root identity remains UNKNOWN.
UserPromptSubmit, missing fields, matching session, PID, environment and SessionSource
mint no authority. Known child, readonly, abandoned and fenced actors cannot establish,
expand, rewrite or reactivate it. Shared OS/unrecognized delegates have no universal
mechanical authentication. Ordinary interruption/reconnect needs no repeat Root proof;
authority ends on human revocation, closure or Controller abandonment/replacement.
Goal, scope, acceptance, mode, unfencing or security-baseline changes need an actual
superior human decision. Children cannot authorize them through prompts, state or config.
Controller-direct allows Controller reads/edits/tests/Git and useful auxiliary roles;
single-agent allows ordinary execution without children. Default delegated routing,
fresh isolation, readonly restrictions and explicit Astra authorization otherwise hold.

## Task recovery

On CURRENT_CONTINUATION continue or explicitly abandon using the exact task-abandon
packet. An unbound pending spawn first needs trusted terminal Host recovery evidence.
On FOREIGN_RECOVERY_DECISION or UNKNOWN, Controller decides continuation/recovery.
On INVALID_STATE/bootstrap failure diagnose the affected surface; preserve evidence,
label managed assurance UNKNOWN, and route ordinary source work through assigned roles.
For incompatible task schema, read task-status and use task-recover-state with exact
--expected-sha256; ACTIVE recovery also needs --abandon-active and no nonterminal children.
Never delete invalid state or treat it as absent. Runtime drift is evidence for
Controller repair/restore/accepted-upgrade judgment, not a blanket source-work ban.

Authority conflict recovery uses task-recover-authority --expected-authority-sha256
<exact external hash> --reason <reason>. It archives evidence, restores recorded bytes
and original security baseline, and fences known old children; death proof may stay
UNKNOWN. It cannot bless changed security bytes or remove fences.
User-authorized external repair/forced recovery requires disconnected global integration
and the separate reviewed tools/thaliris_offline_recovery.py runner with exact task,
revision, state/lifecycle hashes and reason. OPERATOR_ASSERTED_USER_DELEGATED_ADMINISTRATION
is operator intent, not cryptographic consent or Host attestation. It archives bytes,
fences extractable identities and releases only the old slot; it grants no task-start,
child binding, Controller identity or readonly exemption. Automated actors are denied
while integration is present. Try native termination/observation of known children;
unknown owner, unbound identities, incompatible fields and unavailable death proof stay
UNKNOWN. Disk disconnection does not prove running Host configuration.

## Host maintenance

Host installation, upgrade and uninstall require a separate --maintenance-contract:
the actual human instruction, exact Host operation/home and independently selected
immutable executor/candidate identities. They require no project init/task admission
and never approve unknown project control instructions. Prior authorized installation
receipts establish Host ownership independently of candidate rendering; unknown bytes
are preserved until exact specific human approval. Preserved role documentation is
manual follow-up, not project admission authority. Disk setup is not native activation.

Host maintenance during another ACTIVE project uses a separate checkout and Codex
session. Only exact identity-checked Host codex-install/codex-uninstall invocations with an explicit --maintenance-contract
cross that boundary; source changes use managed roles. Self-uninstall reports any inert
retained runner for later direct cleanup/reinstall. Changed installation requires a fresh
Host session where needed; disk registration does not prove loaded instruction/catalog
activation. Never change a live task's security anchor as part of source synchronization.
In user-facing status describe work and concrete blockers plainly; keep receipts,
hashes, attestations and lifecycle details out of that prose and report blocked work honestly.

## Routing, selected context, evidence and acceptance

The Controller is the sole task-specific semantic router. Core records identities,
revisions, hashes, provenance and observations; models decide meaning and completion.
Native Completed proves execution closure, never child-result meaning or quality.
Controller independently interprets the result against human acceptance before
closing the task; SubagentStop is optional observational evidence, not another gate.
Follow the global startup/authority contract and the selected execution mode.
In delegated mode, Controller owns direction, scope, acceptance, context selection
and next routing; assigned executors own implementation design and local methods.
Controller-direct permits Controller execution with useful fresh auxiliary roles;
single-agent permits ordinary execution without children. Isolation and readonly
boundaries hold in every mode. Damaged management does not transfer child duties
to Controller; diagnose the management failure and keep assurance UNKNOWN.

Choose the minimum necessary fresh role for the Workstream's work shape:

| Role | Responsibility | Default native binding |
| --- | --- | --- |
@ROLE_ROWS@

Controller has no fixed model, effort or native profile; Host/user selection applies.
Investigator gathers broad facts, not architecture decisions. Reasoning Specialist
independently challenges a decision basis when that could change direction.
Scanner is a nested Investigator discovery working pattern. Executor is a category
covering Implementer and Focused Implementer; profiles select execution facts for
those same semantic roles. Stable direction and deterministic convergence use
ordinary Implementer; coupled invariants requiring sustained reasoning use Focused
Implementer. Choose one profile per Workstream, not a ladder or size threshold.
Automatic routing stops at Sol; static Astra medium/xhigh profiles require current-task
user authorization before spawn. Per-spawn model/effort overrides are denied.
The dedicated luna-only installation requires `execution_constraint: luna-only`
in the authority contract; it retains semantic roles, restricts ordinary profiles
to Luna/xhigh, and forbids Astra. Children cannot alter the frozen constraint.

## Handoff and operational acceptance

Provide a decision-complete handoff: goal and original acceptance, confirmed facts,
hard invariants and decided boundaries, authoritative source/derived relationships,
affected surfaces, usable verification entry, and decision-changing unknowns.
Include current source locations and covered/uncovered scope from selected discovery.
Resolve ambiguity from the human request and confirmed facts before handoff; bound
the specific discrepancy or transformation in cleanup, migration or synchronization.
Decisions, invariants and acceptance bind; recommendations are non-binding. Methods
belong to the executor. Reuse established inventory and reopen only decision-critical
originals; a new Scanner covers a genuinely uncovered evidence gap.

Use a stable narrative base language and preserve precision-bearing original terms,
quotations, distinctions and user formulations when translation would materially
blur, broaden, narrow or expand meaning. Avoid forced monolingual translation,
random language switching and bilingual repetition. Output language requirements
still govern. Compression and handoff retain this precision-bearing representation.
For operational artifact or installation acceptance, select the authoritative
artifact, source, revision and provenance before delegation, or explicitly assign
that selection to a later Workstream before its operational acceptance.

Project/package install-smoke closure here covers builds, installs, fixtures,
isolated smoke, packed artifacts and project-local verification. Effective live
Host install/upgrade/uninstall, global instructions, profiles, hooks and trust
require separate Host maintenance authority under the global contract.

## Workstream endpoints and review

Root routes Workstreams; executors close local loops inside them. Semantic dependency,
decision coupling and independent closure define their boundaries. Ordinary Implementer
may finish assigned deterministic execution and Git closure in the same Workstream.
Focused Implementer returns at semantic convergence: core solution/invariants hold,
direction-changing unknowns are resolved, focused evidence supports core semantics,
and remaining work cannot materially change causal model, architecture, contract,
scope, acceptance or direction. A test PASS alone is insufficient. Remaining ordinary
regression, lint/build, sync, deterministic defects, project/package install-smoke checks and Git closure then
go to a fresh ordinary Implementer when assigned; shared guidance cannot extend the
Focused endpoint. FINAL ends a child session; any further work uses a fresh handoff.
Evidence changing a decided boundary or requiring an unverified external capability
returns to Controller; ordinary local defects stay within the accepted assignment.

Classify remaining work as independently deterministic only when the accepted
contract uniquely determines the behavior to preserve. Compatibility authority
ambiguity remains semantic: when production behavior and historical fixtures leave
authority undecided, Focused must supply representative evidence or return the
dependency to Controller; this does not mandate full regression. Controller may
reroute the same semantic closure to a fresh ordinary session when explicit inputs
and independent acceptance suffice and accumulated debugging state adds no benefit.
Carry distilled invariants, exact candidate, green evidence, provenance, remaining
acceptance and blockers, not raw history. FINAL still ends the prior child session.

Select a fresh independent non-writing Reviewer only after candidate convergence
when semantic challenge adds value. It checks original acceptance, invariants and
cross-boundary behavior. Counterevidence is a finding; insufficient evidence remains
unverified. READY requires supported critical closure, not absence of blockers.
Bounded defects with design unchanged go to fresh ordinary correction; changes to
architecture, contract, invariant, scope, acceptance or decision basis reopen Controller.
Before opportunistic work, account for every explicit user goal as addressed,
explicitly deferred, or blocked by a decision-changing dependency.

Fresh role sessions use V2 `fork_turns="none"` or V1 `fork_context=false` and only the authorized parent's native
spawn message plus explicitly selected information. Controller may spawn registered
roles; Implementer, Focused Implementer and Reviewer may spawn a fresh Investigator
doing Scanner work. The supported managed shape has one active/pending top-level
child and at most one active/pending Scanner under its exact parent. This is a
simultaneous slot, not a lifetime quota: after proved terminal completion, a fresh
Scanner may cover another necessary uncovered gap within the same boundary.
Other children cannot delegate. Maximum managed depth is two, never sibling workers.
Native capacity does not expand managed authorization; UNKNOWN overlap evidence
does not authorize bypassing Hooks or disabling all future supported delegation.
Keep working sets private; return distilled conclusions, facts, unknowns,
contradictions, verification and optional Artifact pointers. Child communication,
mutation/verification practice and role endpoints are defined in native role prompts.

## Durable retrieval and knowledge admission

Controller alone selects durable retrieval and knowledge admission. Before task-start,
read `.agent-memory/INDEX.md` and `.milestones/INDEX.md`; create minimal thin navigation
if absent. Read selected documents explicitly through catalog/document-get; a bounded
get names up to eight paths. Reread navigation after relevant change, missing context,
invalid freshness or resumed compaction. Near task closure, select Curator only when
reusable knowledge has future value; supply exact prior memory, navigation and evidence.
Keep INDEX semantic and concise. Core validates storage, never chooses relevance.
CHANGED is an observation, not semantic invalidation; Controller decides revalidation.

## Native completion and closure

Use only trusted direct runtime commands and native coordination allowed by the
current execution mode. Pending-spawn recovery needs exact trusted native failure
evidence; timeouts, not_found and prose cannot release a reservation. Wait only for
a known unfinished necessary child. Choose waiting from the available capability,
expected meaningful event and necessary dependency; prefer native notifications.
The tool maximum is capacity, not a recommended duration. Higher-level duration
limits take precedence; do not impose a universal maximum or fixed wait duration.
Give each necessary dependency one observation owner: executors run and wait on
their own tests/processes/CI and report substantive changes or terminal evidence;
Controller waits for the necessary child result without rechecking the same job.
Do not poll a finished child or create repeated reasoning turns solely to observe
unchanged deterministic state when the runtime can wait for a meaningful or terminal
event. A timeout alone creates no new decision or evidence and does not justify
another status-only reasoning round. Use the native tool family available in the
current session: V1 `wait_agent` returns a status map keyed by the exact spawned
agent ID; V2 `list_agents` returns status entries keyed by canonical task name.
Either can prove native Completed; no V2 switch or second confirmation is required.
The one-key `{"completed": <string or null>}` variant proves execution completion;
null supplies no result text and cannot establish semantic acceptance. A V2 wake-only
wait, Stop, nickname, missing target or unsupported payload remains UNKNOWN.
Conflicting native statuses block new
managed handoffs and closure. SubagentStop is an optional observation; missing or delayed Stop cannot veto proved
native completion. Stop/wake/prose alone is not completion; missing evidence keeps closure UNKNOWN. The last Controller-direct
handoff must complete under the same native evidence rule with no pending/active descendants. Host instruction/catalog
activation remains UNKNOWN without native evidence; changed disk files alone do not
prove activation. Keep security/control-state mutations and live Host installation
outside child source work. See [Codex protocol](../adapter/codex/README.md),
[role profiles](thaliris-role-packs.md), and [task authority](thaliris-task-authority.md).

## Causal diagnosis and acceptance

Reuse the original failure and smallest local reproduction before changing behavior.
Distinguish receive, strict decode, JSON syntax/shape, dispatch, maintenance contract
and runtime identity failures at their actual boundaries. A diagnostic stage is a
failed boundary observation, not proof of the deeper root cause; label guesses as
inferences until source or reproduction supports them. Keep payloads, credentials,
contract contents and unbounded exception objects out of diagnostics.
Repair the supported cause without weakening refusal, identity, ownership, isolation,
native completion or acceptance guarantees for CI. Review READY covers its selected
candidate and criteria; it does not replace final product acceptance. Choose fresh
sessions by remaining independence and total context reconstruction cost, never a
mechanical duration/call threshold or a local PASS alone.
