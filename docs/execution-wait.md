# Deterministic observation of owned execution

`thaliris_codex.execution_wait` runs one foreground command or observes one
selected GitHub Actions attempt. Local waiting, output collection and unchanged
CI responses stay inside that operation. It has no model client, agent runtime,
daemon, database, scheduler, Desktop subscription or automatic thread resume.
It does not establish task authority. Invoke it only for work already authorized
by the selected task and Host execution boundary. The caller owns observation;
the Controller still judges semantic acceptance.

## Identity and receipts

Pass a UTF-8 JSON identity file with these fields:

```json
{
  "task_id": "selected-task-id",
  "repo_root": "/absolute/canonical/worktree",
  "cwd": "/absolute/canonical/worktree/nested-directory",
  "commit": "0123456789012345678901234567890123456789",
  "run_id": "selected-operation-id",
  "attempt": 1,
  "parent_id": "selected-parent",
  "child_id": "selected-executor",
  "owner_id": "selected-observation-owner",
  "kind": "process",
  "repository": ""
}
```

Paths above are placeholders; Windows uses canonical absolute Windows paths.
The runner verifies the actual Git top-level, HEAD, canonical paths and Git
worktree metadata directories before starting. It rechecks those associations
before publishing an operation result. If the HEAD, repository root or worktree
association changes, the receipt keeps the process/CI evidence as
`observed_outcome` but reports overall `UNKNOWN` and does not report success for
the current candidate. This recheck does not snapshot dirty or untracked file
contents: `workspace_bytes` remains `UNKNOWN`, even when the commit and worktree
association match. Identity labels select evidence and never grant authority.
Do not infer exact workspace bytes from a matching commit.
Do not invent managed task, parent or child identifiers. Use a fresh receipt
directory per observation attempt, preferably in an ignored local directory or
temporary storage. Reusing
an existing directory fails without replacing it. Receipts and output can contain
private application data; keep them out of commits.

The module has a standalone CLI using the project's selected Python environment:

```text
python -m thaliris_codex.execution_wait run --identity identity.json --receipt NEW_DIRECTORY -- python -m pytest tests/test_selected.py
python -m thaliris_codex.execution_wait run --identity identity.json --receipt NEW_DIRECTORY --timeout 600 -- python -m build
python -m thaliris_codex.execution_wait inspect --identity identity.json --receipt EXISTING_DIRECTORY
python -m thaliris_codex.execution_wait cancel --identity identity.json --receipt EXISTING_DIRECTORY
```

`stdout.bin` and `stderr.bin` preserve owned output. `state.json` is an atomic,
fsynced receipt with exact correlation, exit code and output completeness. One
final JSON result appears on stdout. `--stream` mirrors progress to stderr for a
visible terminal; it may cause Host output yields. Otherwise progress is available
in the output files without periodic model turns. An explicit timeout is an
operation deadline and returns `TIMED_OUT`; internal 100 ms cancellation checks
are local implementation work, not model wakeups.

