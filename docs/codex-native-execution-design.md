# Codex native execution contract

The Controller owns human intent, task direction, boundaries, context selection,
evidence admission and semantic acceptance. Codex owns native execution identity,
status, messaging and completion observations. Neither a native Completed status
nor an adapter ledger accepts the meaning or quality of a child result.

Inherited global/project managed spans contain shared authority, isolation and
readonly boundaries plus entry pointers. The owning Controller receives normal
Controller procedures in the existing bootstrap response; it does not retrieve a
section before each operation. The complete response has BEGIN/END markers; its END
marker carries SHA-256 and UTF-8 byte count. After the complete tool result and marker
are visible, the same context may pass that digest to another workspace bootstrap to
omit duplicate text. This is an explicit caller acknowledgement, not an inference from
stdout or persisted state; new sessions and fresh children do not reuse it. Use
`controller-instructions --resident` to recover a complete copy after truncation.
Retrieve an exact section with the installed pinned
runner's `controller-instructions --section <name>` only when applicable context is
missing or exceptional recovery/Host maintenance requires it. The bare command
returns a small procedure index. This is contextual relevance, not secrecy. Other
roles may retrieve rules on demand within their authority. Native developer
instructions describe the selected role's responsibilities and working methods.
Fresh V2 `fork_turns="none"` or V1
`fork_context=false` and the authorized
parent's selected native spawn handoff remain the task-specific input boundary;
inherited AGENTS snapshots cannot be undone with ThreadInstructionsProvider.

The adapter retains independent authority and exact handoff/identity bindings and
records naturally returned native observations. Exact-identity native terminal facts
resolve remaining execution risk without requiring the latest handoff to succeed or
complete historical handoff/Start/Stop records. No issued child requires no child
proof, including in delegated mode. Execution-dependent checks read native status
directly, without a second terminal-state or stopped-state mirror. SubagentStop is
retained when observed; absent or
delayed Stop cannot veto already proved native completion. Stop alone cannot prove
native terminal execution. Conflicting identities and malformed or missing native
terminal evidence fail closed. Exact native terminal facts retire an unbound
reservation while preserving its unprivileged provenance. `not_found` does not prove
termination and cannot erase a prior terminal fact or contradiction. Controller-direct
auxiliary children
use the same execution distinction. Controller acceptance remains independent. V1
`wait_agent` returns a status map keyed by the exact spawned agent ID; V2 `list_agents`
returns canonical-name status entries. A wake-only V2 `wait_agent` is not completion
evidence; take one `list_agents` snapshot after a meaningful wake. A general
recommendation to limit blocking waits to 60 seconds is not an intrinsic cap on an
event-capable native `wait_agent`; only an explicit applicable higher-level limit
imposes that bound. Otherwise choose an event-aware duration informed by expected task
length, which may be several minutes or longer. Prefer native completion events over
short polling loops and preserve responsiveness to interruptions and substantive
events. Do not substitute `sleep`, poll unchanged state after a timeout, or impose one
fixed timeout across tasks. Executors observe their own tests and CI; the Controller
does not repeat that observation. Neither native status family requires
another completion check once exact completion is proved. The accepted Completed payload is exactly
the one-key `{"completed": <string or null>}` variant. Null proves execution closure
but supplies no semantic result. Other value types, extra fields and unsupported
payload shapes remain UNKNOWN. Wake-only V2 waits supply no status evidence.
A contradictory native status also blocks new
managed handoffs and closure.

Generic spawn errors do not prove that creation failed before a native child existed.
The current native control path can fail after thread creation, and cleanup is
asynchronous and best-effort. The version-pinned sources are
[`spawn.rs`](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/agent/control/spawn.rs),
[`spawn_guard.rs`](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/agent/control/spawn_guard.rs),
and [the error mapper](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/handlers/multi_agents_common.rs).
Exact call correlation cannot distinguish those errors
from rejection before creation. Keep the authorization reservation pending; generic
`spawn_failed` records establish neither that no child exists nor that it has
terminated. Only exact identity-bound native terminal observations retire pending
reservations automatically. Without those observations, the existing Controller
dependency disposition/fence path remains available. This is a minimum authorization
association retained at the native schema boundary, not another execution state.

The native shape is sourced from OpenAI Codex
[`rust-v0.162.0-alpha.2` at `74e804deeb1241d5fe699b31fb319f7d46454c42`](https://github.com/openai/codex/blob/74e804deeb1241d5fe699b31fb319f7d46454c42/codex-rs/core/src/tools/handlers/multi_agents_spec.rs):
V1 spawn returns `agent_id` and nullable `nickname`; V1 waits return
`{status: {agent_id: AgentStatus}, timed_out: boolean}`. Display nicknames do not
bind execution identities. The shared Completed schema explicitly permits null.
This establishes source compatibility, not the payloads or catalog loaded by a
particular running Host. Unsupported live surfaces remain UNKNOWN.

Controller-selected Workstreams retain authorized self-iteration. Executors own
implementation methods and repair ordinary local defects inside their assignment.
Focused Implementer returns at semantic convergence; ordinary deterministic
closure then belongs to a fresh assigned Implementer. No fixed pipeline, polling
scheduler, execution-state mirror, mechanical semantic acceptance or artificial
method restriction is introduced. Current native spawn, list/status, messaging
and event waiting are used only for concrete needs. Feature defaults stay intact.

Canonical sources are `controller_instructions.md` in the adapter package,
`codex_adapter.py` shared-span renderers, `roles.py` role instructions and
`lifecycle.py` native observation/binding logic. The repository Controller document,
AGENTS managed span, native role TOMLs and role-pack document are rendered outputs.
Controller instruction retrieval works before project admission and during damaged
management without granting control or changing authority. Unknown user documents
are preserved; rendering does not authorize ownership or live Host maintenance.

Acceptance uses source-imported focused tests for completion without Stop, Stop
without completion, identity/handoff conflicts, pending/active descendants,
Controller-direct closure, selected-context isolation, role self-iteration and
retrieval/rendering. Prompt size comparisons measure bytes/characters, not model
quality. No Core, emergency/offline runner, live Host or experimental feature changes
are in scope for the original design. The compatibility repair uses isolated
Windows independent-maintenance tests; no effective live Host changes are made.
App-server identity, live payload fidelity/catalog activation and
completion reentry remain UNKNOWN without their own native evidence. World State
is not a callable Python Hook API; board, dynamic tools and deep AgentControl are
not dependencies of this design. No DSH parity is inferred.

## Owned prompt size evidence

Character counts against immutable predecessor `7045c7de4a490e589e49d3151b37e6ea4679f429`:

| Surface | Before | Candidate |
| --- | ---: | ---: |
| Project inherited managed span | 8,970 | 1,488 |
| Global inherited managed span | 5,500 | 1,423 |
| Implementer developer instructions | 3,448 | 2,770 |
| Focused Implementer developer instructions (Sol) | 4,594 | 3,536 |

Normal bootstrap delivers resident Controller guidance; exact-section retrieval is
for missing context or exceptional recovery/Host maintenance. Counts
cover Thaliris-owned surfaces, not a measured full Host/session prompt or model-quality
benchmark. Default/constrained prior profile renderings, managed span and role packs
were replayed from immutable predecessor source; exact tracked default bytes matched.
Edited historical bytes remain user-owned. Live Host activation was not exercised.
