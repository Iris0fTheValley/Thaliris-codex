# Codex native execution contract

The Controller owns human intent, task direction, boundaries, context selection,
evidence admission and semantic acceptance. Codex owns native execution identity,
status, messaging and completion observations. Neither a native Completed status
nor an adapter ledger accepts the meaning or quality of a child result.

Inherited global/project managed spans contain shared authority, isolation and
readonly boundaries plus entry pointers. Controller procedures are explicitly
retrieved before their relevant operations, from the installed pinned runner's
`controller-instructions --section <name>` command or the selected section of the
repository Controller document. The bare command returns a small procedure index. This is
contextual relevance, not secrecy: other roles may retrieve rules on demand within
their authority. Native developer instructions contain only the selected role's
responsibilities and working methods. Fresh V2 `fork_turns="none"` or V1
`fork_context=false` and the authorized
parent's selected native spawn handoff remain the task-specific input boundary;
inherited AGENTS snapshots cannot be undone with ThreadInstructionsProvider.

The adapter retains independent authority and exact handoff/identity bindings and
records naturally returned native observations. Exact-identity native Completed for
the latest authorized top-level handoff, with no pending or active descendants,
establishes execution closure. SubagentStop is retained when observed; absent or
delayed Stop cannot veto already proved native completion. Stop alone cannot prove
native terminal execution. Conflicting identities, unbound children, malformed or
missing native terminal evidence fail closed. Controller-direct auxiliary children
use the same execution distinction. Controller acceptance remains independent.
V1 `wait_agent` returns a status map keyed by the exact spawned agent ID; V2
`list_agents` returns canonical-name status entries. Neither requires a second
confirmation once completion is proved. The accepted Completed payload is exactly
the one-key `{"completed": <string or null>}` variant. Null proves execution closure
but supplies no semantic result. Other value types, extra fields and unsupported
payload shapes remain UNKNOWN. Wake-only V2 waits supply no status evidence.
A contradictory native status also blocks new
managed handoffs and closure.

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

Controller procedures are retrieved explicitly; they were moved, not deleted. Counts
cover Thaliris-owned surfaces, not a measured full Host/session prompt or model-quality
benchmark. Default/constrained prior profile renderings, managed span and role packs
were replayed from immutable predecessor source; exact tracked default bytes matched.
Edited historical bytes remain user-owned. Live Host activation was not exercised.
