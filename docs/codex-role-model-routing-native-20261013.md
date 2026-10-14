# Codex role model routing and native verification

This record covers managed role model selection in the Codex adapter. Passing source and test checks does not establish the profile stack loaded by a live Host.

## Historical basis

The preceding role-routing and managed-guidance migration is commit [`257df596fd2047b4ca819992fe1a388ed23b4ef9`](https://github.com/Iris0fTheValley/Thaliris-codex/commit/257df596fd2047b4ca819992fe1a388ed23b4ef9). The prior published bytes for five generated role profiles are preserved as an exact ownership fixture at [`tests/fixtures/role-model-routing-prompt-predecessor`](../tests/fixtures/role-model-routing-prompt-predecessor). Its provenance pins commit `7e1c11d0577441e01a1e6c6efea11362739f4767`, Git blob IDs, and SHA-256 digests; these are independent historical bytes, not ownership inferred from the current renderer.

## Candidate behavior

`roles.ROLE_MODEL_ROUTING_DEFAULTS` keeps model defaults separate from role identity and permissions. On an authorized managed dispatch to an ordinary named role profile, the adapter fills only omitted selection fields through the native `updatedInput` response. A supplied model and effort pair passes through unchanged; when only the model is supplied, the adapter leaves effort selection to Native. Frozen execution constraints and the existing role, parent, isolation, and lifecycle checks retain precedence.

Before reserving the dispatch, `profile_compatibility.check` checks only the selected target's observed definitions. It resolves the target by TOML `name` (with the native `config_file` identity hint when `name` is absent) and compares direct `model` and `model_reasoning_effort` fields. It does not treat `profile`, `profiles`, features, skills, or unrelated profile names as alternate model bindings. Matching definitions are allowed; a fixed-field conflict or an ambiguous/unreadable target returns a denial before reservation and leaves files unchanged. An unverifiable target remains `UNKNOWN`; this check does not prove which configuration layers a running Host loaded.

The source contract is pinned in [`profile_compatibility.py`](../src/thaliris_codex/profile_compatibility.py) to Codex `rust-v0.162.0-alpha.17.2`, commit `740e5af33c71225640e0c1c1555c514c2c93ab74`. The inspected native role projection reads direct `model` and `model_reasoning_effort` values. That source fact does not establish live Host activation.

## Verification record

The full source suite passed on Python 3.11 with exit code 0 before the final Native probes; its count was not retained. After the final prompt wording update, all 35 tests in `tests/test_prompt_contract.py` passed, including generated-output consistency, and two focused generated-artifact sync tests passed. `git diff --check` returned 0.

The trusted isolated Native CLI run used `codex-cli 0.162.0-alpha.17.2`; the candidate `lifecycle.py`, `profile_compatibility.py`, and `codex_adapter.py` hashes matched the installed package. The earlier managed routing pass observed these actual child contexts:

| Dispatch | Actual Native model/effort | Hook and context evidence |
|---|---|---|
| Default Reviewer | `gpt-6.1-sol/high` | Bound `thaliris-reviewer`; read-only sandbox and managed permission profile |
| Explicit Reviewer | `gpt-6-luna/max` | Bound `thaliris-reviewer`; read-only sandbox and managed permission profile |
| Nested default Investigator | `gpt-6-luna/max` | Bound `thaliris-investigator`; read-only sandbox and managed permission profile |
| Nested explicit Investigator | `gpt-6.1-sol/high` | Bound `thaliris-investigator`; read-only sandbox and managed permission profile |

The additional generic child omitted `agent_type`. Its actual Native context was `gpt-6.1-sol/low`, with `agent_type` and `agent_role` absent, and it returned its requested terminal marker. The Hook capture classified that spawn as role `unknown`; the managed lifecycle ledger did not change. This matches the unmanaged source branch, which returns without role routing or reservation.

For the same-name profile probe, the isolated personal `thaliris-verifier` definition fixed `model = "gpt-6.1-sol"` and omitted effort. A fresh default Verifier spawn was denied by the PreToolUse Hook with `THALIRIS_ROLE_PROFILE_BINDING_CONFLICT` before reservation. The lifecycle ledger hash was identical before and after. The original isolated profile bytes were restored exactly after the probe. These results demonstrate the tested temporary CLI behavior; they do not establish which configuration layers a desktop Host has loaded.

Desktop Host activation remains **UNKNOWN**. This pass did not separately exercise model-only native effort preservation, and no Hook-level readonly write denial is claimed; the managed child contexts were read-only, while a Native `CreateProcess` rejection is not Hook evidence.
