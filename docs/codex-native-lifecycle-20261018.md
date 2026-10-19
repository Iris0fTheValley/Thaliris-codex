# Native lifecycle contract observed on 2026-10-18

The isolated `codex-cli 0.162.0-alpha.17.2` experiment used disposable Codex
homes, workspaces and an immutable candidate runtime. It did not change the
production Host configuration, inspect UI state, or tail session files. The
official app-server connection corroborated its requested `CODEX_HOME` through
`initialize`. CLI disk/process identity does not establish Desktop activation.

## Exact dispatch identity

The current V2 spawn Hook result is a JSON string containing only `task_name`.
`SubagentStart` supplies the child's `agent_id`, `agent_type`, root `session_id`
and child `turn_id`; it does not echo the parent spawn call or handoff. A single
pending reservation, a task path, profile, nickname or event ordering therefore
cannot prove the dispatch-to-child edge.

The official `thread/items/list` API supplies that edge. Within the actual
spawn `PostToolUse` callback, a read of the exact parent native thread and Hook
turn returned:

```json
{
  "turnId": "<parent Hook turn_id>",
  "item": {
    "type": "subAgentActivity",
    "kind": "started",
    "id": "<spawn Hook tool_use_id>",
    "agentThreadId": "<SubagentStart agent_id>",
    "agentPath": "<returned task_name>"
  }
}
```

The candidate requires exactly one matching item, the expected turn, valid native
UUIDs, a `started` activity and consistent returned navigation. It reads all
pages of that selected turn without status polling, model calls or a lifecycle
subscription. The task name is a consistency check; the native call ID and
`agentThreadId` establish identity. Missing, malformed, duplicated, conflicting
or unavailable evidence leaves the reservation pending and the child unbound.
The historical experiment used this exact CLI version. The current reader now
accepts the same corroborated edge independently of CLI version; initialized home
mismatches remain refused. See the [2026-10-19 compatibility update](codex-native-compatibility-20261019.md).

Normal task ownership, immutable task association, exact parent/profile/session/
turn/call checks, abandoned/fenced refusal, model constraints and collision checks
still apply. Nested Investigator dispatch resolves the already bound live
parent's native thread; it inherits that handoff's selected provenance. The
legacy exact `{agent_id, nickname}` spawn response remains an independent V1
identity source. Start and Post may arrive in either order; neither path grants
authority from an uncorroborated Start, including in a fresh owner session.

Status callbacks carrying native call identities must match an allowed
PreToolUse recorded by that same Task ID, actor, session, turn, tool and call.
Reused sessions require this correlation even when a callback omits fields.
An old task's delayed list/wait/interrupt/close result cannot acquire the new
task's reservation merely by reusing its task name. Missing correlation stays
UNKNOWN; legacy sparse status fixtures remain limited to unreused sessions.

## Observed tool surfaces

| Surface | Current observation | Interpretation |
| --- | --- | --- |
| Spawn | `task_name` only, inside JSON string `tool_response` | V2 navigation; resolve exact official activity edge |
| Wait | `message`, `timed_out` | Wake/timeout only; no completion proof |
| List | `agents[]` with `agent_name`, `agent_status` | Exact known navigation status; never an independent child binding |
| Interrupt | `previous_status` | Observe that status; `not_found` does not prove closure |
| Followup / send message | Empty string response | No identity or completion evidence |
| Start / Stop | Native child ID, type, root session, child turn | Start needs dispatch corroboration; Stop is optional observation |
| Close | No current tool exposed in the experiment | Current activation and shape remain UNKNOWN; legacy parser is not current evidence |
| `updatedInput` | Supported input rewriting, independently observed for this CLI | Does not supply an echoed native child identity; production activation remains separate |

Historical V1 status maps remain parsed separately from V2 wake-only responses.
They are compatibility fixtures, not observations of current V2 execution.

Following a completed child reused through `followup_task`, the actual CLI
emitted child `PreToolUse` with a new turn and no second `SubagentStart`. The
candidate records this new execution risk without changing the old handoff's
turn or granting fresh permissions. Old thread snapshots cannot close that
unidentified execution. A new selected task still requires fresh delegation.

Doctor reports Start observation separately from `managed=true` /
`handoff_bound=true`, records the latest privacy-safe decoded shape for each
tool, and does not derive spawn/schema support from a wait-capability pin.
Observed wire, source compatibility, installed definitions and current-session
activation remain distinct.

## Evidence and limits

`tests/fixtures/codex-0162-alpha17-native-contract.json` retains the observed
field shapes, generated official schema excerpts, original artifact digests and
the matching call/child identity hashes. It omits payload text, paths and raw
native identity strings. Unit tests use explicitly synthetic identities and
controlled reader responses; they do not claim live Host activation.

Disposable managed CLI acceptance verifies legal child writes, child and nested
Scanner `task-observe`, exact parent lineage, wait/list completion observation
and separate fresh/reused owner tasks. The privacy-safe receipt in
`tests/fixtures/codex-0162-alpha17-managed-acceptance.json` verifies four managed
children and four correctly attributed observations in two tasks sharing one
native root session; the immutable runtime's three changed Python modules match
the candidate source bytes. Deterministic tests challenge stale calls,
wrong actor/profile/session/turn, missing evidence, collisions and native thread
reuse. Other CLI versions, production Desktop activation and a turn-specific
completion subscription remain UNKNOWN. No production Host install is performed
by this change.

The same receipt separately records a controlled callback replay against the
candidate runtime. It used the digest-identified Hook capture for its field shapes
and the exact official activity item, with captured root-session, parent-turn,
spawn-call, child-actor and task-path hashes correlated in memory. After a fresh
same-name Task B reservation, replayed Task A spawn, Start, list, wake, interrupt
and Stop callbacks left B's reservation, handoff evidence, Core state and authority
byte-identical; no A actor gained B authority, wrong call/turn/session/profile
variants did not bind, and a readonly Investigator write was denied. This was a
deterministic replay, not another naturally emitted stale race or a replacement
for the real fresh/reused acceptance above. The capture retained only hashes for
the child turn, list call, selected message and response text, so those fields
used disposable substitutions; the non-managed probe profile was replaced by a
supported focused-implementer profile. The receipt records source artifact
digests and these substitutions without raw IDs, payload text or private paths.
