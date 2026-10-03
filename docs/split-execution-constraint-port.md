# Split-package execution constraint port

The source fix is immutable monolithic commit
`939806372c858926eb9aa17ec5e3c45b8c187595`. This port starts from Codex adapter
`158690bdc087fbe3ce5f4c61e4a356ddbac89e0e` and Core
`751ccea498ad89c6c77c622fb4efaee9be469326`.

Core owns the selected contract. Its minimal optional nonempty
`execution_constraint` string remains opaque policy intent in the immutable
contract, checkpoint, history and recovery truth. Codex validates the supported
`luna-only` policy and native execution snapshots. The adapter requires Core
0.4.3; no Core implementation is copied into `thaliris_codex`.

| Original fix surface | Split-package disposition |
| --- | --- |
| Three generated Focused Implementer profiles | Already exact independent output of the split baseline renderer; all eleven default profiles remain byte-identical to that baseline. Preserve the split renderer metadata. |
| `AGENTS.md` | Regenerated managed block from the split adapter renderer, preserving the file-path authority admission contract. |
| `README.md` | Incremental constraint guidance and explicit reviewed Core dependency pin. |
| Historical live evidence document | Retained with a clear monolithic-runtime label; does not verify the split candidate. |
| Role packs | Regenerated from the split renderer with the constraint guidance. |
| Role registry document | Default model/effort labels, split namespace preserved. Historical split registry ownership comes from an exact immutable Git blob independently checked against its renderer. |
| `src/thaliris/cli.py` | Ported install option to `thaliris_codex.cli`, retaining external Core imports. |
| `src/thaliris/codex_adapter.py` | Ported constrained installation, coherent profile validation, SessionStart comparison, diagnostic and owned-removal behavior. |
| `src/thaliris/lifecycle.py` | Ported profile/config observations, Astra denial and actual-model binding check. |
| `src/thaliris/roles.py` | Ported optional execution binding; semantic registry IDs and default bindings unchanged. |
| `src/thaliris/task_authority.py` | Adapted facade delegates contract truth to shared Core, validates supported policy and records/checks native snapshots. |
| Execution constraint tests | Ported to split imports, with direct facade validation and immutable split-document migration regression checks. |
| Single-handoff tests | Ported profile/config snapshots and constraint assertions; retained current split startup wording. |

Core's five-field default contract representation is unchanged. Recovery cannot
add, remove or replace a selected constraint through adapter callbacks. No model
routing or automatic upgrade policy enters Core. The runtime pin includes both
packages. Runtime lifecycle tests cover default roles, readonly boundaries,
nested Scanner inheritance, missing/mismatching models, profile drift, config
shadows, mixed installation and one-shot contract binding.

A model mismatch is observed after native model selection. The hook leaves the
child unbound, retains the reservation and denies later tools; it cannot prevent
the first model invocation. Effective Host catalogs and CLI overrides remain
UNKNOWN beyond concrete rollout observations.
