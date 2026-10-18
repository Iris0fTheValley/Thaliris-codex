# Thaliris Codex adapter

Language: English | [简体中文](README.md)

A lightweight, Git-native context and orchestration layer for AI coding workflows.

Thaliris selects necessary facts, constraints and evidence to protect effective reasoning by high-capability models in focused contexts. Context quality is not context quantity; runtime prompts are part of the working context too. Irrelevant information, competing objectives and accumulated history can dilute or interfere with the evidence that actually needs reasoning.

**Attention is the most expensive resource.** Here, attention means a capable model's effective cognitive budget for solving difficult problems in a clean, focused context. It is neither simply the price of tokens nor the Attention algorithm.

Thaliris manages the conditions under which information enters a reasoning path rather than rebuilding a general-purpose Agent Framework. Evidence, freshness, memory, task state and adapter mechanisms serve correct information transfer and task execution, rather than adding process for its own sake. Cognitive isolation and appropriate allocation of model capabilities aim to improve complex-task quality and overall efficiency without sacrificing necessary reasoning or evidence.

> **Status:** Beta. Design goals are not demonstrated gains. Historical ABCD results apply to their original setups; recent prompt, orchestration and waiting-rule changes have no new controlled quality or cost comparison.

## Why this project exists

Long coding tasks tend to accumulate context.

A single agent may eventually carry:

* repository exploration;
* failed search paths;
* implementation details;
* test output;
* debugging traces;
* architectural reasoning;
* reviewer criteria;
* old decisions;
* unrelated historical context.

More context is not automatically better context.

For strong reasoning models, the larger risk is often not the raw number of tokens but the number of competing objectives inside the same reasoning trajectory.

An agent asked to simultaneously:

* investigate,
* design,
* implement,
* verify,
* review its own design,
* remember previous failures,
* and satisfy a large procedural checklist

is solving a different problem from an agent given a focused reasoning question with the necessary evidence.

Thaliris is built around a simple idea:

> **Preserve useful information without forcing every role to carry every piece of information.**

The project therefore treats context boundaries as part of the engineering architecture.

---

## Why Thaliris

**Thaliris** combines **Thalamus** and **Iris**.

The thalamus filters and routes information entering cognition; the iris
regulates how much light reaches vision. The name is an image for agent
context: control what reaches a reasoning path, preserve evidence-backed
information, and isolate unrelated working sets.

---

## How the principles shape work

### Long-lived decisions, short-lived working contexts

The long-lived Controller retains the user objective, scope, hard invariants, acceptance conditions and selected decision basis, then decides what work is needed next. Short-lived roles carry the investigation or implementation working set. Search paths, debugging traces and raw logs stay in the responsible context; the return carries conclusions, source locations, verification, contradictions and unknowns that could change a decision. The Controller need not carry the entire process again, and executors need not carry the project's entire history.

A Fresh Child is a new native role session receiving the facts, constraints, sources and acceptance needed for its work through a selective Handoff. Isolating history does not discard evidence: necessary originals can be reopened at their source locations, while established inventories and facts should be reused. A working set is not a handoff set. Recording or retaining information does not automatically pass it to every role.

Controller keeps global user requirements and acceptance. A child receives selected local goals,
acceptance and source pointers. When an already discovered local fact changes its conclusion,
local acceptance or critical UNKNOWN, the child records it with source refs, handoff provenance
and opaque requirement refs. This adds no search duty, global-importance judgment, model call or gate. Critical evidence stays visible
across handoffs until Controller explicitly reassesses the related user requirement for the current
candidate as satisfied, unknown or repair, or explains why it no longer affects the candidate.
Reading or acknowledgement is not disposition; PASS, READY, Completed and DONE cannot substitute.
Prior observations and judgments stay in history without becoming automatic current truth.
The immutable candidate is a logical handoff label, not a repository snapshot. Source refs and optional
producer-selected `observed_state` distinguish local observations; absent state identity remains UNKNOWN.
Nested Scanner lineage does not infer requirement relevance: unassigned observations await Controller selection.
A later judgment explicitly addresses prior repair/unknown basis through `judgment_refs` and reasoning
or its complete observation refs. Fresh positive evidence alone does not remove that basis.
Adapters reintroduce bounded evidence during ordinary Controller result delivery, before its next broad
completion decision; this adds no polling, mandatory stage, Agent or mechanical close gate.

Curator maintains exact selected durable knowledge and INDEX entries, including editing, merging,
splitting, replacing or deleting existing entries. Core provides CAS document maintenance and
provenance storage; the model chooses semantic reconciliation. Curator does not scan the corpus,
delegate, decide product acceptance or own real-time evidence continuity. Concise future decision
value stays in memory; raw detail stays in canonical Artifacts, Git or rollout records.

