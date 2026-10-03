# Historical monolithic-runtime evidence

This document records the old monolithic `939806372c858926eb9aa17ec5e3c45b8c187595` runtime. It does not verify the split `thaliris` Core / `thaliris_codex` packages or their current runtime identity. New split-package verification is recorded separately.

# Semantic roles and constrained native execution

Thaliris now supports an explicit `luna-only` execution constraint without
changing semantic role IDs, responsibilities, routing, isolation or readonly
restrictions. Unconstrained installations and tasks retain the default model
and effort mapping. The Root Controller's model remains a Host/user choice.

Install a dedicated Codex home with the identity-checked command
`codex-install --execution-constraint luna-only`. Its ordinary profiles execute
every registered worker role on `gpt-6-luna/xhigh`, using the existing profile
names and exactly the same developer instructions. The authority contract must
explicitly include `"execution_constraint": "luna-only"`. Per-spawn model and
effort overrides remain denied. Exceptional Astra profiles cannot be spawned
under this constraint; their existing authorization rules are unchanged for
unconstrained tasks.

The external authority anchor records the constraint and hashes of the exact
validated Host profiles and public configuration. A changed profile, changed
home, explicit role configuration shadow, or project profile shadow fails
closed. Children cannot establish or relax task policy. Constraint admission
also checks the profile hashes observed at the current session's SessionStart.
For a newly initialized repository, bootstrap first, then start a fresh Host
session before constrained task admission: the activation marker did not exist
at the initial SessionStart. Disk checks are configuration evidence; actual
execution requires native rollout observations.

## Native CLI observations

On 2026-10-03, two disposable empty Git repositories and separate Codex/user
homes used the real OAuth CLI `0.159.2`. Both installations registered and
trusted all seven hooks through the official app-server. No hook-trust bypass,
fake attestation, profile-specific role clone, or V2 feature change was used.
The live runtime was built from source based on
`4a754d2c50f8a83b878ed36286db877ad5a2ed45` plus the candidate implementation.
Its launcher SHA-256 was
`576fad0ab64918445117ffb01a6ded2e2874d1dd3a417f4bd5af5a615e91caef`.

Each Root admitted its task with a genuine one-shot Hook proof, sequentially
spawned the existing Focused Implementer and Reviewer with `fork_turns="none"`,
waited for native completion, and observed exact name-bound `completed` results
through `list_agents`. The Focused Implementer wrote one harmless marker; the
Reviewer read it without writing. Both tasks closed normally to `DONE`, revision
2. These observations are a focused integration probe, not a product benchmark.

| Case | Semantic role | Raw `session_meta.id` | Every observed `turn_context` model / effort |
| --- | --- | --- | --- |
| C, explicit constraint | Controller | `01a10048-cf64-7011-85f2-88d96e1a0c2b` | `gpt-6-luna / xhigh` |
| C | Focused Implementer | `01a10049-c642-7e11-8fb8-eeb57fd34fba` | `gpt-6-luna / xhigh` |
| C | Reviewer | `01a1004a-62f6-70a3-81d8-19392ff628dc` | `gpt-6-luna / xhigh` |
| D, no constraint | Controller | `01a10049-75ec-74d0-a772-d93f725585d8` | `gpt-6.1-sol / medium` |
| D | Focused Implementer | `01a1004a-3ef9-7d80-9c3e-d67b92bfeb69` | `gpt-6.1-sol / high` |
| D | Reviewer | `01a1004a-fa8e-7811-b5c5-1180de2ff3ce` | `gpt-6.1-sol / high` |

For each child, the raw session ID's SHA-256 matches the native lifecycle
`agent_id_hash`; the rollout's parent thread, agent path and semantic role match
the exact handoff binding. This uses the child's raw session identity, rather
than treating the Hook's shared root `session_id` as a child execution identity.
Native Start/Stop, the exact Completed responses, and successful task-close
supply completion evidence. Model request parameters alone are not the proof.

The initial C session bootstrapped the previously empty repository and was
correctly rejected at admission for lacking a profile snapshot. A fresh native
session then completed C. A C task-close path typo was corrected locally before
the successful close. Neither issue changed the policy or test design.

## Evidence and limits

The frozen external smoke bundle contains install results, full argv, event
streams, source/package pins, native rollout hashes, and a distilled verified
identity/model table. Authentication was copied directly to the isolated homes;
it was never read, printed, hashed or included in the evidence bundle.

[Constraint tests](../tests/test_execution_constraint.py) cover all registered
semantic roles, exact unchanged instructions, readonly roles, default bindings,
model override and Astra rejection, external profile/config pinning, unknown
user profile preservation, child policy mutation denial, nested Scanner
inheritance, and one-shot contract digest binding. Existing nested lifecycle,
task authority and runtime identity checks exercise their unchanged boundaries.
No live nested Scanner was needed for this one-file marker task.

