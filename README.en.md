# Thaliris Codex adapter

Language: English | [简体中文](README.md)

This is the Codex Host adapter for [shared Thaliris Core](https://github.com/Iris0fTheValley/Thaliris), not an independent Core. It imports Core rather than bundling a copy.

The `thaliris-codex` distribution uses `thaliris_codex` and preserves the `thaliris` and `context` Codex commands. It owns native bootstrap, lifecycle, Hook trust, actor identity, doctor, recovery and generated model profiles. Core supplies the ledger, retrieval, evidence, memory and `thaliris.authority` API.

pyproject.toml declares Python >=3.11 and thaliris>=0.4.4,<0.5.

On Windows with Python 3.11+, create a disposable bootstrap environment and use
the packaged runtime installer. Select the independently reviewed full adapter
commit. When `--runtime` is omitted, setup discovers the current Codex Host's
package family and resolves its existing LocalCache directory to the physical
path before creating a candidate. A bootstrap launched outside Codex resolves
only a unique registration of the exact `OpenAI.Codex` package; missing or
ambiguous discovery fails closed. No Store internal path needs to be entered.

```powershell
py -3.11 -m venv .thaliris-bootstrap
$bootstrap = (Resolve-Path .thaliris-bootstrap\Scripts\python.exe).Path
$adapterSource = 'git+https://github.com/Iris0fTheValley/Thaliris-codex.git@<reviewed-full-40-character-commit>'
& $bootstrap -m pip install --no-deps $adapterSource
$env:PYTHONDONTWRITEBYTECODE = '1'
$runtime = (& $bootstrap -m thaliris_codex.runtime_setup --core-source 'git+https://github.com/Iris0fTheValley/Thaliris.git@56e48ac299dd2c5c4b16c992db732a55b7790893' --adapter-source $adapterSource | ConvertFrom-Json)
if (-not $runtime.ok) { throw $runtime.error }
$exe = $runtime.executable
& $exe version
```

For an intentional custom location, pass `--runtime 'D:\chosen\runtime'`; that path is still checked for final physical identity. The default creates a new uniquely named runtime under the discovered Host base.

Replace the adapter commit placeholder with the independently reviewed published revision. Host maintenance uses `codex-maintenance-plan` and an explicit `--maintenance-contract FILE`, independently of project init/task admission. Prior authorized installation receipts establish byte ownership; candidate equality does not. Unknown project role documentation is preserved without blocking admission, while unknown control instructions remain blocking. Supported uninstall and normal reinstall preserve user configuration and recovery evidence. See [Host maintenance](docs/thaliris-host-maintenance.md) for the public sequence and legacy approval boundary.


Setup resolves the automatic Host LocalCache base through an OS handle before
creating a candidate directory, then observes the final runtime directory before
creating the venv or installing packages. An explicitly redirected `--runtime`
stops with the physical path to select; setup removes only the empty leaf created
by that attempt. Preexisting or nonempty directories remain untouched. The runtime
location anchor and Windows launcher's embedded interpreter must agree with that
directory. Setup executes the ordinary final-path
`thaliris.exe runtime-check` with bytecode writes disabled, and maintenance
selection repeats that side-effect-free check before producing a contract.
Preparation, the contract and Host installation use the same final directory.
Never copy, move or rename an installed venv; recomputing a manifest cannot approve
relocation, even when the old interpreter still exists. Preserve any candidate that
fails after the redirect check, and create a new runtime directly at the correct
final location.

For local development install `../Thaliris[test]`, then this repository with `--no-deps -e '.[test]'`, and run `pytest`. The installer creates the dedicated runtime without ensurepip and installs both selected packages through the bootstrap's pip. pip, setuptools and build dependencies stay outside the runtime; no manual `.pth` repair is required. System site packages stay disabled and executable or path-extending `.pth` files remain rejected without exceptions. Verified local wheels are also accepted as `absolute-wheel-path#sha256=<reviewed-digest>`. The entire environment, including shared Core, remains pinned by the runtime manifest. Keep the pinned directory immutable; use a new directory for upgrades. Installing packages does not prove Host enablement, authorization or health.

## Starting and recovering project tasks

After Host installation, the owning Controller runs `codex-bootstrap` once for substantive Git work using the installed pinned runner and target repository. Make this a separate invocation:

```powershell
& '<installed pinned runner>' --root '<repo>' codex-bootstrap
```

`READY` (legacy `DEFINITION_READY_ACTOR_UNKNOWN` is also accepted) means project definitions are available; it does not authenticate a Host actor or prove that the current process loaded role configuration. If definitions are missing, follow the bootstrap result instead of bypassing the adapter to create a separate task ledger.

Task admission uses a separate UTF-8 JSON contract file with non-empty `human_instruction`, `boundary`, `invariants`, and `acceptance` strings, plus optional `execution_mode` (`delegated`, `controller-direct`, or `single-agent`). If omitted, the mode defaults to `delegated`: the Controller owns long-lived decisions, while short-lived Investigator/Implementer roles handle the main investigation and implementation. `controller-direct` lets the Controller read, edit, test, commit and close the work, with auxiliary roles available when useful; `single-agent` means ordinary single-agent work with no children. An explicit user choice takes precedence over the efficiency default without expanding task scope or overriding read-only role limits or protection of user-owned files.

```json
{"human_instruction":"<actual user instruction>","boundary":"<selected scope>","invariants":"<hard constraints>","acceptance":"<acceptance conditions>","execution_mode":"delegated"}
```

After creating that file, start the task in another separate invocation:

```powershell
& '<installed pinned runner>' --root '<repo>' task-start '<goal>' --authority-contract '<absolute-contract-file>'
```

In `delegated` mode, direct evidence reads through Codex's native `functions.exec_command` are limited to a one-time or very small number of related, precisely located reads. The `cmd` must be exactly one single-path form: `Get-Content [-LiteralPath] PATH -TotalCount N` or `Get-Content [-LiteralPath] PATH | Select-Object [-Skip S] -First N`, with `N` from 1 to 200; set the tool's `max_output_tokens` explicitly from 1 to 4096. The native limit bounds returned tokens, not source bytes, and long lines may be truncated, so a line limit alone is not a byte bound. Do not use an unbounded read or default Bash for this exception. Open-ended iteration, cross-file investigation, long-output analysis, and a broad investigation split across successive small queries must still be delegated. This is a mandatory Controller work rule; Hooks cannot reliably prove cumulative intent across every third-party MCP call.

Explicit contract admission does not require a bootstrap receipt or one-shot Hook bearer. If a legacy proof is explicitly supplied, the adapter still validates it strictly. The contract records the Controller's selection of human task intent; Host Root actor assurance remains `UNKNOWN`, so it is not general identity authentication. Known child, readonly, fenced, retired, or conflicting states cannot establish or expand authority. Ordinary repository work may use an exact native Agent-to-Task mapping or an active handoff with a known role; missing noncritical session, turn, or profile fields remain `UNKNOWN` and do not qualify managed control. Provided identity contradictions still block dependent actions, and a known read-only role remains denied Bash/MCP mutations even when Authority or optional fields are incomplete.

Each Task ID has its own task state, Authority, lifecycle reservations, child bindings and recovery evidence. `task-start` creates and selects a new Task ID; an older task in the same repository may remain `ACTIVE` or `UNKNOWN` without being inherited or blocking the new task. Resuming an existing task requires selecting its Task ID explicitly. The current Codex session must also be associated explicitly with `task-associate`; that operation records navigation for the Task ID and session ID with an Authority revision/hash CAS, but does not authenticate a Host actor, so Host assurance remains `UNKNOWN`. Hooks use only an explicit mapping for the current session/agent-task or an exact Task ID selector; repository path alone does not choose the current task.

The default execution mode is `delegated`: the long-lived Controller owns direction, scope, acceptance and next routing, while Investigator handles open-ended, broad or repeated investigation and Implementer handles work with a stable direction. The Controller may make a one-time or very small number of related, precisely located reads needed for the current decision; open-ended iteration and successive small queries remain one investigation to delegate. An explicit user choice of `controller-direct` or `single-agent` takes precedence over the efficiency default. Task scope, role-readonly limits and user-content protection still apply. An in-task mode change uses `task-mode` with the selected Task ID, Authority digest and revision CAS; it changes only `execution_mode`. Unresolved work dependencies must first be explicitly cancelled or abandoned.

An intact task-scoped ACTIVE anchor can continue across turn, network or Hook interruption without proving Root session identity again. A missing contract, historical ACTIVE task without an anchor, Authority conflict or unverifiable security bytes still blocks managed control operations that depend on that Authority; it must not block unrelated ordinary work, reads or diagnostics. Real identity conflicts, fenced/abandoned children and readonly role boundaries still apply. Use bounded `task-status` for routing observations and full `task-show` only for explicit diagnostics. Native child state, Core/lifecycle records and the Controller's semantic acceptance are separate facts.

Authority recovery targets a Task ID selected explicitly or through a session already associated with it, and preserves that task's provenance and protected user bytes; it cannot approve a changed security baseline or remove a known old-child fence. `task-recover-state` requires `--task-id` or an already-associated `--session-id`. Legacy state is available only through explicit diagnostic/recovery paths and is never auto-adopted; unselected legacy bytes remain untouched. `UNKNOWN` remains UNKNOWN; the Controller can end or abandon the old task through a bounded path and fence late results without fabricating child `Completed`. If a child may still write shared files, handle that actual conflict. Host file changes, installation records, or a bootstrap run do not prove that the current Codex process loaded an update. See [task authority](docs/thaliris-task-authority.md) and [runtime recovery](docs/thaliris-runtime-recovery.md) for the exact procedure.

If the user explicitly changes execution mode during a task, `task-mode` updates the selected Task ID's mode with the current Authority digest and task-revision CAS plus the user's new instruction. It changes only `execution_mode`; it does not rewrite the goal, boundary, invariants or acceptance. An active dependency can be explicitly disposed with `task-dispose-dependency` in the same Task ID, using the current handoff ID, task revision, lifecycle digest and a reason. This records `ABANDONED_DEPENDENCY` and risk without fabricating the child’s native terminal state, and fences late results for that handoff. The Controller must handle any actual shared-file write conflict. After disposition, a dual-CAS `task-mode` update can change the mode in the same task. The Controller associates the current session with `task-associate`, supplying the Task ID, session ID and expected Authority digest; this creates navigation only and does not authenticate a Host actor. `task-start` can also receive the current `--session-id` to establish task navigation.

See [integration](adapter/codex/README.md), [authority](docs/thaliris-task-authority.md), and [recovery](docs/thaliris-runtime-recovery.md). The [shared documentation](https://github.com/Iris0fTheValley/Thaliris/tree/main/docs), [Core canonical README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md) and [English version](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.en.md) stay in main. [Thaliris-DSH](https://github.com/Iris0fTheValley/Thaliris-DSH) is a sibling Host adapter using the same Core.

Shared semantics leave judgment with models: INDEX is model-maintained semantic navigation; Core only checks paths, CAS, size and links. The Controller selects retained knowledge, and role results never automatically become durable memory.

Historical migration regressions read original immutable Git blob bytes from `tests/fixtures/history/provenance.json`, validating both Git blob and SHA-256 identities. Current generated profiles do not establish historical ownership.

The [historical admission-fix archive](docs/historical/admission-fix/README.md) preserves the original patches and profile-byte source snapshot. Its profile-content rejection behavior is not the current active contract.


## Execution constraints

Semantic roles, responsibilities, routing, and readonly limits remain separate from execution models. A dedicated Codex installation can use codex-install --execution-constraint luna-only to bind every ordinary worker profile to gpt-6-luna/xhigh while retaining the same role IDs and instructions. The task authority contract must explicitly include:

```json
{"execution_constraint": "luna-only"}
```

Core stores this optional non-empty string as immutable intent. The adapter accepts only luna-only and validates each execution binding. The external anchor freezes validated profile and configuration hashes; children and mutable configuration cannot expand or remove the constraint. A fresh Host session is required after installation. Admission compares role-profile and public-config snapshots recorded at SessionStart; those disk observations do not prove the effective Host role map or CLI -c overrides. SubagentStart checks the Host-reported model for a constrained child. Missing or mismatched values leave the handoff unbound and deny later child tools, but the Hook cannot prevent the model invocation. The constraint forbids Astra profiles and per-spawn model overrides; default bindings stay unchanged when it is absent. See the [execution-constraint port notes](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/docs/split-execution-constraint-port.md).

This feature requires thaliris>=0.4.4. Development tests must install the Core checkout used for this fix; the older monolithic wheel does not satisfy the split-package boundary.

## CI and platform compatibility

The CI matrix covers Ubuntu and Windows with Python 3.11, 3.12, and 3.13. It uses Core revision `56e48ac299dd2c5c4b16c992db732a55b7790893` by default; only a manually dispatched workflow may select another `core_ref`. POSIX runtime-identity checks accept only the exact virtual-environment alias `lib64 -> lib` and verify that target drift is rejected. Hook transport treats only one document-leading UTF-8 BOM as transport syntax; repeated or misplaced BOMs and invalid UTF-8/JSON remain denied. Hook diagnostics emit bounded JSON boundary labels without payload or inferred deeper causes. CI and source tests do not prove that a currently installed Codex process loaded these contents.

## Runtime prompt layers

Global instructions carry shared authority/isolation boundaries and the one-shot
startup entry. The required bootstrap response delivers resident normal Controller guidance: startup/admission, routing, handoffs, evidence reuse, waiting,
Workstream endpoints, acceptance/review selection, durable admission and causal diagnosis.
Project instructions retain shared boundaries and canonical pointers; the normal
Controller routine is not injected into every fresh child. The
[Controller procedures](docs/thaliris-controller.md) are canonical; retrieve exceptional
recovery/Host maintenance only when needed. The installed pinned runner's
`controller-instructions` returns an index; `controller-instructions --section <name>`
retrieves an exact missing section. Compare complete normal task context plus retrieval
cost and delivered quality, rather than the shortest prompt.
Native role prompts own current-role execution style, delegation and endpoints.
Fresh selected handoffs keep unrelated Controller procedures out of child injection;
rules remain retrievable on demand within authority. Each
invariant has one normal runtime authority; rationale and mechanical design live in
[Codex protocol](adapter/codex/README.md) and [Core prompt design](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-prompt-design.md).

Each necessary dependency has one observation owner: executors run/wait on their tests,
processes and CI; Controller waits only for a known unfinished child result that remains
necessary, without checking the same job again. A child FINAL or a decision-changing
unknown ends that slice; do not keep waiting for it. Choose waiting by available capability,
meaningful event and dependency; tool maximum is capacity, not a default duration, and
higher-level duration limits take precedence. The Hook
preserves caller wait arguments. No new controlled comparison measures wait cost; a
five-minute monitoring cadence is only an optional observation alternative, not a
current feature or requirement. Independent Task IDs may proceed in parallel. Within one
Task ID, multiple bound children may run simultaneously, with at most one unbound dispatch
reservation awaiting association. The Controller chooses parallel work from its dependencies;
overlapping writes in one worktree need coordination, while independent worktrees can carry
separate changes.

Hook failures emit a bounded JSON diagnostic on stderr identifying the receive,
strict decode, JSON syntax/shape, dispatch, maintenance-contract or runtime-identity
boundary. They contain no payload or exception contents and do not establish a deeper
root cause or change refusal/identity checks. One leading UTF-8 BOM is still accepted
only at the Hook document boundary. Review READY never replaces final product acceptance.

Controller supplies decision-complete selected handoffs; implementation methods belong
to the executor. Ordinary Implementer owns stable direction and deterministic convergence.
Focused Implementer owns the full reasoning, implementation, runtime-feedback and revision
loop for coupled invariants; once focused evidence supports core semantics and remaining
tasks cannot change the decision basis, it returns FINAL and releases that context.
Fresh ordinary Implementer handles remaining regression, build/sync, deterministic defects,
installation and Git closure. Shared execution guidance does not extend the Focused endpoint.
Reviewer is fresh independent and non-writing; READY requires evidence supporting critical
acceptance, not absence of blockers. Core/lifecycle observations do not decide acceptance.
V1 wait_agent status maps use exact spawned agent IDs; V2 list_agents uses canonical task
names. Both provide execution evidence without requiring V2 or duplicate confirmation of
an already-supported result. The supported Completed payload is the one-key
`{"completed": <string or null>}` variant; null indicates execution termination without
result text or semantic acceptance. Other value types and unsupported shapes remain
UNKNOWN. Native execution termination, Controller acceptance and task cancellation or
abandonment are separate facts. The Controller can end management through a bounded path
even when a child remains UNKNOWN; late results cannot re-enter a terminated task. Known
shared-write risks still need handling. SubagentStop is optional and its absence does not
undo other supported evidence. A contradiction or identity conflict restricts operations
that depend on that evidence, not unrelated ordinary work. Real Host stability of identity
fields across SubagentStart and PreToolUse remains UNKNOWN; synthetic tests do not prove a
Host protocol. Controller semantic acceptance remains independent, and unverified
compatibility stays UNKNOWN.

`thaliris_codex.roles` is canonical for native profile generation. Exact historical hashes
preserve safe upgrades; user-edited bytes and project profile shadows retain fail-closed
behavior. [Profile document](docs/thaliris-role-packs.md) is generated. Source changes do
not prove activation in a running Host and are not installed during an ACTIVE parent task.
ABCD results below remain historical; this prompt normalization has no benchmark claim.

Saved native Agent trees can be audited offline on demand. This read-only utility does not integrate with Hooks or runtime state; see the [audit usage and annotation format](docs/agent-tree-audit.md).

## ABCD benchmark results

We ran a controlled single-task benchmark to separate **model capability**, **orchestration**, and **heterogeneous intelligence allocation**. A/B/C used the same task, BASE revision, Codex version, isolated workspace/CODEX_HOME and environment; D is a previously sealed production-architecture run and was not rerun.

The four completed arms test two primary hypotheses:

**Orchestration Gain — B → C:** does role decomposition and isolated multi-agent execution improve a Luna-only system over a single Luna agent?

**Intelligence Allocation Gain — C → D:** once orchestration exists, does selectively placing stronger models at semantic implementation/review/closure points materially improve the result?

### Results

| Arm | Configuration | Coverage | Correctness | Compatibility | Implementation | Verification | Mean | Completion | Wall time | Cost proxy |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| **A** | Sol medium, single agent | 6 | 4 | 6 | 6 | 7 | **5.8** | Partial | **21m36s** | **$0.883** |
| **B** | Luna xhigh, single agent | 6 | 5 | 6 | 6 | 4 | **5.4** | Partial | **54m09s** | **$0.232–0.235** |
| **C** | Thaliris, Luna-only | 4 | 6 | 7 | 6 | 4 | **5.4** | Managed DONE / product partial | **41m11s** | **$0.272** |
| **D** | Thaliris, heterogeneous routing | **9** | **8** | **8** | **8.5** | **8** | **8.3** | Largely complete; one P2 remains | **64m47s** | **$2.475** |
| **E?** | D topology, **all-Sol workers** | **9?** | **8?** | **8?** | **8.5?** | **8?** | **8.3?** | D-like? | **64m47s?** | **~$3.67 predicted** |
| **F?** | D + **semantic-convergence cut** | **9?** | **8?** | **8?** | **8.5?** | **8?** | **8.3?** | D-like? | **64m47s?** | **~$2.06–2.07 predicted** |

A/B/C's independent scores and runtime/cost measurements come from the fresh benchmark assessment. D's original sealed assessment rated all five dimensions `GOOD`; the numeric 8.3/10 row above is a later read-only re-evaluation of the same frozen candidate using the A/B/C rubric. The original D run itself remains sealed and unchanged. Its production routing was Luna Investigator → Sol Focused Implementer → Sol Reviewer → Luna repair → Sol Reviewer → Luna repair.

### Token structure

`cached input` is a subset of input, not additional tokens.

| Arm | Input | Cached | Fresh input | Output | Reasoning output | Model distribution |
|---|---:|---:|---:|---:|---:|---|
| **A** | **3.104M** | 2.962M | 0.142M | 30.3k | 7.1k | 100% Sol medium |
| **B** | **16.70M** | 16.39M | 0.309M | 79.8k | 46.8k | 100% Luna xhigh |
| **C** | **15.73M** | 15.03M | 0.695M | 105.0k | 66.3k | 100% Luna xhigh |
| **D** | **15.22M** | 14.51M | 0.706M | 108.2k | 44.2k | Sol: 9.96M input / 64.3k output; Luna: 5.26M / 43.9k |
| **E? all-Sol** | **~15.22M?** | ~14.51M? | ~0.706M? | **~80.9k predicted** | ? | Same D topology, Luna nodes replaced by Sol |
| **F? semantic cut** | **~14.05–14.65M predicted** | ? | ? | **~100.9–108.9k predicted** | ? | Sol ~8.09M input; Luna ~5.96–6.56M |

Observed D usage was 15.219M input, of which 14.513M was cached. Luna consumed 5.260M input / 43.9k output, while Sol consumed 9.959M input / 64.3k output.

### What each arm shows

| Arm | Strength | Main weakness |
|---|---|---|
| **A — Sol solo** | Fastest run; strong implementation and extensive self-generated verification. | A single trajectory developed a coherent but incomplete semantic model. Its tests largely validated its own assumptions, leaving cross-surface ownership/replay/shutdown defects. |
| **B — Luna solo** | Extremely cheap. With much more compute and time, Luna reached nearly the same aggregate score as A. | ~5.4× A's input and ~2.5× wall time; weak global semantic convergence and verification. Large compute did not eliminate lifecycle/authority gaps. |
| **C — Luna orchestration** | Clear role separation, managed lifecycle, ~13 minutes faster than B, and slightly better correctness/compatibility. | **No aggregate quality gain over B.** Coverage fell 6→4. Treatment review produced a false-negative closure and the managed task reached DONE while product acceptance remained incomplete. |
| **D — heterogeneous Thaliris** | Only configuration to cross into substantially stronger completion. Independent review → repair → re-review actually changed the candidate and closed defects. | Most expensive and slowest observed arm. Sol accumulated large cached-context replay; one later P2 presentation-lifecycle defect remained and real GPU/audio/UI behavior was still unverified. |

A/B/C's principal independent defects are documented in the assessment: each reached a different partially-correct implementation rather than failing in exactly the same way.

### Hypothesis 1 — Orchestration Gain

**Method:** compare **B vs C** while holding actual execution capability at Luna xhigh. B is one Luna agent; C uses Thaliris roles, isolated child contexts and managed lifecycle, but every observed worker remains Luna xhigh.

**Observed result:**

`5.4 → 5.4`

No product-quality gain was observed. C was about **13 minutes faster** and used slightly fewer total tokens, but its estimated cost was **~16–18% higher** because more input was uncached. Its quality distribution changed rather than improving overall: coverage −2, correctness +1, compatibility +1.

**Conclusion:** orchestration alone did not make the weaker model materially stronger in this sample. It showed workflow/lifecycle and throughput benefits, but not aggregate quality improvement.

### Hypothesis 2 — Intelligence Allocation Gain

**Method:** compare **C vs D**. Both use Thaliris orchestration, but D selectively assigns Sol to the Controller, core semantic implementation and independent review while retaining Luna for investigation and bounded repair.

**Observed result:**

`5.4 → 8.3`

The largest rubric jumps were:

`Coverage: 4 → 9 (+5)`<br>
`Verification: 4 → 8 (+4)`<br>
`Implementation: 6 → 8.5 (+2.5)`<br>
`Correctness: 6 → 8 (+2)`<br>
`Compatibility: 7 → 8 (+1)`<br>

D cost about **9.1× C** and took about **1.57× longer**, but it was the only arm to substantially cross the product-completion threshold. D used no parallel execution; the main observable mechanism was repeated **Reviewer → bounded repair → re-review**, not agent count or parallel compute.

**Conclusion:** the result supports **selective intelligence allocation**, not “more agents are automatically better.”

### Two cost hypotheses to test next

**E — All-Sol counterfactual.** Keep D's task, topology, role sequence and lifecycle unchanged, but replace Luna Investigator/Implementer nodes with Sol. Input/context replay is held approximately constant; only output is adjusted using the observed A/B output-efficiency ratio (`79.8k / 30.3k ≈ 2.64×`). This predicts approximately **$3.67** for an all-Sol D-shaped run versus **$2.475 observed**, implying roughly **32.6% routing savings** from heterogeneous execution if D-level quality is preserved. Without the output-efficiency adjustment, the simple same-token estimate is about **$3.94**. This remains a counterfactual until run.

**F — Semantic-Convergence Cut.** Keep D's architecture and high-capability semantic nodes, but terminate the Sol Focused Implementer once the core implementation and hard invariants are established. Broad tests, build/lint closure, deterministic compatibility fallout and small repairs move to a fresh Luna Implementer; a fresh Sol Reviewer remains responsible for semantic acceptance. Trace-based estimation removes roughly **1.87M Sol input / 15.3k Sol output** and adds approximately **0.7–1.3M Luna input / 8–16k output**, predicting **~$2.06–2.07**, or roughly **16–17% below D**, while targeting the same 8.3-level result. Quality remains explicitly unknown until tested.

### Bottom line

The benchmark currently supports a narrower claim than “multi-agent is better”:

> **Weak-model orchestration alone did not improve aggregate quality. Selective placement of stronger intelligence at semantic implementation, review and closure points did.**

It also exposes the next optimization target: **not less high-capability implementation, but shorter expensive-context lifetime**. High-capability models should remain available for work that genuinely requires their reasoning during execution; once the semantic solution has converged, deterministic closure can move to cheaper fresh workers instead of repeatedly replaying a large Sol context.

## Benchmark boundary

`benchmarks/abcd/` may contain complex collectors, formal authority, and
offline scoring. The production `thaliris` package does not depend on D11,
formal registries, capture authority, or benchmark receipt issuers. Benchmarks
observe production; they do not define production architecture.

See [DESIGN.md](DESIGN.md) and
[docs/thaliris-routing-protocol.md](docs/thaliris-routing-protocol.md).

## README maintenance

Setup and installation also exercise the independent PowerShell runtime guard
before switching the Host generation. For explicitly authorized maintenance when
the ordinary entrypoints fail, see [launcher preflight recovery](docs/host-preflight-recovery.md).

The [Thaliris Core Chinese README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md) and [English README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.en.md) are canonical for shared explanations and full ABCD results. Keep Codex-specific features, dependencies, and limits here; update both Core language variants for shared changes and keep this repository's English and Chinese READMEs aligned.