| Role | Work it handles | Why separate it |
| --- | --- | --- |
| Investigator | Facts within the selected scope, exact sources, coverage, contradictions and unknowns | Keeps exploration history in the investigation context without deciding architecture for the Controller |
| Implementer | An accepted, stable direction through necessary verification, local repair and assigned closure | Lets deterministic work reuse an explicit contract without reopening architectural decisions |
| Focused Implementer | Sustained reasoning, implementation, runtime feedback and revision across coupled invariants until core semantics converge | Protects focused cognitive budget while the solution can still change; a fresh ordinary Implementer then handles assigned deterministic closure |
| Reviewer | Independent, non-writing challenge of original acceptance, invariants and cross-boundary behavior after candidate convergence | Examines evidence without carrying the implementer's full debugging trajectory or continuing its code changes |

Roles are capabilities selected by work shape, not stages every task must traverse. Multiple Agents, fixed review rounds and uniform steps are not mandatory; an explicit single-agent execution choice should also be preserved. Investigation, independent review and parallelism depend on evidence, decision coupling and actual write conflicts rather than file, call or elapsed-time thresholds. Native role bindings and execution modes belong to each Host adapter.

### Evidence, task records and reusable knowledge

Conclusions should identify their evidence and applicability. File hashes, Git blobs and test/runtime observations can identify the version observed. Freshness checks only declared sources for change; they cannot prove every dependency unchanged or decide whether a conclusion still applies. Insufficiently established conclusions remain `UNVERIFIED`; missing execution or identity observations remain `UNKNOWN`, rather than turning inference into confirmation. Existing records are retrievable material, not facts downstream roles must accept.

Short-term records retain facts, pending work and evidence for the current Task ID rather than copying conversation transcripts. Core `task-promote` persists only Controller-selected Markdown records under `.agent-memory/`; each record requires `id`, `path` and `text`, while `title` defaults to the ID and `source_refs` defaults to an empty list. It creates a new non-INDEX Markdown file, and Core refuses to overwrite an existing durable target. The promotion transaction uses the current Task ID and task revision CAS. Optional legacy `status` is opaque and conveys no confirmation or lifecycle state. Each record is limited to 16,384 text characters and 64 source references. Promotion records cannot target `.milestones/`; an optional INDEX update can target `.milestones/INDEX.md`. `INDEX.md` is model-authored semantic navigation; updates supply a complete file replacement, and Core validates the expected digest, path and links rather than generating the index. The Controller decides what merits long-term retention. Persistence and transmission to the next role are separate choices. Optional Host memory integrations have their own storage and authorization contracts.

Each independent task has a UUID Task ID and its own local state file. Continuing a task means selecting its Task ID and relevant evidence; starting another creates a new Task ID rather than inferring the current task from old workspace state. Old `ACTIVE`, `UNKNOWN` or damaged records do not automatically occupy a singleton task slot. Actual overlapping writes to shared files still need coordination. Native session association, recovery and permission checks belong to adapters; a Task ID grants no authority and does not authenticate a Host actor.

The Controller combines the user's original objective, acceptance criteria and available evidence to decide whether the product is complete, and whether to route repair, request useful extra verification or record mechanical closure. Executors implement and verify assigned work, then return the candidate state, criterion-linked evidence and `UNKNOWN` for unverified behavior. A Reviewer may provide an independent read-only challenge when useful; review is optional, and no separate closing handoff or new Agent is required. Test `PASS`, Reviewer `READY`, native `Completed` and mechanical `DONE` describe different evidence or status layers; none alone decides product completion. The Controller retains that decision in delegated, controller-direct and single-agent work. Each necessary dependency has one observation owner. Use reliable results once available, without waiting for the same completion again or repeatedly waking a model to observe unchanged state. Verification and waiting serve actual unresolved questions.

## A cross-module coding example

Suppose a user requests cancellation for an export feature spanning an API, queue and storage layer while preserving older requests. This illustrates the mechanism, not a product test or performance experiment, and is not a mandatory workflow.

