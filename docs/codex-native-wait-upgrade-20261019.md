# Codex native-hook and wait-C2 evidence (2026-10-19)

This report records selected native-hook candidate `final-C1` and the wait-C2
implementation. It answers the eight operational questions from the evidence
available in this workstream. Local test, package, process, and CI results are
mechanical evidence; `semantic_done` remains `false`, and the Controller judges
task acceptance. No source change or package install proves activation in a
production Host.

## 1. Which native binary and hook entries were inspected?

The observed Codex `0.163` binary SHA-256 was
`f6dbf48cb70f62649c645f26c87dc9bf84cc36986202dfad8e12fb5b8ca70312`.
The inspection found seven candidate Hook entries and one
user Hook entry. All seven candidate entries matched the selected exact trust
and enabled checks. The initial report of zero Hooks came from a harness that
put an invalid top-level `user_owned_extension` field in the fixture. After
removing that invalid field, the opaque user-owned bytes were checked separately
and preserved. The invalid fixture did not represent the production runtime.

## 2. Which native Hook events and call identities were exercised?

The candidate was observed handling `UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, and `SubagentStart`. Parent-turn and tool-call identity used the
exact call-path UUID. Wrong-parent, stale-turn, reused-call, and wrong
tool/call-path cases were rejected. This is the selected native candidate's
observed behavior; it does not establish universal Host authentication.

## 3. Did ordinary role instructions and model selection match?

The ordinary `Focused Implementer` instructions were effective in the observed
Host path. The selected `gpt-6.1-sol` / `high` model-and-effort pair matched the
observed route. Source pointers for this evidence are
[`docs/codex-native-compatibility-20261019.md`](codex-native-compatibility-20261019.md),
[`tests/fixtures/codex-0163-alpha10-native-c1-managed-candidate.json`](../tests/fixtures/codex-0163-alpha10-native-c1-managed-candidate.json),
and [`scripts/verify_native_spawn_runtime.py`](../scripts/verify_native_spawn_runtime.py).

## 4. What did isolated package installation and the synthetic responder prove?

Candidate Core and adapter wheels were installed into a temporary home. Three
local synthetic responses completed with zero external responses. The test
demonstrated the candidate wheel pair and fixture path; it did not exercise a
production model endpoint. The separate package smoke in this workstream builds
Core from the authoritative sibling `core/Thaliris` source and installs both candidate wheels in a
temporary virtual environment. Both normal Hatchling wheels built successfully,
and an offline, non-editable install passed five isolated module imports,
the `thaliris`, `context`, and `thaliris-release` help entry points,
the observer module's help, and `pip check`. Both package versions were `0.4.6`,
and all five inspected modules resolved inside the disposable environment.

## 5. How does wait compatibility degrade when Host support is missing?

The five Host compatibility modules did not need changes. Compatibility now
selects behavior rather than relying on a version-only gate. Wait schema and
runtime capability are checked separately; when wait support is unavailable,
the result degrades to `STAGED_WAIT` and does not prevent task spawning. JSONL
`additional_tools` remains accepted. These are source and fixture results, not
proof that a particular installed Host has loaded the candidate.

## 6. What does wait-C2 record and control?

The foreground observer runs one already-authorized local command or watches
one exact GitHub Actions attempt. It records exact task/repository/commit/run
correlation, process output, CI events, and terminal transport state. The
receipt always retains `semantic_done: false`. Before and after an operation,
the Python helper checks canonical repository and working-directory paths,
HEAD, and Git worktree metadata associations. A changed association preserves
the observed result but downgrades current status to `UNKNOWN`. Dirty and
untracked bytes remain `UNKNOWN` because they are not snapshotted.

On Windows, `CreateProcessW` assigns a fresh Job Object at creation, and cleanup
confirms the job has no active processes. The observer does not fall back to an
uncontained process. On non-Windows systems, local process launch is refused
before spawn; receipt inspection and GitHub CI observation remain supported.
Cancellation and timeouts stop this local observation and do not cancel a remote
GitHub run. See [`docs/execution-wait.md`](execution-wait.md) and the focused
tests [`tests/test_execution_wait.py`](../tests/test_execution_wait.py) and
[`tests/test_owned_tool_wait.js`](../tests/test_owned_tool_wait.js).

## 7. What wait-boundary and usage measurements are supported?

In a controlled command with 34 seconds of silence, separate model-visible
tool returns were observed twice in 38.428 seconds; one JavaScript observer
returned once in 36.671 seconds. The checked-in adapter driving the Python CLI
also returned once: 36.781 seconds of wrapper time, or 42.1 seconds including
setup and source retrieval. It preserved progress and terminal output and
reported `semantic_done: false`. These are observed call boundaries and wall
times, not a latency benchmark or proof of model-token savings.

The live CI observation later used nine inner tool observations (`exec_command`
plus eight `write_stdin` calls), and produced five model-facing tool returns:
four running-cell yields and one terminal return. Nine inner observations do
not imply nine model calls. Four forced Host yields remained, so information-free
model re-entry was not eliminated. Actual model calls and token attribution
for this observation remain `UNKNOWN`.

The same outer cell accepted `functions.wait` with `yield_time_ms: 600000` and
held 601.0 seconds before returning the still-running cell. A subsequent
`yield_time_ms: 3600000` request was accepted and returned terminal evidence
early after 753.9 seconds. This establishes accepted requests and terminal early
return; it does not establish a full-hour hold or the maximum effective wait.
The [usage example](execution-wait.md#host-tool-integration-and-measured-boundary)
uses an explicit long continuation after an outer yield.

The earlier pytest observation window was 24m21s, 45 waits, 8,132,935 input
tokens (8,112,896 cached; 20,039 uncached), and 5,773 output tokens including
2,578 reasoning tokens. The CI observation window was 49 interactions,
8,930,158 input (8,860,672 cached; 69,486 uncached), and 8,637 output including
5,433 reasoning tokens. A separate 8.83M-input CI observation ended at a
different cutoff; these windows do not support treating all reported usage as
avoidable. Actual model calls, token attribution for the controlled runs,
reasoning/cache attribution for the wrapper, and raw model tokens are `UNKNOWN`.

## 8. What happened in CI, and what remains unverified?

The pushed code milestone is
`dca15c5ce677d8fc7a8917b2f0cdb9cbe777c6d3` in
`Iris0fTheValley/Thaliris-codex` on `main`.
[CI run 39219576557, attempt 1](https://github.com/Iris0fTheValley/Thaliris-codex/actions/runs/39219576557)
was observed live from `in_progress` to `completed` / `success`, bound to that
exact repository, commit, run and attempt. The foreground observer retained 67
snapshots: seven changed running observations, 59 duplicates, and one terminal
observation over 2241.203 seconds. Its final status was `RUN_COMPLETED`, conclusion
`success`, checkout association `VERIFIED`, workspace bytes `UNKNOWN`, and
`semantic_done: false`. Full CI success is mechanical evidence for the configured
Windows/Linux Python 3.11/3.12/3.13 matrix; it does not decide semantic acceptance.

Provider-shaped fixtures separately cover duplicate responses, interleaved
attempts, early job failures, and checkout changes. The live observation adds a
real running-to-terminal transition; it does not certify every fixture branch
against the provider. This report fixes the verified code milestone above;
the final documentation commit and its CI result are reported separately in the
delivery response rather than changing this file to chase its own commit hash.

Local related regression passed 369 tests with one POSIX-only test skipped on
Windows. This is one non-overlapping invocation across execution waiting,
native wait capability, Host compatibility, single handoff, native spawn
identity, managed acceptance, and native execution contracts. The Node adapter
test passed separately. These counts do not add earlier overlapping runs.
Windows process tests run only on Windows; the actual POSIX refusal test runs on
POSIX, where process launch must remain unsupported.

The selected Host advertised a 3,600,000 ms maximum native wait. Requested
600,000 ms and 1,800,000 ms waits were accepted; selected waits returned early
on meaningful messages and completion. User
interruption, automatic Desktop resumption, hard outer termination behavior,
and actual model/token counts remain `UNKNOWN`; the maximum was not exercised.
The production runtime differs from the candidate source. No production update
was installed, so production activation remains `UNKNOWN`. The selected
requirements are `R-WAIT` and `R-DELIVERY`; the candidate receipt is not an
acceptance decision or authorization to install or activate Host changes.