Cancel publishes an exact-identity request; only the still-running observer can
terminate its owned execution. `CANCEL_REQUESTED` does not prove termination.
Ctrl-C records `INTERRUPTED`. Neither route looks up or kills a PID from disk.
On Windows, `CreateProcessW` receives a `PROC_THREAD_ATTRIBUTE_JOB_LIST` and
explicit inherited standard handles: the new process belongs to a fresh unnamed
Job Object before its user code executes. The non-inherited job handle uses
kill-on-close and prohibits breakaway. Cleanup terminates this job and queries
its active-process count; only zero yields `CONFIRMED_JOB_EMPTY`. Setup failure
never falls back to an uncontained Popen. Handle closure also kills the job if
the observer is forcibly exited. Commands must be finite operations; descendants
are cleaned up when the root command ends, including successful root exit.
See Microsoft's [creation attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
and [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

On non-Windows platforms the local process runner is unsupported and fails before
spawning a command. Read-only inspection and GitHub CI observation remain
available. On Windows, an unconfirmed cleanup or incomplete inherited pipe is
explicit in `descendant_termination` or
`output_complete`; no result claims semantic completion from process termination.
Interactive stdin is deliberately unavailable. Run an interactive tool directly
when the user must supply input.

A leftover `RUNNING` receipt is reported as `UNKNOWN` on inspection. It does not
prove observer/process liveness. Recovery is manual: inspect output, reconcile
the exact original tool session, then explicitly decide whether to rerun in a
new receipt directory. No process or Desktop child is automatically resumed.
The helper cannot guarantee receipt publication after a hard Host/process kill.

## GitHub Actions

Set `kind` to `github-actions`, `repository` to the exact `owner/repository`, and
`run_id` to the numeric workflow run ID. The selected checkout commit must equal
the intended CI commit. Use the existing `gh` authentication; no credentials are
accepted in identity files or printed by the transport.

```text
python -m thaliris_codex.execution_wait github --identity ci-identity.json --receipt NEW_DIRECTORY --interval 30
```

The transport reads the full run and the specific attempt's paginated jobs using
the [official GitHub REST endpoints](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt).
It validates repository, run ID, SHA and attempt; job evidence additionally
requires matching run ID, SHA and `run_attempt`. Missing fields fail closed.
Repeated observations are retained as `DUPLICATE`; unchanged running responses
do not return to the model. `events.jsonl` retains observations and dispositions.

Full-run `completed` returns `RUN_COMPLETED`, including failed/cancelled runs.
Its `conclusion` must be inspected: CLI zero exit means a completed observation,
not a successful CI conclusion. Confirmed job `failure`, `timed_out` or
`action_required` returns `JOB_DECISION_EVIDENCE` before the run completes.
Run `waiting` or `action_required` returns `INTERVENTION_REQUIRED` for handling;
it does not assert the specific cause is an approval. Ordinary output containing
the word `error` has no effect. Unsupported statuses, transport errors and malformed
evidence return `UNKNOWN`. Each request has a 30 second transport bound; cancellation
is observed between requests. Cancel/timeout stops local observation and does not
cancel the remote run.

An old attempt's late success is rejected, including after a new attempt starts.
There is no shared latest-result slot for old observations to overwrite. Terminal
state is immutable within an observer. All results retain `semantic_done: false`.

## Host tool integration and measured boundary

Installed Executors can discover the mechanism with the installed pinned runner's
`execution-wait` command. `execution-wait --tool-source` returns JSON with the
packaged JS source and its digest; it does not install or activate profiles.
The canonical helper is `execution_observation.TOOL_SOURCE`, pinned as part of
the Python package. `tools/owned_tool_wait.js` is generated by
`tools/sync_instruction_sources.py`. This keeps the helper within existing
runtime identity and reviewed Python source boundaries.

Load only a successful response from the selected pinned runner:

```javascript
// @exec: {"yield_time_ms": 120000, "max_output_tokens": 1200}
const loaded = await tools.exec_command({cmd: selectedPinnedRunnerSourceCommand,
  max_output_tokens: 7000});
if (loaded.exit_code !== 0) throw Error("Helper unavailable; use native tool before launch");
const packet = JSON.parse(loaded.output);
if (!packet.ok) throw Error("Helper retrieval failed before launch");
const observeOwnedCommand = new Function(packet.source + "; return observeOwnedCommand;")();
text(await observeOwnedCommand(tools, selectedAuthorizedExecArgs,
  {expectedLong: true, finite: true, noninteractive: true}));
```

Select this only for an already authorized, expected-long, finite operation whose
new session belongs to this call. The helper selects one native invocation for
short, interactive/TTY or unsupported work; its `mode: NATIVE` result retains the
original tool observation for normal handling. It cannot attach to a pre-existing
or unowned session. Unavailable retrieval on older installations also falls back
to the native tool before execution. Once a command may have started, observation
errors return `UNKNOWN` with its original session; they never trigger a restart.
These flags grant no task, actor, sandbox or cancellation authority.

The same public command forwards `execution-wait run|github|inspect|cancel` to the
foreground Python observer with its existing identity/receipt options. Exact
durable cancellation and checkout/CI correlation remain unchanged. Bare retrieval
needs no task admission and writes no state. Operational actions keep the normal
CLI Host-transition refusal. No wait helper can suppress an outer Host yield.

Use `tools/owned_tool_wait.js` inside a `functions.exec` isolate. It owns only the
session returned by its own `exec_command`, repeatedly awaits `write_stdin` in
that same JS execution, and returns terminal/error/intervention evidence. It
checks session consistency, bounds in-memory output and preserves a manual
recovery entry on `UNKNOWN`. The foreground Python helper supplies complete
durable output; the JS buffer alone is not a complete output archive.

Set the outer `functions.exec` pragma to a supported long yield, for example:

```javascript
// @exec: {"yield_time_ms": 120000, "max_output_tokens": 1200}
// Include waitOwnedCommand from tools/owned_tool_wait.js in this isolate.
const result = await waitOwnedCommand(tools, {
  cmd: selectedAuthorizedCommand,
  workdir: selectedWorktree,
  yield_time_ms: 30000,
  max_output_tokens: 1000
});
text(result);
```

In this selected Host, a controlled Python process printed progress, remained
silent for 34 seconds, then exited successfully. With outer yield 120000 ms,
`exec_command` returned session 27318 after 30.002 s and the same JS awaited
`write_stdin` for another 4.124 s. The outer tool completed once in 36.671 s:
no intermediate model return for progress or the inner session yield. An
equivalent process observed using two separate model-issued tool calls completed
in 38.428 s (session 22510, 30.002 s initial observation). These are small runtime
experiments, not a latency benchmark or a measured token savings claim.

An explicit outer yield of 1000 ms returned cell 6 while its JS kept running;
`functions.wait` retrieved terminal evidence at 14.614 s. Thus buffering alone
cannot remove an outer Host yield. If the Host returns `Script running with cell
ID ...`, resume only that exact cell with `functions.wait`; do not start a second
observer. For a still-needed operation with no intermediate decision, explicitly
request the supported long continuation instead of relying on its short default:

```javascript
// Tool call after the outer isolate yields; use its actual returned cell ID.
functions.wait({cell_id: selectedCellId, yield_time_ms: 3600000, max_tokens: 3500})
```

During the live delivery CI observation, `functions.wait` accepted 600000 ms
and held 601.0 s before returning the same running cell. A subsequent 3600000 ms
request was accepted and returned terminal evidence early after 753.9 s. These
prove the requested bounds were accepted and the latter returned on completion;
they do not prove a full-hour hold or an effective maximum. The effective maximum
outer wait, hard termination behavior, and automatic continuation after user
interruption remain `UNKNOWN`. `terminate: true` can stop
the JS isolate; it does not prove the owned external command was terminated.
Use the exact durable cancel request when the Python observer is alive.

| Measurement | Separate calls | Same JS observation |
| --- | --- | --- |
| Controlled command | progress + 34 s silence + exit 0 | same |
| Model-facing tool return boundaries | 2 | 1 |
| Tool calls observing process | exec + write_stdin | exec + write_stdin |
| Inner output | progress + terminal | progress + terminal |
| Observed wall time | 38.428 s | 36.671 s |
| Actual model calls / input / cached / uncached / output / reasoning tokens | UNKNOWN | UNKNOWN |
| Correctness | exit 0, output retained | exit 0, output retained |

The model-facing return count is observed tool topology; actual model-request and
token attribution are not available from these tool results. Synthetic tests make
zero external model requests and cannot measure token/cache/reasoning savings.
Historical session/CI token figures describe their entire selected observation
windows and must not be presented as wholly avoidable waste.

The actual checked-in JS adapter was also loaded into a `functions.exec` isolate
and used to drive the actual Python CLI for a 34 second command. It returned
`TERMINAL`, exit 0, two internal observations, `output_complete: true`, and
`semantic_done: false`; wrapper wall time was 36.781 s (42.1 s including setup
and source retrieval). Reading the durable stdout confirmed both the progress
line and final `done` line. This was a real tool/CLI composition test.
That composition preceded the Job Object improvement. The current Windows path
is verified by real root/descendant cancellation: wait for the descendant's ready
file, request exact-identity cancellation, confirm `CONFIRMED_JOB_EMPTY`, confirm
the descendant cannot write its marker after releasing a post-cleanup gate, and confirm a separately owned
unrelated control process remains alive. The focused test also covers failure to
establish ownership without launching an uncontained fallback. A separate real
CLI observer is forcibly terminated after its descendant becomes ready; the
test waits for that exact live fixture descendant's synchronization-only process
handle to signal termination, then releases the marker gate. The marker stays
absent and the surviving receipt is reported
as `UNKNOWN` with manual recovery. This proves the current Windows kill-on-close
behavior without falsely manufacturing a terminal receipt after observer death.
Both fixture gates replace a readiness-relative sleep that could expire before
cancellation was scheduled on a loaded CI runner. The production cleanup code
was unchanged by this test synchronization repair.

The read-only GitHub transport was exercised against completed public run
39178233725, commit `379f60a9af3e6fae817b0f87403ef54c16011152`, attempt 1.
The attempt jobs response had seven jobs with matching `run_id`, `head_sha` and
`run_attempt: 1`. Running-to-terminal, duplicates, interleaved attempts and early
job failure transitions are controlled provider-shaped fixtures, not a live CI
transition experiment. A later live delivery observation watched repository
`Iris0fTheValley/Thaliris-codex`, commit
`dca15c5ce677d8fc7a8917b2f0cdb9cbe777c6d3`,
[run 39219576557, attempt 1](https://github.com/Iris0fTheValley/Thaliris-codex/actions/runs/39219576557)
from `in_progress` to `completed` / `success`. Its 67 snapshots comprised seven
changed running observations, 59 duplicates and one terminal observation over
2241.203 s. The checkout association was verified again at finish; workspace
bytes remained `UNKNOWN` and `semantic_done` remained `false`.

The actual JS adapter made nine inner observations (`exec_command` plus eight
`write_stdin` calls). The outer operation returned to the model five times:
four running-cell yields and one terminal return. Inner tool calls are not
model requests. Long continuation reduced re-entry, but four forced Host yields
still occurred and information-free re-entry was not eliminated. Model call and
token attribution for this live observation remain `UNKNOWN`. See the
[delivery report](codex-native-wait-upgrade-20261019.md) for the combined evidence.

## Native children and app-server boundary

This module does not wrap `collaboration.wait_agent`: collaboration tools are
not exposed in the `functions.exec` tools object. Current Host schema advertises
a 3600000 ms maximum, while runtime duration and individual wake reasons require
separate evidence. Parent-selected observations establish substantive-message
early return and completion notifications during a 600000 ms wait; user
interruption and automatic Desktop recovery remain `UNKNOWN`. A message, timeout
or exception is not proof of exact native child completion. Use a semantically
usable FINAL, or one exact native status check when a wake only supplies a hint.

The [official OpenAI app-server documentation](https://learn.chatgpt.com/docs/app-server)
defines `command/exec` as a sandboxed command API and experimental `process/*` as
explicit control outside that sandbox. This implementation uses the existing
Host shell tool's permission boundary and introduces no app-server process API
or sandbox bypass. An independent app-server connection only owns its own output
stream; it is not a Desktop subscription. `thread/read`, an exited process or a
saved thread ID supplies no task authority and does not justify resuming a child.

Focused checks: `python -m pytest tests/test_execution_wait.py` and
`node tests/test_owned_tool_wait.js`. Native compatibility/managed Hook acceptance
and full package/Git regression are owned separately.

The [2026-10-19 observation compatibility report](execution-observation-compat-20261019.md)
records the packaged public entry, real fresh Implementer comparison, measured
usage increases, outer-cell termination/cancellation evidence and remaining UNKNOWNs.