1. The Controller establishes cancellation semantics, compatibility boundaries and acceptance scenarios. An Investigator maps request entry, queue transitions and storage writes, returning sourced call relationships, existing tests and unresolved races. Failed searches and raw logs stay in its working set.
2. The Controller selects relevant facts, hard invariants and unknowns for the Handoff. Where cancellation, completion and writes are coupled, a Fresh Focused Implementer implements and verifies those invariants. Independent changes with stable direction can go to an ordinary Implementer.
3. The executor returns the exact candidate, source versions, test coverage and uncovered cases. After core semantic convergence, a fresh ordinary Implementer can handle remaining deterministic synchronization, regression or Git closure without extending the original focused context.
4. Where independent challenge could affect acceptance, a Fresh Reviewer examines boundaries such as simultaneous cancellation and completion or older API compatibility. Unverified runtime behavior remains unknown; findings return with evidence rather than becoming accepted conclusions automatically.
5. The Controller integrates implementation reports, tests and available runtime evidence against the original objective and criteria. It routes repair or useful additional verification for unmet criteria or decision-changing unknowns, and selects a Reviewer only when independent challenge could affect the decision. The Controller then records mechanical closure when actual product completion is supported. Only cancellation invariants or verified failure modes with value beyond this task enter project memory; other records remain with their Task ID.

Source code, Git, tests, compilers and actual runtime behavior remain the basis for correctness. Thaliris reuses native sessions, Agents and execution in Codex and DSH, adding context selection, handoffs, records and evidence boundaries rather than constructing another Agent Runtime.

## Codex runtime contracts and capabilities

