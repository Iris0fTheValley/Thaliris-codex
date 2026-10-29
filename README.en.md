# Thaliris

[简体中文](README.md)

**Attention is the most expensive resource.**

Thaliris is a **cognitive orchestration layer** for AI coding agents. It does not shorten context; it addresses three problems in long-running work:

- A capable model's attention is diluted by noise. Exploration, debugging and logs should not stay in the reasoning path responsible for key judgments.
- Original requirements and counterevidence can disappear during handoffs. A local “done” report must not silently overwrite an issue already found.
- A project's identity drifts over long-running work. Why the project exists and what must not change should not be silently rewritten by one local task, experiment or implementation limit after another.

The three form one causal chain, and attention dilution is where it starts. To protect key reasoning, work has to be split across Agents with fresh contexts and across many sessions; the split protects attention but creates handoff boundaries. Within one task, counterevidence is easily lost at those boundaries. Across tasks, if nobody holds what the project is for, each local decision can turn an implementation limit into a new principle, and the project's identity drifts a little at a time. In turn, lost evidence and drifted identity bring old problems and noise back into the key reasoning. So Thaliris does more than isolate noise: it states explicitly what must cross the boundaries after isolation, and who holds it.

> **Protect the reasoning. Isolate the noise. Isolation without amnesia.**

Thaliris builds on the native Agent capabilities of Hosts such as Codex, DeepSeek Harness and Claude Code, adding a layer for isolation, handoffs, evidence continuity and project identity rather than creating another Agent Runtime.

