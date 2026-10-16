# Requirement acceptance and evidence continuity, 0.4.5

This change addresses the failure where known counterevidence reached Controller but
lost decision influence among local success reports. Discovery and transport alone
were already present. Controller must explicitly reassess the related user requirement
for the current candidate; tests, review, native completion and mechanical closure
remain distinct evidence and execution facts.

## Contract and acceptance evidence

| User requirement | Implementation and verification |
| --- | --- |
| Selected local context remains isolated | Only opaque requirement refs, candidate and selected durable paths accompany a handoff. `test_nested_handoff_inherits_opaque_lineage_without_global_text` checks nested selection without global requirement text. Existing fresh-child and authority tests remain applicable. |
| Low-cost recording of an already discovered local fact | `task-observe --observation-json` needs no payload file, task revision lookup or additional model call. Existing Hook identity binds the task, handoff and native producer. `test_readonly_child_appends_inline_observation_with_hook_bound_identity` executes the resulting CLI arguments. |
| Identity, candidate and nested source continuity | Core retains task, handoff ancestry, original candidate, source refs and producer. Adapter rejects forged observation selection; child observation results contain no unrelated global bodies. Existing explicit context retrieval retains its telemetry policy. See the Core provenance tests and Adapter forgery/nested tests. |
| New evidence remains available to requirement decisions | Append-only observations and exact-reference judgments persist separately. Status and existing Controller operation results expose unincorporated observations and latest candidate judgments with explicit totals/continuation. `test_controller_results_keep_unincorporated_evidence_visible` checks successful update, CAS conflict and DONE; child acknowledgements exclude global evidence bodies. Reading/acknowledgement cannot replace a requirement judgment. |
| Core does not classify semantic importance or acceptance | Observation recording does not produce FAIL, severity, blocker or an acceptance gate. Models author requirement applicability, current candidate, outcome and reasoning. Core validates structural references and persistence. |
| Repair can change the current judgment while preserving facts | `test_cross_candidate_judgment_and_new_evidence_preserve_history` retains C1 observations and prior judgments while assessing C2. Unknown/repair incorporates cited evidence without claiming requirement satisfaction. |
| Concurrent updates and recovery preserve observations | Separate-process append and Controller CAS race tests cover both legal lock orders, stale revisions, restart, paging and DONE retention. Clearing active work/pending results does not clear observations. |
| Old or abandoned results can remain historical evidence | Controller import records original native identity and status, including UNKNOWN/conflict, and identifies Controller as submitter. It neither reactivates a child nor resolves execution risk. The historical import test covers abandonment and conflict. |
| Curator maintains selected existing knowledge | `document-maintain` applies exact selected writes/deletes and optional INDEX replacement with file digest CAS, link checks and backup/rollback. Tests cover split/delete, stale digests, mutation failure recovery and refusal outside selected paths. New-only promotion remains separate. |
| Roles and event-driven execution remain optional | Source prompts retain selected local context, fresh sessions after FINAL, private Investigator working sets, optional Reviewer/Verifier/Curator and event-driven waiting. No new agent, stage, approval or scheduler is introduced. |

Core tests: `tests/test_evidence_continuity.py` in the shared Core repository.
Adapter tests: `tests/test_evidence_continuity_adapter.py`, existing role/prompt,
handoff/tree and authority suites. Canonical instruction sources generate the tracked
profiles and documentation; Core AGENTS stays Host-neutral.

## Verification record

- Core local full regression: 194 passed, 9 skipped. Integration/source provenance
  checks: 10 passed; the corrected concurrency expectation was subsequently checked
  in the complete Core CI matrix. Core commit `31f8e6212adbd27be2f8af1f21811811b0882695`
  passed [CI 38980670667](https://github.com/Iris0fTheValley/Thaliris/actions/runs/38980670667).
- The initial Adapter full run had 1418 passed, 10 failed, 10 skipped and 1 xfailed.
  This was not accepted as completion. An unnecessary blanket task-read refusal was
  removed to preserve the existing telemetry-only retrieval contract; Curator's
  explicit non-delegation wording was retained. The affected boundary regression
  then passed 348 tests, with 5 skipped.
- Role/prompt/authority/CLI regression had 204 passed and one newly added wording
  assertion failure; its equivalent semantic assertions were repaired and passed.
  Final observation/readonly/wait/CLI checks passed 48 tests. Counts overlap and are
  not presented as an independent combined total. The Adapter CI workflow performs
  the complete final platform matrix against the fixed Core commit above.
- Generated instructions check: current. Both 0.4.5 wheels build and install in a
  disposable environment; package versions/dependency metadata and seven packaged
  implementation/instruction files are checked against their canonical source bytes.

The Core race test accepts both legal serializations: two child appends, with the
Controller either committing first or failing its stale revision CAS. Earlier CI
exposed an assertion that omitted the valid Controller-first case; only the test
expectation changed, not product CAS behavior.

## Evidence boundary

These deterministic checks establish the persistence, provenance, authorization,
context-selection and prompt contracts. They do not prove that a future model will
always make the correct semantic judgment. No new ABCD benchmark or live Host
installation/activation is claimed. Frozen historical benchmark evidence is unchanged.
Local verification uses disposable environments; installed Host files are outside scope.

Legacy unmarked handoffs remain spawn-compatible. Their direct observations fail
explicitly when no requirement association exists; this is not a successful durable
record. Controller retains the returned fact and sources, registers the exact historical
association and imports it. New work selects registered requirement refs in the handoff.

An old handoff observation's candidate remains historical. Controller may cite it when
assessing another current candidate with explicit reasoning; no automatic truth transfer
or semantic acceptance inference occurs.