After the live probe, deterministic synchronization updated diagnostic
recognition/removal of exact constrained profiles, historical document ownership
pins, generated documentation and error wording. The final generated default
and constrained profile bytes are compared with the live installations. Actual
model observations remain scoped to this CLI build and these sessions; Desktop
activation, other Host builds, and product benchmarks are not established by
this probe. The source checkout's prior manually edited managed instruction
differences remain outside this repair; its non-Thaliris user instructions are
preserved.

## Admission correction probe

The review correction makes a partially reverted Luna installation fail closed:
it detects an exact constrained profile only when that role's Luna mapping
differs from the default mapping, so roles already defaulting to Luna do not
make a pure-default installation look constrained. A mixed candidate now
raises `EXECUTION_PROFILE_CONSTRAINT_MISMATCH`; a pure-default installation
continues through the legacy path. Admission also compares the exact user and
project `config.toml` digests captured at SessionStart with current disk bytes,
alongside the known role-profile digest checks. These are disk observations;
they do not prove the Host's effective role map or CLI `-c` overrides.

Under a `luna-only` authority contract, the adapter checks the native
SubagentStart `model` field against `gpt-6-luna`. A missing or mismatching value
leaves the child unbound and the spawn reservation pending, so the existing
exact-child PreToolUse check denies later tool calls. The Hook cannot prevent
the child model invocation: Codex CLI `0.159.2`'s SubagentStart handler exposes
the model but treats that event as context injection only; only SessionStart
honors `continue:false` ([versioned Host source](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/hooks/src/events/session_start.rs#L142-L157), [event handling](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/hooks/src/events/session_start.rs#L203-L208)).
No effort value is inferred from the SubagentStart payload.

The first disposable C process had no observed SessionStart profile snapshot,
so constrained task-start failed with `EXECUTION_PROFILES_REQUIRE_FRESH_HOST_SESSION`
and created no task. A second fresh C process recorded the profile and config
snapshots and completed normally. The independent D process also completed.
Both tasks closed at `DONE`, revision 2, after exact native completion of the
Focused Implementer and Reviewer. The constrained C lifecycle recorded model
status `MATCH` for both children.

| Case | Role | Raw `session_meta.id` | Observed `turn_context` model / effort |
| --- | --- | --- | --- |
| C, constrained fresh retry | Controller | `01a100b1-e508-7ae3-b4f8-4ba82dc9dc16` | `gpt-6-luna / xhigh` |
| C | Focused Implementer | `01a100b2-ca7d-7462-9cd3-5bbc1e17a8e8` | `gpt-6-luna / xhigh` |
| C | Reviewer | `01a100b3-6825-7180-9bda-7bebf6ab1721` | `gpt-6-luna / xhigh` |
| D, default | Controller | `01a100aa-6ad0-7dc2-95d7-84e695a84869` | `gpt-6.1-sol / medium` |
| D | Focused Implementer | `01a100ab-29ca-7cc2-85bc-a0fab7f0ba8b` | `gpt-6.1-sol / high` |
| D | Reviewer | `01a100ab-e1a1-7921-8be5-70e6822d7cfb` | `gpt-6.1-sol / high` |

The new disposable evidence bundle is stored outside the source checkout as
`20261003-role-smoke-admission-v1/verified.json`; it includes the initial C
rejection and the successful retry, raw session identities, model observations,
and lifecycle bindings. The runtime executable pin for this probe is
`13b6aac85afa06c204fa650c06bfa60ecd9e406c1f4b4fbb1bc005005adc7c73`.

Focused checks used Python 3.11 with `PYTHONPATH=src`:

- `pytest -x -vv tests/test_execution_constraint.py` — 25 passed.
- `pytest -q tests/test_single_handoff.py::test_session_start_records_project_and_host_file_snapshot_without_catalog_evidence tests/test_single_handoff.py::test_role_content_update_by_existing_filename_does_not_look_like_new_identity tests/test_single_handoff.py::test_host_profiles_added_after_session_start_are_reported tests/test_single_handoff.py::test_task_start_blocks_host_role_added_after_current_session_start tests/test_single_handoff.py::test_task_start_blocks_roles_added_after_current_session_start` — 5 passed.
- `pytest -q tests/test_roles.py::test_knowledge_maintenance_and_formal_docs_stay_in_instruction_sources tests/test_roles.py::test_managed_renderer_matches_working_artifact_and_derives_added_role` — 2 passed.
