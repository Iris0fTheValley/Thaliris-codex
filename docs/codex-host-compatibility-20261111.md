# Codex host compatibility record — 2026-11-11

This extends [the 2026-10-28 record](codex-host-compatibility-20261028.md)
with an isolated run of stable **Codex CLI 0.167.1**. The
[official changelog](https://learn.chatgpt.com/docs/changelog) lists that release
on 2026-11-10. No live Desktop installation, configuration, or activation was
performed.

## Runtime provenance and boundary

- Upstream release: [`rust-v0.167.1`](https://github.com/openai/codex/releases/tag/rust-v0.167.1),
  commit `0a94398fa60c4fac0e7659e4213a0a36e613dd46`.
- Asset: `codex-x86_64-pc-windows-msvc.exe`, downloaded from that release into a
  disposable temporary directory and executed as `codex.exe`.
- SHA-256: `c12aca02de615a9fcb76f955bf005a33f4b10b577f8a1730161953f57a1155b3`,
  equal to the release API asset digest; `--version` returned `codex-cli 0.167.1`.
- Native probes used disposable `CODEX_HOME`, workspace, authority store, user
  profile, source-built candidate runtime, and synthetic loopback Responses
  provider. They made zero external model requests and inherited no credentials.
- Candidate package identities were adapter `0.5.5` and sibling Core `0.5.2`,
  matching their canonical `pyproject.toml` versions. Imports were checked inside
  the candidate runtime. These are source-fixture wheels, not release artifacts
  or dependency-resolution certification. The adapter declares
  `thaliris>=0.5.3,<0.6`, while this sibling Core source declares `0.5.2`; the
  fixture installer uses `--no-deps`. A normal release dependency install against
  these exact source versions is therefore not established by the native smoke.

## Findings and changes

The real config capability probe returned `SUPPORTED` for both
`features.multi_agent_v2.multi_agent_mode_hint_text` and `developer_instructions`.
For each field it checked sentinel delivery, empty-string effect, and rejection
of an integer before any Responses request. The exact `codex-cli 0.167.1` build
therefore joins both configuration fast paths. Neighboring and prerelease builds
still require their own capability probe; versions never certify wait behavior.

The native verification scripts exposed three local fixture assumptions:

1. Source-wheel metadata was fixed at `0.5.2`, so installed adapter identity
   verification rejected the current `0.5.5` source. The native probe now passes
   canonical package versions to the fixture builder. Existing historical tests
   retain their default fixture version.
2. The catalog probe required a `<model_switch>` wrapper. This binary rendered
   the selected first-turn model template directly as developer base instructions.
   The probe now checks template content in actual developer messages and reports
   `catalog_instruction_delivery`; switch and replacement wrappers remain valid.
   The baseline/managed target-line comparison and native routing checks remain.
3. The disposable native probe's long temporary path exceeded the Windows legacy
   path limit during the atomic navigation write containing two full identity
   hashes. Its temporary directory and user-profile names are now shorter. Hashes,
   storage layout, authority checks, and production path handling are unchanged.

No adapter guard or lifecycle identity rule needed a compatibility change.

## Native evidence

`scripts/verify_native_spawn_runtime.py` returned
`CANDIDATE_HOOKS_DISPATCHED_IN_ISOLATED_NATIVE_HOST`:

- All seven candidate hooks were discovered, trusted, enabled, and dispatchable.
- Actual `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and `SubagentStart`
  events bound a fresh selected handoff to the exact parent session, turn, spawn
  call, returned path, and child UUID using official app-server activity.
- Actual child route was `gpt-6.1-sol` / `high`, matching the selected profile;
  its developer instructions reached the child Responses request.
- Wrong parent, stale turn, wrong call, and wrong path were refused.
- User hook, disabled hook state, user profile, unrelated configuration, and an
  unknown merger extension were preserved. Production home was not modified.

`scripts/verify_model_catalog_runtime.py --json` returned `PASS` with native
baseline/managed parity: 12 bundled models, 11 exact patched templates, 15 local
Responses requests per variant, and 79 selected template lines in the Controller
request. Fresh Implementer, Reviewer, and nested Investigator profile delivery,
model/effort routing, project instructions, and complete Controller guidance were
observed. The catalog transformation did not change fork/resume semantics.

Source and the binary's `app-server generate-json-schema --experimental` retain
`agentPath` / `agentThreadId` native activity identity and the four-field
initialize response (`codexHome`, `platformFamily`, `platformOs`, `userAgent`),
without `serverInfo`. Daemon identity therefore stays `UNKNOWN`.
V2 spawn retains `fork_turns`; V2 wait retains `timeout_ms` with source defaults
10,000 / 30,000 / 3,600,000 ms. Those source limits are not measured session
duration or completion-reentry evidence.

The [current hook contract](https://learn.chatgpt.com/docs/hooks) and pinned
`hooks/src/engine/output_parser.rs` require `updatedInput` together with
`permissionDecision: "allow"`. The adapter already emits that pair. Unsupported
PreToolUse fields can fail the hook while allowing the tool to continue, so they
must not replace the supported deny shape. No transcript was used as lifecycle
proof.

## Reproduction and limits

Select this isolated executable with `THALIRIS_CODEX_EXECUTABLE` for the two
native scripts. Run configuration effect probes explicitly with
`config_capability.probe(executable, field)`; the exact-version fast path must
not substitute for this evidence. The native spawn probe needs pytest for its
source-wheel fixture helper and the authoritative sibling Core source.

Focused regression completed with **325 passed, 1 skipped** (326 collected):

- `test_codex_host_compatibility`, `test_profile_compatibility`,
  `test_config_capability`, `test_mode_hint_config`, `test_wait_guidance_config`,
  and `test_model_catalog_runtime`: 204 passed, 1 skipped. The opt-in runtime
  wrapper was skipped; both native scripts were executed directly as above.
- `test_native_spawn_identity`, `test_native_execution_contract`,
  `test_native_wait_capability`, `test_repository_association`, and
  `test_cli_hook_transport`: 121 passed.
- `git diff --check` passed. Full adapter/Core regression was not run here.

- Full-fork explicit developer override and cold-resume updated role profile
  remain `NATIVE_LIMITATION` in both catalog variants. Original instructions were
  preserved; direct attached-child input was rejected as expected.
- Production Desktop activation, current live Host maintenance, effective wait
  duration, child-completion reentry, and external authenticated model behavior
  were not verified.
- The live chat's pinned-runner helper calls were refused with
  `THALIRIS_REPOSITORY_ASSOCIATION_UNKNOWN`. That is current actor-navigation
  evidence, not a latest-runtime regression or authority/admission proof. The
  isolated native run succeeded without weakening navigation or identity guards.
- Shortening this probe's fixture paths does not establish support for arbitrary
  production paths beyond the Windows legacy path limit.

## C2 local source candidate and packaging evidence — 2026-11-11

This addendum records local package candidates. The native fixture history above
remains the observed adapter `0.5.5` / Core `0.5.2` source pair; it is not rewritten
to describe these later candidate builds.

### Source baseline and scope

- Candidate versions are Core `0.5.4` and Codex adapter `0.5.6`. The adapter
  dependency remains `thaliris>=0.5.3,<0.6`.
- Core's selected compatibility baseline is commit
  `f0ee56320a7e3d8bcd04ca9369804af66851fee9`, previously locked as Core `0.5.3`.
  The baseline source changes were synchronized onto the current modified Core
  worktree without replacing its local changes. The synchronized Core paths are
  `README.md`, `README.en.md`, `docs/thaliris-task-authority.md`, `pyproject.toml`,
  `src/thaliris/__init__.py`, `src/thaliris/authority.py`, `src/thaliris/core.py`,
  `src/thaliris/errors.py`, `tests/test_core_cli.py`,
  `tests/test_mechanical_core.py`, new `tests/test_state_continuity.py`, and
  `uv.lock`.
- The existing Core task-get exact-object guidance and refusal recovery, plus its
  CLI/mechanical tests, remain alongside the imported schema-6 continuity,
  named-capacity, corrupt-anchor, and bounded-Git behavior. The local frontend
  routing policy and packaged Codex Controller guidance remain present; the
  Controller guidance and its generated repository document passed their sync
  test.
- Core and Codex README source version summaries and each package's source version
  metadata identify the local candidate pair. The committed
  `release/core.lock.json` still records the earlier `f0ee5632…` release baseline;
  it was not changed to claim an uncommitted candidate SHA. No commit, tag,
  publication, or live Host activation was performed.

### Wheels and dependency installation

`uv lock --check --offline` passed for Core. `uv build --wheel` built both
candidate wheels:

- `C:\Windows\Temp\thaliris-cda8d2b1-package\wheels\thaliris-0.5.4-py3-none-any.whl`
  — SHA-256 `297ca9c020cb0075ef22855e673890fe57e65469ba6237613957f1f488c6a789`
  (81,999 bytes).
- `C:\Windows\Temp\thaliris-cda8d2b1-package\wheels\thaliris_codex-0.5.6-py3-none-any.whl`
  — SHA-256 `deb8e3556b13e6fbb46e41b8c239f133af7731e91e587c15a91e29fd16faf8db`
  (302,543 bytes).

A new isolated Python 3.13.18 environment at
`C:\Windows\Temp\thaliris-cda8d2b1-package\venv-normal` installed
`thaliris-codex==0.5.6` with ordinary pip dependency resolution from the local
wheel directory. pip selected Core `0.5.4`; the install used no `--no-deps`, and
`pip check` reported no broken requirements. The installed `thaliris-core` and
`thaliris` Codex CLIs both returned help successfully. Package-resource reading
found the frontend policy in `thaliris_codex/controller_instructions.md`; an
installed Core CLI task-get with the Task ID returned `TASK_OBJECT_NOT_FOUND` and
the expected exact-object, `task-status`, and `task-show` recovery guidance.

### Regression and isolated native checks

- Core collection found 295 tests. The run had 287 passes, 7 skips, and one
  unrelated Git ownership-boundary failure: a child `git rev-parse HEAD` refused
  the source repo as a dubious owner. Rerunning that single test with a
  process-scoped `safe.directory` entry for the exact Core path passed. No global
  Git configuration was changed. The Core suite includes the imported continuity
  tests and the retained task-get diagnostics.
- The focused Codex compatibility, profile, configuration, catalog, native
  contract, repository association, CLI transport, prompt-sync, and runtime setup
  set collected 361 tests: 360 passed and 1 skipped.
- `git diff --check` passed for both source repositories, and the release lock
  remained unchanged.
- The isolated native spawn probe used official `codex-cli 0.167.1`, SHA-256
  `c12aca02de615a9fcb76f955bf005a33f4b10b577f8a1730161953f57a1155b3`. It built
  and imported Core `0.5.4` and adapter `0.5.6`, observed the native spawn and hook
  events, confirmed all seven candidate hooks dispatchable, matched child routing
  to `gpt-6.1-sol/high`, and refused wrong-parent, stale-turn, wrong-call, and
  wrong-path probes. The disposable run made zero external model requests and
  preserved production Host files.
- The isolated model-catalog probe returned `PASS` with baseline/managed parity:
  12 bundled models, 11 patched templates, 15 local Responses requests per
  variant, and 79 selected Controller template lines. It made zero external model
  requests. Explicit fork override and cold-resume updated-role delivery remain
  `NATIVE_LIMITATION`; the original child profile was preserved. Production Host
  activation and effective native wait behavior remain `UNKNOWN`.

The installed runner helper was unavailable in this turn because actor/repository
association remained `THALIRIS_REPOSITORY_ASSOCIATION_UNKNOWN`; child-owned build,
test, install, and isolated native processes were observed through their native
process tools. This does not alter or certify live Host state.