> **Status: Beta.** Real refactoring work has shown an implementer dispatching an investigation, a Controller starting an independent review, and counterevidence driving repairs. The sample is too small to establish a general quality or cost advantage. See [empirical observations](#empirical-observations).
>
> **Versions:** this document describes the source versions on each repository's `main` branch: Core 0.5.3, Codex adapter 0.5.5, Claude Code plugin 0.4.2 and DSH plugin 0.3.2. Version numbers describe source, not an installation on a given machine; updated files in a repository or on disk do not prove that a running Host has loaded the new version.

## Why more than context management

Common approaches manage more context within one Agent through compaction, retrieval or memory. Thaliris sees a larger problem than token count: too many competing goals share one reasoning path. The same Agent may be expected to investigate, design, implement, debug, review its own work and remember earlier failures.

Thaliris manages **who reasons and with what reasoning context**:

> **Give each reasoning context the information it needs; do not include other information merely because it exists.**

The name combines Thalamus, which filters and routes information, and Iris, which regulates how much light reaches the eye.

## Three pillars

### 1. Cognitive isolation: focus capable models on the work that needs them

A long-lived **Controller** retains the user goal, hard constraints and acceptance criteria. Short-lived roles work in fresh contexts and return conclusions, sources, verification results and decision-changing unknowns rather than the full working trail.

| Role | Responsibility |
| --- | --- |
| Investigator | Investigate facts within the selected scope |
| Implementer | Implement an accepted direction and verify it |
| Focused Implementer | Handle tightly coupled design and implementation until the core semantics converge |
| Reviewer | Optionally challenge a candidate independently and read-only |

Roles are selected as needed, not used as a fixed pipeline. Single-Agent work, direct Controller execution and delegation are all valid. Different roles can use models with different capabilities, keeping stronger models at decision-critical points.

### 2. Evidence continuity: isolate without forgetting

The main risk of isolation is that a counterexample found by a reviewer can disappear after several handoffs and repairs behind a simple “tests pass.” Thaliris addresses that risk with these rules:

1. **Record counterevidence.** When a child discovers a fact that changes a local conclusion, local acceptance or critical unknown, record an observation with sources, handoff provenance and its associated user requirement.
2. **Keep it visible until disposition.** Relevant observations remain visible in later handoffs until the Controller explicitly judges each related requirement satisfied, unknown, needing repair, or no longer relevant with a reason.
3. **Good news does not erase bad news.** A later test PASS, Reviewer READY, child Completed or Core DONE does not retire an earlier repair or unknown basis. The Controller must explicitly respond to it.
4. **Present evidence before the next decision.** The Adapter returns still-unresolved evidence with the child result before the Controller's next broad completion decision. This needs no extra Agent, fixed stage or polling.
5. **Append history instead of rewriting it.** Earlier observations and judgments remain in the record without automatically becoming current facts.

Core stores these links and append-only history; it does not decide what matters. The Controller decides relevance and acceptance.

~~~text
Reviewer finds a counterexample -> observation with source and requirement
                    |
      repair, test PASS, child Completed ... do not erase it
                    |
Controller disposition: satisfied / unknown / repair / no longer relevant
~~~

### 3. Semantics belong to the model; mechanics belong to Thaliris

The mechanical layer handles native Agent identity, sources, versions, continuity and bounded retrieval; semantic judgments stay with the model. Conclusions carry sources such as file hashes, Git blobs or test observations. Freshness only says whether declared sources changed; it does not prove every dependency stayed unchanged. When evidence is insufficient, keep the state UNKNOWN rather than upgrading an inference to a confirmed fact.

## Core design: four kinds of state, each with its own job

After isolation, what crosses Agent and session boundaries is not conversation history but four kinds of explicit state. They answer different questions, change in different ways and do not substitute for each other:

| State | Answers | Who can change it | How it crosses Agents and sessions |
| --- | --- | --- | --- |
| **Project identity** (`.project-identity/`, optional) | Why the project exists; which identity, invariants, principles, directions and non-goals lower-level work must not silently rewrite | Only an amendment the Controller records on the human owner's explicit decision; evidence can only raise a challenge against it | Tracked in Git, across all tasks and Hosts; the Controller sees a one-line summary and reads on demand, and a child sees it only when the Controller quotes selected items into its handoff |
| **Per-task authority** (Task Authority) | The intent the user selected for this one task: goal, scope, hard constraints, acceptance criteria and execution mode | Established and frozen by the Controller from the user's instruction at task start; changing goal, scope, acceptance or mode needs a new user decision; children cannot establish, expand, rewrite or reactivate it | Anchored outside the repository by the Adapter and kept across interruptions and reconnects; it is user intent recorded by the Controller, not authentication of the Host owner, and it does not include authority to maintain a live Host |
| **Evidence** (task ledger) | What this task found, from which sources, for which requirement, and how the Controller disposed of it | Children record observations; only the Controller judges; history is append-only | Bound to the Task ID and handoff chain; unresolved critical evidence is re-presented before the Controller's next judgment and survives compaction, resume and continuing the task in a new session |
| **Durable knowledge** (`.agent-memory/`, `.milestones/`) | Project knowledge and long-lived progress worth reusing later | Written when the Controller selects it, or reconciled by a Curator from selected material; carries sources and freshness | Kept in the repository and retrieved on demand through INDEX files; recording something does not push it into every role |

From the top down, project identity constrains tasks, task authority constrains this piece of work, evidence tests the current candidate, and durable knowledge keeps what was learned. A lower layer may challenge a higher one but cannot silently rewrite it: evidence does not overturn task authority, a task's conclusion does not become project identity on its own, and amending project identity does not rewrite the frozen authority of a running task. A project without an identity runs as usual and is never blocked or nagged.

## Components

| Component | Responsibility |
| --- | --- |
| [Thaliris Core](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.en.md) (shared Core) | Task IDs and task records, task authority, observation/judgment links, evidence and freshness, project memory, milestones, project identity, compare-and-swap writes and rollback |
| [Thaliris-codex](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/README.md) | Native Codex integration: Fresh Children, role profiles, native Agent identity and lifecycle, and evidence re-presentation |
| [Thaliris-dsh](https://github.com/Iris0fTheValley/Thaliris-dsh/blob/main/README.md) | DeepSeek Harness plugin: Workspace/Session/Agent integration and optional Memory |
| [Thaliris-claude](https://github.com/Iris0fTheValley/Thaliris-claude/blob/main/README.en.md) | Claude Code plugin: Controller skill, role subagents, hook-based native identity binding and evidence re-presentation |

There is one shared Core. Core does not run models, schedule Agents or authenticate callers; native execution belongs to each Adapter.

## Role capabilities and recommended models

> **Never use a small or low-capability model as the Controller.** Savings should come from giving narrow work to cheaper child roles, not from downgrading the Controller. A Controller's mistakes are not corrected by its children; they are amplified. In practice, weak Controllers skipped the managed flow, fell back to single-agent work after an isolation refusal, or declared completion while review counterevidence was still unresolved.

The Controller needs all of these capabilities; each one matters:

| Capability | The question the Controller must answer |
| --- | --- |
| Global Coherence | After dozens or hundreds of steps, does it still remember why the work is being done? |
| Strategic Planning | Can it work backwards from the end goal, identify dependencies and allocate resources, rather than only looking at the next step? |
| Retrospective Reasoning | Can it trace a root error in earlier decisions instead of repeatedly patching symptoms? |
| Metacognitive Monitoring | Can it notice that it is drifting, duplicating work or stuck on an impossible task? |
| Prospective Reasoning | Can it predict how a current decision affects later stages and avoid future structural problems? |
| Adaptive Replanning | When the plan fails or conditions change, can it reorganize the overall work instead of mechanically continuing the old plan? |

Capabilities each role needs, and recommended models:

| Role | Capabilities needed | GPT (Codex) |
| --- | --- | --- |
| Controller | All six above; integrates the original objective, acceptance criteria and evidence to decide product acceptance | gpt-6.1-sol (high or above); gpt-6-astra when the user explicitly selects it |
| Investigator | Gathers facts and sources broadly and accurately within the selected scope, stating covered and uncovered scope | gpt-6-luna (max) |
| Implementer | Implements, verifies and repairs ordinary defects within an accepted direction until deterministic convergence | gpt-6-luna (max) |
| Focused Implementer | Sustained reasoning over coupled invariants, absorbing runtime feedback until semantic convergence | gpt-6.1-sol (high); gpt-6-astra when the user explicitly selects it |
| Reviewer | Independently challenges a converged candidate and seeks cross-boundary counterevidence without adopting the author's framing | gpt-6.1-sol (high) |
| Reasoning Specialist | Challenges the problem framing, causal model and decision basis | gpt-6.1-sol (high); gpt-6-astra when the user explicitly selects it |
| Curator | Maintains selected durable knowledge and INDEX entries precisely from supplied material | gpt-6-luna (max) |
| Verifier (Codex compatibility role) | Read-only check of acceptance evidence, modification boundaries and synchronization | gpt-6-luna (max) |

Recommendations are a starting point, not a quality guarantee. A role and its execution model are independent; the model that actually ran is what the Host observed, not what a configuration file says.

These are recommendations only. Choosing each role's model is the Controller's job, made freely within any constraint the user wrote into the task. A user may also have the Controller do all the work itself: whether and how much to delegate is the user's decision.

## Empirical observations

**What this benchmark measures:** We chose a difficult single-turn refactor: desktop and WebUI share Live2D behavior, with model selection, voice/action queues and exit lifecycle involved. The benchmark does not rank candidates by how many bugs remain. It compares how original requirements guide investigation, plan convergence, implementation and verification, especially whether checks cover real consumer paths and whether counterevidence changes the plan. A/B are single-agent runs; C/D provide collaborative comparisons.

**How to read the results:** Frozen candidates received independent product post-reviews. The table separates in-run independent review and repair from the later post-review. A/B had no independent Reviewer during their runs; their later GPT-6.1 Sol/high reviews were separate assessments, not in-run self-review or repair. Their original high/medium severity labels and V3 coverage finding are preserved rather than converted to this table's P1/P2 scale. Each sample has unresolved requirements, some of which were already present in the starting code; defect counts are not a quality score.

| Sample (execution date) | Execution | In-run independent review/repair | Independent post-review of frozen candidate | P1 | P2 | Runtime | API-equivalent cost |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| A · 10/03 | Single agent, Sol/medium | No | Oct 14–15: NOT_READY; 1 high, 2 medium, plus V3 renderer coverage gap | — | — | 21.6 min | $0.88 |
| B · 10/03 | Single agent, Luna/xhigh | No | Oct 14–15: NOT_READY; 2 high, 3 medium | — | — | 54.1 min | $0.23 |
| C · 10/14 | Luna multi-agent | Yes, local | NOT_READY | 2 | 3 | 57.1 min | $0.46 |
| D · 10/14 | Sol + Luna multi-agent | Yes | NOT_READY | 1 | 2 | 40.4 min | $2.62 |
| C · 10/19 | Luna (dispatch rejected; single-agent fallback) | No | NOT_READY | 3 | 3 | 19.8 min | $0.22 |
| **D · 10/19** | **Sol + Luna native multi-agent** | **Yes, two counterexamples triggered repairs** | **PARTIALLY SUPPORTED / NOT_READY** | **0** | **3** | **34.4 min** | **$2.91** |

A and B ran on October 3, 2026; GPT-6.1 Sol/high independently reviewed their frozen candidates on October 14–15. API-equivalent costs are reference estimates for comparison, not actual billed amounts.

A had a shared behavior-policy and renderer-adapter direction by 16:46 UTC, then brought desktop audio blocking and WebUI segment scheduling into implementation. Its final relevant Python suite reported 92 passed and 1 deselected, with 20 frontend tests and successful build/lint. Its post-review still found that desktop conversion replaced an explicitly selected custom model with a Sakiko costume and Web presentation kept only the latest no-audio motion. An early overall direction and local verification therefore left real consumer paths open. B spent longer on broad investigation; its explicit defect set and shared target/renderer plan arrived at 16:59 UTC. It then corrected test-fixture and lint issues and completed 84 Python tests, 16 frontend tests, build and lint. The separate post-review still reproduced incomplete character-state and cancellation ingress and bye leaving active audio playing. The two reviews were independent assessments, not Reviewers in the A/B runs.

A/B and C/D are compared on investigation, plan convergence, requirement preservation, verification plans and revision after counterevidence—not on the number of bugs remaining in a frozen candidate.

The D · 10/19 independent post-review found no P0 or P1 issue, but reported three P2 classes and concluded PARTIALLY SUPPORTED / NOT_READY; this is not full product acceptance. The three classes were: a segment queued before cancellation could arrive afterward and resume playback; an in-flight producer could publish after the shutdown bye, while a separate frontend reproduction also accepted a later segment; and Web selected mouth-parameter names by model version, failing on supported alternate spellings that desktop selected from actual parameter IDs. A conflicting native Agent status during that run was handled as a Codex-native lifecycle anomaly.

**What happened in D · 10/19:**

~~~text
Controller assigns coupled design and implementation to Sol
  -> Sol independently dispatches Luna to investigate runtime support and test boundaries
  -> Sol returns a local candidate
  -> Controller starts an independent review instead of treating local completion as the end
  -> Reviewer finds two counterexamples that overturn the local conclusion:
       - an explicitly selected model can be replaced by an older desktop rule
       - an exit farewell may be sent after its event channel has closed
  -> Controller accepts the counterevidence and dispatches repairs and regression checks
~~~

This demonstrates the behavior Thaliris is designed to test: **local success is not global completion, and counterevidence changes the work that follows.**

**C · 10/19 also matters:** This was not a successful multi-agent run. Luna's request to pass the full conversation history to a child was correctly rejected by Fresh Context protection; it did not retry with an independent context, so the task returned to single-agent execution. This shows that isolation protection worked, while also showing that a critical dispatch decision needs a capable model.

**What is not yet established:** Each arm is a single run; Host and model effort differed between batches, so this is not a single-variable experiment. The mixed-model configuration cost more. Some counterevidence from D · 10/19 review and repair led to real fixes but was not recorded as formal observations, so the persistent Evidence Continuity path is still being completed. See the [ABCD benchmark implementation](https://github.com/Iris0fTheValley/Thaliris/tree/main/benchmarks/abcd) and [benchmark protocol](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-benchmark-protocol.md).

## Quick start

Python 3.11 or newer is required. Git is optional for Core use; installing from the Git URL below also requires Git.

~~~bash
uv tool install git+https://github.com/Iris0fTheValley/Thaliris
cd your-repository
thaliris-core --root . init
TASK_ID=$(thaliris-core --root . task-start "example task" | python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')
thaliris-core --root . --task-id "$TASK_ID" task-status
~~~

Each task has its own Task ID, which is passed explicitly to later operations. Installing Core alone does not enable multi-agent work. For native integration, follow the [Codex](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/README.md), [DSH](https://github.com/Iris0fTheValley/Thaliris-dsh/blob/main/README.md) or [Claude Code](https://github.com/Iris0fTheValley/Thaliris-claude/blob/main/README.en.md) guide.

An initialized repository contains:

~~~text
.agent-memory/   # selected knowledge that can be reused across tasks
.milestones/     # long-term scope, decisions, progress and verification
.context/tasks/<task-id>/state.json   # task state and evidence; ignored by Git by default
~~~

Task state stores structured facts, observations and judgments, not conversation transcripts. Persistence and handoff are separate choices: recorded information is not automatically passed to every role.

A project may also have an optional, tracked `.project-identity/`: a cross-task identity baseline that changes only through a recorded amendment by the Controller on the human owner's explicit decision. The Codex Adapter shows the Controller one summary line and never injects identity text into child roles. Without any setup form, the Controller records the user's own explicit long-term statements verbatim with `identity-note`, and may offer once after a task closes (`identity_offer`) to compose a first version for the user's confirmation; `identity-suggest` turns offers off by scope; see [Project Identity](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-project-identity.md).

## What it is not

Thaliris is not an Agent Runtime, workflow engine, fixed multi-agent pipeline, vector database or RAG system, automatic whole-repository summarizer, or substitute for source code, tests, compilers and runtime behavior.

Removing Thaliris should not make the underlying development process incorrect.

## Further reading

- [Core design](https://github.com/Iris0fTheValley/Thaliris/blob/main/DESIGN.md)
- [Routing protocol](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-routing-protocol.md)
- [Task authority contract](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-task-authority.md)
- [Project Identity](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-project-identity.md) — project-level identity, amendments and challenges
- [Prompt ownership and research motivation](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-prompt-design.md)
- [Role descriptions](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-role-packs.md) · [Packaging and API boundaries](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/host-neutral-packaging.md)

## Native Codex integration

Thaliris-codex connects shared semantics to Codex's native Agents, role profiles, Hooks and session lifecycle. It depends on the separately installed Thaliris Core (Core 0.5.3 or later, below 0.6), which provides task records, evidence and the task authority API; the Codex Adapter handles native admission, routing, identity association and lifecycle observation. See the [integration protocol](adapter/codex/README.md).

Default model and effort routing for ordinary roles is shown below. During managed dispatch, the Adapter supplies omitted selection fields only for an exact registered Thaliris role and preserves explicit choices:

| Role | Default model | Default effort |
| --- | --- | --- |
| Investigator, Implementer, Curator, Verifier | gpt-6-luna | max |
| Reasoning Specialist, Focused Implementer, Reviewer | gpt-6.1-sol | high |

A role is separate from its execution model. A Fresh Child is a new native role session created with a selective Handoff: Codex V2 uses fork_turns=none and V1 uses fork_context=false. It receives only the facts, constraints, sources and acceptance needed for its work, not the parent's conversation history. Relevant originals can still be reopened, and children stay within their selected scope rather than making architecture or product-acceptance decisions for the Controller.

Native child status is associated through the exact child identity, dispatch and lifecycle evidence. Visibility in the Native agent catalog or temporary inactivity alone does not prove execution ended. Native child Completed describes Agent execution; Core task DONE is a mechanical task state; the Controller judges product acceptance against the original goal, criteria and available evidence. Missing or conflicting status remains UNKNOWN under the Codex lifecycle contract. See [role and model routing](docs/codex-role-model-routing-native-20261013.md), the [native lifecycle record](docs/codex-native-lifecycle-20261018.md) and [runtime recovery](docs/thaliris-runtime-recovery.md).

**Controller management overhead (adapter 0.5.1 with Core 0.5.1):** the semantic rules are unchanged; the Controller needs fewer management calls and reads shorter output. `task-status` returns a compact view by default (routing header, counts and a bounded open-evidence summary paged with `--evidence-offset N`); `--view full` returns the full Evidence Continuity page, and `--since-revision N` adds a bounded, non-exact review hint. Controller write results and the evidence packet the Hook re-presents carry the current task revision and the same compact evidence summary. Writes remain strict revision compare-and-set: a stale `--base-revision` returns `TASK_REVISION_CONFLICT`, `details.current_revision` and an approximate `details.changes_since`; review it and retry once with the current revision. Other Core errors also carry a stable `code`, `recovery` and `details`. `task-judge` can commit 1 to 64 judgments as one atomic batch (`{"judgments":[...]}`, one revision), and `task-update`, `task-evidence-register` and `task-judge` accept inline `--json` (through the Hook's UTF-8/base64 transport) instead of a temporary file. Child observation ids are stored in a per-handoff namespace (`<handoff>.O1`), so parallel children can all use `O1`. bootstrap, controller-instructions and Hook output are always written as UTF-8 regardless of the console code page. Repository tests cover this behavior; overhead has not been measured on a live Codex Host, and the Claude repository's overhead benchmark numbers do not carry over to Codex.

## Installation and project setup

For normal installation, update or status checks, make an explicit request in Codex and let the installed maintenance client use a trusted, exact release input. First installation, a missing updater or recovery uses system Python 3.11+ and thaliris-bootstrap.py. The [release lifecycle](docs/release-lifecycle.md) documents the exact command and its manifest/digest trust requirements. The local read-only status command is thaliris-release status.

After Host integration is installed, the owning Controller runs codex-bootstrap once for a project with substantive file changes, including README changes, using the installed pinned runner and target repository. Bootstrap does not create a Git repository. Chat and read-only work do not need it. Core installation and project setup serve separate purposes, and source edits do not prove that Codex has loaded an update.

See the [release lifecycle](docs/release-lifecycle.md), [Host maintenance contract](docs/thaliris-host-maintenance.md), [task authority contract](docs/thaliris-task-authority.md) and [Adapter integration protocol](adapter/codex/README.md) for maintenance and source-development details.