This is the Codex Host adapter for [shared Thaliris Core](https://github.com/Iris0fTheValley/Thaliris), not an independent Core. It imports Core rather than bundling a copy.

The `thaliris-codex` distribution uses `thaliris_codex` and preserves the `thaliris` and `context` Codex commands. It owns native bootstrap, lifecycle, Hook trust, actor identity, doctor, recovery and generated model profiles. Core supplies the ledger, retrieval, evidence, memory and `thaliris.authority` API.

Codex supplies native Controller and role sessions, tools and collaboration. The adapter connects shared role semantics to native profiles, selective Handoffs, explicit task association and Hook observations. Fresh Children use V2 `fork_turns="none"` or V1 `fork_context=false` and receive only parent-selected material. Native execution termination and product acceptance remain separate records.

Ordinary reads, edits, tests and Git work have different boundaries from managed controls such as establishing Authority, changing execution mode or disposing of dependencies. Missing observations stay `UNKNOWN`: they neither automatically deny unrelated ordinary work nor grant managed-control authority. Known read-only restrictions, identity conflicts and user-content protections still apply. Host installation and maintenance require separate authorization; source or disk changes alone do not prove activation in the current process.

Global instructions also carry shared working principles: reuse selected evidence, coordinate writes by work dependencies, verify behavior with the smallest meaningful checks, and give each necessary dependency one observation owner. Bootstrap delivers normal Controller guidance; exceptional recovery and Host maintenance are retrieved when needed. See the [integration protocol](adapter/codex/README.md) and [Authority contract](docs/thaliris-task-authority.md).

Ordinary generated role profiles intentionally omit model and effort because Codex applies a configured role model after spawn arguments. Controller defaults Investigator, Implementer, Curator and Verifier to gpt-6-luna/max, and Reviewer, Focused Implementer and Reasoning Specialist to gpt-6.1-sol/high. Every Thaliris auxiliary task, including preparation, must select an exact registered Thaliris `agent_type`; generic native profiles do not receive Thaliris defaults. After applicable isolation, readonly, fence, task-control, role and execution-constraint guards pass, routing supplies omitted or `null` model/effort fields only for an exact registered ordinary role. With only effort supplied it adds the role's default model; with only model supplied it preserves Native configured/default effort. Explicit non-empty choices remain unchanged, and empty or non-string values are denied. For an ACTIVE task, the existing freshness, owner, delegation and Authority checks remain ahead of routing and reservation. In NO_TASK or inactive state, the same role defaults update only Native spawn parameters; they create no reservation or lifecycle binding. Before a managed reservation, a read-only check validates only the selected ordinary target in personal and project scopes, using TOML name and legacy config_file references. Fixed fields must agree with selected/routed fields; model-free user edits are allowed. Conflicts or unverifiable target bindings prevent reservation, with UNKNOWN for unverified effective priority or unsupported target model/effort values. Routing preserves user bytes and cannot prove which definitions the running Host loaded. Astra still requires current-task human opt-in; static Astra compatibility profiles retain their fixed bindings, and luna-only stays frozen and forbids per-spawn overrides. A trusted isolated Native run on `codex-cli 0.162.0-alpha.17.2` verified `updatedInput`, four managed role/model contexts, generic Native passthrough, and pre-reservation denial for a same-name profile conflict. These temporary child contexts also recorded managed read-only sandboxes and lifecycle bindings. That candidate did not establish formal production or desktop Host activation; installed profiles may still be historical. See [native selection precedence](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning).

The Codex model catalog is Host-wide configuration (`model_catalog_json`), separate from project role profiles. Maintenance is explicit and infrequent: catalog compatibility is determined by the selected source's model roster and content checks, not a CLI-version allowlist. Online exports also validate isolated-cache freshness, the CLI's whole `major.minor.patch` cache version and model identities; the full CLI version remains source evidence, while its prerelease label is omitted from the cache version. Known templates require the exact full line in its expected neighboring context; new models require one exact full-line target. An absent, moved, rewritten, split, embedded or repeated target preserves the old catalog and reports incompatibility. Catalog receipts declare their required capability; the current reader accepts valid legacy receipts and migrates them during a successful authorized upgrade, while an older reader rejects the new receipt format before writing. For downgrade, uninstall with the current reader first; its exact archive allows a later upgrade to reclaim matching bytes while the field is absent. User edits may be preserved while other authorized Host work proceeds, but the catalog goal remains unmet. An install contract can select a project-loss recovery location; an actual Host `SessionStart` removes the managed configuration field only after exact marker, receipt and catalog-digest checks, leaving the physical catalog file in place. A restoration receipt permits one reclaim only when recovery removed the exact owned field. If the field was already absent without prior restoration proof, recovery reports `RECOVERY_PROVENANCE_UNKNOWN` and does not authorize reclaim. Successful reinstatement clears the proof. Disk configuration, the catalog loaded by the current process and sessions started earlier are separate states; an edit or installation does not prove current Host activation. See the [model catalog maintenance report](docs/model-catalog-maintenance-report.md). The accepted transaction boundary preserves user edits observed by the final byte comparison and retains the backing catalog. A non-cooperating writer can still race between comparison and atomic replacement; this documented interval is accepted for this scope and is not a pending decision.

## Installation and local development

### Normal use: ask Codex to maintain Thaliris

Users ask “install Thaliris”, “update Thaliris”, “repair this installation” or “check Thaliris”. The root agent checks local facts, selects a trusted exact release, verifies candidates and invokes the verified updater under the current user maintenance intent. Users need not handle manifests, digests, Core/Adapter pairing, wheels or maintenance contracts.

A supporting Hook issues a short-lived, single-use operation capability bound to the session, latest observed prompt epoch, action, Host/home, release input, updater and original resume contract. Known children/delegates, readonly, fenced/abandoned actors, mismatched scope, expiry and replay are refused. An instruction string or command spelling alone cannot grant permission. This is model-selected governance with mechanical Hook checks; host_actor_assurance remains UNKNOWN, not shared-OS human or universal Controller authentication.

The installed updater provides local read-only status without release input, network access or candidate creation:

~~~powershell
thaliris-release status
~~~

A trusted manifest/digest pair optionally adds release comparison. Ordinary updates fully revalidate saved candidates before acquiring wheels; only a miss acquires artifacts and creates a new immutable runtime. Host mutation still uses exact contracts, ownership and transition/recovery, preserving user edits. Loaded Host/restart facts remain UNKNOWN without native evidence.

No release from this source state has been published; public attestation and native activation are unverified. Trusted automatic latest discovery remains deferred: the agent must select independently trusted exact release inputs, never treat a same-origin checksum as authentication. An older Hook requires the existing explicitly authorized exact-contract transition route. Python-free delivery is also deferred.

The standalone thaliris-bootstrap.py is for first installation, missing updater and independent recovery. It requires system Python 3.11+ and separately trusted bootstrap/release inputs; it does not implement a second candidate verifier or serve ordinary cache hits. Explicit CLI first installation uses --standalone-maintenance only with no managed installation; it cannot replace integrated capability evidence or authorize overwriting damaged ownership. See the [release lifecycle](docs/release-lifecycle.md) for agent protocol, maintainer interfaces and recovery limits.

### Advanced: source development

Source development is separate from ordinary install and update. pyproject.toml requires Python >=3.11 and thaliris>=0.4.6,<0.5. The default Core pairing is recorded once in [release/core.lock.json](release/core.lock.json); read the selected commit there instead of copying a second revision into this README:

~~~powershell
$coreCommit = (Get-Content release/core.lock.json -Raw | ConvertFrom-Json).commit
$coreCommit
~~~

With local Core and Adapter checkouts, install the Core test extra and the Adapter checkout, then point the source runner at the Core source tree and run the Adapter tests:

~~~sh
python -m pip install -e '../Thaliris[test]'
python -m pip install --no-deps -e '.[test]'
~~~

Offline recovery source-runner tests require THALIRIS_CORE_SOURCE to point to a Core checkout containing src/thaliris/core.py; the runner loads that source checkout explicitly instead of treating an installed Core package as reviewed source. In PowerShell:

~~~powershell
$env:THALIRIS_CORE_SOURCE = (Resolve-Path '../Thaliris').Path
python -m pytest
~~~

In POSIX shells, set THALIRIS_CORE_SOURCE=../Thaliris and run python -m pytest. CI also reads its default Core pairing from release/core.lock.json; a manually dispatched workflow may select another core_ref. Source and Host integration details are in the [Codex integration guide](adapter/codex/README.md) and [Host maintenance guide](docs/thaliris-host-maintenance.md).

Source tests and disk installation do not prove that the current Host loaded or trusts these files. See [task authority](docs/thaliris-task-authority.md) and [runtime recovery](docs/thaliris-runtime-recovery.md) for the project instruction and recovery contracts.

## Starting and recovering project tasks

After Host installation, unless the user opts out of Thaliris, the owning Controller runs `codex-bootstrap` once for substantive project file changes, including README-only work, configuration changes and new project creation, using the installed pinned runner and target repository. Chatting and read-only work need no project Bootstrap.

An explicitly selected existing project directory supports bootstrap and managed task admission without Git metadata; `codex-bootstrap` never runs `git init`. Create Git metadata independently only when repository creation is within the user's scope. Native cwd, managed project root and Git worktree root are distinct; existing Git root selection remains compatible. Without Git, HEAD and Git surface observations are locally unavailable and Git evidence freshness stays `UNKNOWN`, while task authority and lifecycle remain available. Make this a separate invocation:

```powershell
& '<installed pinned runner>' --root '<repo>' codex-bootstrap
```

Bootstrap guidance is wrapped in BEGIN/END markers; the complete END marker carries
its SHA-256 and UTF-8 byte count. Bootstrap JSON places compact workspace status
diagnostics before the receipt metadata and guidance body, so truncation leaves the
diagnosis readable while the missing END marker prevents acknowledgement. Only after
the complete tool result and END marker are visible may the same active context pass
`--controller-guidance-sha256 <digest>` for another workspace to omit duplicate text.
This is an explicit content acknowledgement, not proof that the process wrote stdout,
and no session state is persisted.
New sessions and fresh children do not reuse the digest. Omit it after truncation or
when guidance changes to receive the full current copy, or retrieve it with
`controller-instructions --resident`.

`READY` (legacy `DEFINITION_READY_ACTOR_UNKNOWN` is also accepted) means project definitions are available; it does not authenticate a Host actor or prove that the current process loaded role configuration. If definitions are missing, follow the bootstrap result instead of bypassing the adapter to create a separate task ledger.

Task admission uses a separate UTF-8 JSON contract file with non-empty `human_instruction`, `boundary`, `invariants`, and `acceptance` strings, plus optional `execution_mode` (`delegated`, `controller-direct`, or `single-agent`). If omitted, the mode defaults to `delegated`: the Controller owns long-lived decisions, while short-lived Investigator/Implementer roles handle the main investigation and implementation. `controller-direct` lets the Controller read, edit, test, commit and close the work, with auxiliary roles available when useful; `single-agent` means ordinary single-agent work with no children. An explicit user choice takes precedence over the efficiency default without expanding task scope or overriding read-only role limits or protection of user-owned files.

```json
{"human_instruction":"<actual user instruction>","boundary":"<selected scope>","invariants":"<hard constraints>","acceptance":"<acceptance conditions>","execution_mode":"delegated"}
```

After creating that file, start the task in another separate invocation:

```powershell
& '<installed pinned runner>' --root '<repo>' task-start '<goal>' --authority-contract '<absolute-contract-file>'
```

In `delegated` mode, ordinary Controller reads, Git and diagnostics are legal within the task boundary. Default routing recommends fresh roles for substantial investigation and implementation. Choose by purpose and working set; file, line, token and query counts do not grant or deny permission. Prefer bounded retrieval when useful, and preserve isolation, readonly and protected control boundaries.

Explicit contract admission does not require a bootstrap receipt or one-shot Hook bearer. If a legacy proof is explicitly supplied, the adapter still validates it strictly. The contract records the Controller's selection of human task intent; Host Root actor assurance remains `UNKNOWN`, so it is not general identity authentication. Known child, readonly, fenced, retired, or conflicting states cannot establish or expand authority. Ordinary repository work may use an exact native Agent-to-Task mapping or an active handoff with a known role; missing noncritical session, turn, or profile fields remain `UNKNOWN` and do not qualify managed control. Provided identity contradictions still block dependent actions, and a known read-only role remains denied Bash/MCP mutations even when Authority or optional fields are incomplete.

Each Task ID has its own task state, Authority, lifecycle reservations, child bindings and recovery evidence. `task-start` creates and selects a new Task ID; an older task in the same repository may remain `ACTIVE` or `UNKNOWN` without being inherited or blocking the new task. Resuming an existing task requires selecting its Task ID explicitly. The current Codex session must also be associated explicitly with `task-associate`; that operation records navigation for the Task ID and session ID with an Authority revision/hash CAS, but does not authenticate a Host actor, so Host assurance remains `UNKNOWN`. Hooks use only an explicit mapping for the current session/agent-task or an exact Task ID selector; repository path alone does not choose the current task.

The default execution mode is `delegated`: the long-lived Controller owns direction, scope, acceptance criteria and next routing, while Investigator handles open-ended, broad or repeated investigation and Implementer handles work with a stable direction. Ordinary Controller reads, Git and diagnostics are legal within the task boundary; choose delegation by purpose and working set, without numeric permission thresholds. An explicit user choice of `controller-direct` or `single-agent` takes precedence over the efficiency default. Task scope, role-readonly limits and user-content protection still apply. An in-task mode change uses `task-mode` with the selected Task ID, Authority digest and revision CAS; it changes only `execution_mode`. Unresolved work dependencies must first be explicitly cancelled or abandoned.

An intact task-scoped ACTIVE anchor can continue across turn, network or Hook interruption without proving Root session identity again. A missing contract, historical ACTIVE task without an anchor, Authority conflict or unverifiable security bytes still blocks managed control operations that depend on that Authority; it must not block unrelated ordinary work, reads or diagnostics. Real identity conflicts, fenced/abandoned children and readonly role boundaries still apply. Use bounded `task-status` for routing observations and full `task-show` only for explicit diagnostics. Native child state, Core/lifecycle records and product acceptance are separate facts.

Authority recovery targets a Task ID selected explicitly or through a session already associated with it, and preserves that task's provenance and protected user bytes; it cannot approve a changed security baseline or remove a known old-child fence. `task-recover-state` requires `--task-id` or an already-associated `--session-id`. Legacy state is available only through explicit diagnostic/recovery paths and is never auto-adopted; unselected legacy bytes remain untouched. `UNKNOWN` remains UNKNOWN; the Controller can end or abandon the old task through a bounded path and fence late results without fabricating child `Completed`. If a child may still write shared files, handle that actual conflict. Host file changes, installation records, or a bootstrap run do not prove that the current Codex process loaded an update. See [task authority](docs/thaliris-task-authority.md) and [runtime recovery](docs/thaliris-runtime-recovery.md) for the exact procedure.

If the user explicitly changes execution mode during a task, `thaliris --task-id <id> task-mode ...` selects the Task ID through the global option before the command, then updates its mode with the current Authority digest and task-revision CAS plus the user's new instruction. `--task-id` selects a task but grants no authority. The operation changes only `execution_mode`; it does not rewrite the goal, boundary, invariants or acceptance. An active dependency can be explicitly disposed with `task-dispose-dependency` in the same Task ID, using the current handoff ID, task revision, lifecycle digest and a reason. This records `ABANDONED_DEPENDENCY` and risk without fabricating the child’s native terminal state, and fences late results for that handoff. The Controller must handle any actual shared-file write conflict. After disposition, a dual-CAS `task-mode` update can change the mode in the same task. The Controller associates the current session with `task-associate`, supplying the Task ID, session ID and expected Authority digest; this creates navigation only and does not authenticate a Host actor. `task-start` can also receive the current `--session-id` to establish task navigation.

See [integration](adapter/codex/README.md), [authority](docs/thaliris-task-authority.md), and [recovery](docs/thaliris-runtime-recovery.md). The [shared documentation](https://github.com/Iris0fTheValley/Thaliris/tree/main/docs), [Core canonical README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md) and [English version](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.en.md) stay in main. [Thaliris-DSH](https://github.com/Iris0fTheValley/Thaliris-DSH) is a sibling Host adapter using the same Core.

Shared semantics leave judgment with models: INDEX is model-maintained semantic navigation; Core only checks paths, CAS, size and links. The Controller selects retained knowledge, and role results never automatically become durable memory.

Historical migration regressions read original immutable Git blob bytes from `tests/fixtures/history/provenance.json`, validating both Git blob and SHA-256 identities. Current generated profiles do not establish historical ownership.

The [historical admission-fix archive](docs/historical/admission-fix/README.md) preserves the original patches and profile-byte source snapshot. Its profile-content rejection behavior is not the current active contract.


## Execution constraints

Semantic roles, responsibilities, routing, and readonly limits remain separate from execution models. A dedicated Codex installation can use codex-install --execution-constraint luna-only to bind every ordinary worker profile to gpt-6-luna/xhigh while retaining the same role IDs and instructions. The task authority contract must explicitly include:

```json
{"execution_constraint": "luna-only"}
```

Core stores this optional non-empty string as immutable intent. The adapter accepts only luna-only and validates each execution binding. The external anchor freezes validated profile and configuration hashes; children and mutable configuration cannot expand or remove the constraint. A fresh Host session is required after installation. Admission compares role-profile and public-config snapshots recorded at SessionStart; those disk observations do not prove the effective Host role map or CLI -c overrides. SubagentStart checks the Host-reported model for a constrained child. Missing or mismatched values leave the handoff unbound and deny later child tools, but the Hook cannot prevent the model invocation. The constraint forbids Astra profiles and per-spawn model overrides; this mode uses fixed Luna/xhigh role profiles. Outside this constraint, managed `PreToolUse` supplies omitted model/effort fields for the seven default-routed semantic roles; when only one is supplied, the other follows native omission semantics, and explicit values remain unchanged. An execution constraint or verified necessary exception may select another supported value. See the [execution-constraint port notes](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/docs/split-execution-constraint-port.md).

This feature requires thaliris>=0.4.6. Development tests must install the Core checkout used for this fix; the older monolithic wheel does not satisfy the split-package boundary.

## CI and platform compatibility

The CI matrix covers Ubuntu and Windows with Python 3.11, 3.12, and 3.13. Its default Core pairing comes from [release/core.lock.json](release/core.lock.json); only a manually dispatched workflow may select another core_ref. POSIX runtime-identity checks accept only the exact virtual-environment alias `lib64 -> lib` and verify that target drift is rejected. Hook transport treats only one document-leading UTF-8 BOM as transport syntax; repeated or misplaced BOMs and invalid UTF-8/JSON remain denied. Hook diagnostics emit bounded JSON boundary labels without payload or inferred deeper causes. CI and source tests do not prove that a currently installed Codex process loaded these contents.

## Runtime prompt layers

Global instructions carry shared authority/isolation boundaries and the one-shot
startup entry. The required bootstrap response delivers resident normal Controller guidance: startup/admission, routing, handoffs, evidence reuse, waiting,
Workstream endpoints, acceptance/review selection, durable admission and causal diagnosis. Its complete output has BEGIN/END markers; the same active context may suppress duplicate text for another workspace only after the complete result and END marker are visible. This acknowledgement is not persisted, and new sessions or fresh children never reuse it. Omit the digest after truncation to get the full current guidance again.
Project instructions retain shared boundaries and canonical pointers; the normal
Controller routine is not injected into every fresh child. The
[Controller procedures](docs/thaliris-controller.md) are canonical; retrieve exceptional
recovery/Host maintenance only when needed. The installed pinned runner's
`controller-instructions` returns an index; `controller-instructions --resident`
recovers complete normal guidance; `controller-instructions --section <name>`
retrieves an exact missing section. Compare complete normal task context plus retrieval
cost and delivered quality, rather than the shortest prompt.
Native role prompts own current-role execution style, delegation and endpoints.
Fresh selected handoffs keep unrelated Controller procedures out of child injection;
rules remain retrievable on demand within authority. Each
invariant has one normal runtime authority; rationale and mechanical design live in
[Codex protocol](adapter/codex/README.md) and [Core prompt design](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-prompt-design.md).

First continue independent work that should take priority, then decide whether a necessary
dependency needs waiting. This applies at every authorized parent layer, including an
Implementer, Focused Implementer or Reviewer waiting for an Investigator Scanner. Each
layer observes only direct dependencies. Executors own observation of their tests,
builds, processes and CI, using those tools' actual waiting capabilities. A parent waits
only for an unfinished necessary direct child when no higher-priority work remains.
After a complete handoff, the child advances its work without parent patrol. Children
report completion, key blockers, decision-changing discoveries or necessary upper-level
decisions. A child FINAL or decision-changing unknown ends that slice.

Event-driven waiting takes precedence. First confirm the current Host's actual tool
maximum, meaningful-event early return, user interruption and child notifications;
unconfirmed capabilities remain UNKNOWN. When event early return and user interruption
are confirmed and there is no interim decision, normally use the supported 60-minute
window (`timeout_ms=3600000`). This is a maximum window; a meaningful event can wake the
parent early and its result is used directly. Shorten the window only when a brief stage
check is necessary or early return is unreliable: about 60 seconds for a very short task,
10–60 minutes for an ordinary task, or about 30 minutes for a long-task stage check. These
are contextual recommendations, not hard limits. Follow actual tool limits and explicit
applicable higher-level limits; do not change or bypass Host behavior to extend them.

Native terminal events, ordinary child messages, timeouts, exceptions and UNKNOWN are
distinct evidence. Messages and timeouts do not prove completion; exceptions do not
fabricate terminal evidence. Do not substitute `sleep`, patrol, progress pollers or
per-child timed loops for meaningful events. After timeout, reassess necessary direct
dependencies and available independent work. A wake-only V2 result needs one available
exact native status check (such as `list_agents`); proved completion needs no second
confirmation. The Hook preserves caller wait arguments and does not automatically extend
or take over a timeout. Independent Task IDs may proceed in parallel. Within one Task ID,
multiple bound children may run simultaneously, with at most one unbound dispatch
reservation awaiting association. The Controller chooses parallel work from its dependencies;
overlapping writes in one worktree need coordination, while independent worktrees can carry
separate changes.

Hook failures emit a bounded JSON diagnostic on stderr identifying the receive,
strict decode, JSON syntax/shape, dispatch, maintenance-contract or runtime-identity
boundary. They contain no payload or exception contents and do not establish a deeper
root cause or change refusal/identity checks. One leading UTF-8 BOM is still accepted
only at the Hook document boundary. Reviewer `READY` reports its selected read-only challenge; the Controller integrates it with the original objective, criteria and other available evidence when deciding product completion.

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
UNKNOWN. Native execution termination, product acceptance and task cancellation or
abandonment are separate facts. The Controller can end management through a bounded path
even when a child remains UNKNOWN; late results cannot re-enter a terminated task. Known
shared-write risks still need handling. SubagentStop is optional and its absence does not
undo other supported evidence. A contradiction or identity conflict restricts operations
that depend on that evidence, not unrelated ordinary work. Real Host stability of identity
fields across SubagentStart and PreToolUse remains UNKNOWN; synthetic tests do not prove a
Host protocol. Final product acceptance remains separate from lifecycle observations, and unverified
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

E and F are cost hypotheses based on the observed D route, not required role
sequences for current tasks. The Reviewer assigned semantic acceptance in the F
counterfactual belongs only to that estimate. The current Controller decides
product completion from the original objective, criteria and available evidence;
Reviewer remains an optional independent challenge.

**E — All-Sol counterfactual.** Keep D's task, topology, role sequence and lifecycle unchanged, but replace Luna Investigator/Implementer nodes with Sol. Input/context replay is held approximately constant; only output is adjusted using the observed A/B output-efficiency ratio (`79.8k / 30.3k ≈ 2.64×`). This predicts approximately **$3.67** for an all-Sol D-shaped run versus **$2.475 observed**, implying roughly **32.6% routing savings** from heterogeneous execution if D-level quality is preserved. Without the output-efficiency adjustment, the simple same-token estimate is about **$3.94**. This remains a counterfactual until run.

**F — Semantic-Convergence Cut (counterfactual, not run).** Keep D's architecture and high-capability semantic nodes, but terminate the Sol Focused Implementer once the core implementation and hard invariants are established. Broad tests, build/lint closure, deterministic compatibility fallout and small repairs move to a fresh Luna Implementer. The modeled route assigns a fresh Sol Reviewer for an independent semantic challenge; this does not make a Reviewer or separate closing role mandatory for current tasks. Trace-based estimation removes roughly **1.87M Sol input / 15.3k Sol output** and adds approximately **0.7–1.3M Luna input / 8–16k output**, predicting **~$2.06–2.07**, or roughly **16–17% below D**, while targeting the same 8.3-level result. Quality remains explicitly unknown until tested.

### Bottom line

The benchmark currently supports a narrower claim than “multi-agent is better”:

> **Weak-model orchestration alone did not improve aggregate quality. In historical D, selective placement of stronger intelligence at semantic implementation and independent challenge points did. Those observations do not require a Reviewer or separate closing role in new tasks.**

It also exposes the next optimization target: **not less high-capability implementation, but shorter expensive-context lifetime**. High-capability models should remain available for work that genuinely requires their reasoning during execution; once the semantic solution has converged, deterministic closure can move to cheaper fresh workers instead of repeatedly replaying a large Sol context.

## Benchmark boundary

`benchmarks/abcd/` may contain complex collectors, formal authority, and
offline scoring. The production `thaliris` package does not depend on D11,
formal registries, capture authority, or benchmark receipt issuers. Benchmarks
observe production; they do not define production architecture.

See [DESIGN.md](DESIGN.md) and
[docs/thaliris-routing-protocol.md](docs/thaliris-routing-protocol.md).

## README maintenance

The [Thaliris Core Chinese README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md) and [English README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.en.md) are canonical for shared semantics and full ABCD results. All three repositories retain the complete shared project narrative. Synchronize shared changes across both languages in each repository, while keeping runtime capabilities and limits grounded in each adapter's own contract.
