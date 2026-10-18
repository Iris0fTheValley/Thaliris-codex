# Codex Host model-catalog maintenance report

This report describes the Host-wide Codex model-catalog path. It is not a Thaliris project-local role profile: the managed surface is the root configuration field `model_catalog_json`, shared by models in the Host's `CODEX_HOME`. The accepted managed catalog lives at `CODEX_HOME/thaliris-model-catalog.json`; project source edits alone do not run the Host maintenance operation.

## Provenance and ownership

The `native_model_catalog` receipt records the selected catalog path, prior-absence state, exact managed fragment, catalog SHA-256, and source evidence (`kind`, `cli_version`, `upstream_sha256`, and freshness evidence). This separates three facts: a catalog bundled with a CLI build, a catalog actually fetched online, and the managed catalog derived from one of those sources. The managed file is a projection with an ownership receipt; it is not itself a fresh upstream response. Receipts that manage this required catalog use `thaliris-authorized-host-installation-v2` and explicitly declare the `receipt-owned-model-catalog-v1` capability; installations without a managed catalog remain on v1. The new reader still accepts the prior v1 receipt for compatibility; a successful authorized install/upgrade that manages the catalog writes the v2 form. An older reader that does not recognize v2 rejects install or uninstall before mutation instead of silently treating the catalog as unmanaged.

The `codex-install` maintenance contract handles installation, upgrades and intentional low-frequency refresh. Online is the default source. Selecting `bundled` is explicit and leaves online freshness `UNKNOWN`; an existing online catalog is not silently downgraded. Source failures preserve the prior catalog with `UPSTREAM_REFRESH_FAILED_PRESERVED`. User-edited root configuration or catalog bytes are preserved with the appropriate `USER_*_PRESERVED` outcome, including `USER_CHANGED_PRESERVED`, rather than overwritten. Catalog changes use the existing version-journal and recovery path. A catalog compatibility failure returns `ok: false` with `TEMPLATE_INCOMPATIBILITY_PRESERVED`; a required online export failure returns `ok: false` with its preservation status. Both are decided before Host transition writes, preserving the existing Host generation. A preserved user-owned catalog can coexist with completion of other authorized Host work, but `catalog_goal_met` remains false and the result requires manual follow-up.

### Compatible reuse and explicit refresh

Ordinary installation and update reuse an already owned catalog when its exact
configuration fragment and catalog bytes still match the receipt, the selected
source matches, and its complete `reuse_contract` matches the current executable
SHA-256, CLI version, transformation implementation and required roster contract.
The transformation digest includes the exact target, known adjacent lines and
transformation function; the roster digest includes both matched and known-absent
model sets for the selected source. New receipts persist these identities.
Legacy receipts remain readable, but missing or unknown reuse schemas, unavailable
transformation source, uncertain executable identity and changed contracts require
a real export and its usual validation. Launcher-script bytes cannot establish
the identity of the underlying Codex binary and therefore do not enable reuse.
Older readers reject the additional ownership field before mutation.

Successful reuse reports `status: MANAGED`, `compatible_reuse: true`, and
`catalog_goal_met: true`. These describe the compatible managed transformation;
`online_freshness: UNKNOWN` describes the current operation's lack of a fresh
online observation. The receipt's historical source evidence remains provenance.
Applying an existing online receipt alone never establishes current freshness.
Offline availability does not prevent an unrelated update when compatible reuse
is proven, and a catalog-only no-op preserves catalog, config and receipt mtimes.

The approved maintenance intent can set `refresh_model_catalog: true`. This
bypasses reuse and requires a real export even if all identities match. A failed
refresh preserves the old generation and reports freshness `UNKNOWN`. Only a
successful online export with the existing fresh-cache checks can report
`VERIFIED` for that operation. Bundled exports and bundled reuse always report
`UNKNOWN`. Interrupted transitions retain the exact planned bytes; a journal
claiming compatible reuse cannot satisfy an explicit refresh intent.

Optional prompt-field capability checks retain their known-build fast path and
isolated loopback probe for unknown builds. Persistent probe-result caching is
deferred: the current mode-hint and wait-guidance ownership receipts do not
record a probe observation, binary identity, capability implementation or
isolation-environment evidence. Inferring support from those ownership records
would weaken the evidence boundary. Unknown or present system configuration
continues to prevent the probe; no cached support bypass is introduced.

### Project-loss recovery and retained backing data

Auxiliary restoration and its actor/Authority checks are isolated from ordinary
SessionStart dispatch. A failed receipt or unavailable restoration evidence reports
`CATALOG_RECOVERY_FAILED` with `ok: false` on stderr, preserves unproven bytes, and
does not stop project discovery. A discovered project receives the original native
input once, including a leading UTF-8 BOM and transport whitespace; its stdout,
stderr and exit result pass through unchanged, with the recovery diagnostic added
to stderr. An unrelated directory returns success after startup validation even
when auxiliary restoration failed. Invalid runtime identity, Hook ABI, malformed
native actor input and the existing pending Host transition preflight still reject
startup. This isolation grants no restoration or task authority: uncertain actor
checks skip restoration, and the original Hook retains its managed-control refusal.

`codex-maintenance-plan codex-install` proposes `catalog_recovery_project_root` from `--root` by default; `--catalog-recovery-project-root` selects another absolute project path and `--catalog-recovery-source-root` optionally selects an additional source path. These are proposed contract fields, not authorization by themselves. Only a contract carrying the human-authorized selection stores `model_catalog_project_loss_recovery` in the receipt. Legacy receipts without a policy report `RECOVERY_POLICY_UNKNOWN`; SessionStart does not infer a recovery target from the current directory, project history, or a missing receipt.

On an actual Host `SessionStart`, the installed Host entry validates and invokes the pinned runtime before project dispatch. It checks the exact selected project activation marker and any selected source directory. If the selected project or source has disappeared, moved, or no longer has the expected marker, recovery removes only the exact receipt-owned `model_catalog_json` field when the field and backing catalog still match their recorded bytes. It restores the previous absent-field state; it never deletes `thaliris-model-catalog.json`, and a successful removal reports `backing_artifact_status: RETAINED_REFERENCE_SAFE`. A detected field edit (`USER_CHANGED_PRESERVED`), changed catalog (`CATALOG_CHANGED_PRESERVED`), missing policy (`RECOVERY_POLICY_UNKNOWN`), unknown ownership, malformed payload, unfinished transition, or failed runtime validation preserves the evidence and does not claim recovery. Repeated SessionStart is idempotent after a proven restoration. The one-shot `restored` proof is recorded only when recovery removes the exact owned field. If the field is already absent without earlier proof, recovery reports `RECOVERY_PROVENANCE_UNKNOWN`; that user deletion or ambiguous crash state cannot authorize a later reclaim. An existing completed restoration proof remains valid. This is a check at native session entry, not a filesystem watcher or project reconstruction service.

Uninstall likewise removes only the matching configuration field and retains the physical catalog file as reference-safe data. The committed uninstall generation archives its exact ownership evidence. A later authorized upgrade can reclaim the retained catalog only when the field is absent and the archived catalog bytes still match the recorded digest; changed or unproven bytes remain user-owned. This supports a controlled compatibility sequence: the current reader uninstalls v2 first, an older reader can then install, and a later current-reader upgrade can reclaim only the exact archived catalog while the field remains absent. After a project-loss restoration, a later authorized upgrade may reclaim the catalog once only when the receipt's exact `restored` evidence and catalog digest still match. Successful reinstatement clears that restoration marker, so later field loss cannot reuse it. Neither path treats a missing field as permission to delete the backing file.

The configuration writer checks the observed bytes again immediately before atomic replacement. A non-cooperating writer can still race between that final comparison and replacement; this implementation does not prove preservation of a simultaneous, unobserved edit in that interval.

### Accepted transaction boundary

The human accepted this existing transaction boundary: preserve user changes already observed by the exact-byte recheck, retain the catalog backing file so a late reference cannot dangle, and disclose the remaining non-cooperating-writer interval. This is the scoped acceptance criterion, not a pending decision or a claim of exclusive-writer safety. The strict XFAIL records the simultaneous-writer limitation and remains visible in test results; it is not counted as a pass or hidden by weakening the preservation checks.

## Historical candidate verification

The final local adapter suite completed with **1240 passed, 10 skipped, and 1 strict XFAIL**. The catalog unit module completed with **44 passed**. The lifecycle recovery module has 27 collected cases: **26 passed and the same 1 strict XFAIL**. That XFAIL is `test_noncooperating_config_writer_in_replace_window_remains_preserved`; it does not provide evidence for unobserved simultaneous edits in the compare-to-replace interval.

The opt-in installed-runtime pair passed against a local mock Responses endpoint: the managed catalog and unpatched baseline each issued 15 requests, with parity for phase, model, effort and developer markers. The runtime also exercised the configured role profiles and nested Investigator Scanner. No Authorization header or external model request was observed. A `thaliris-codex 0.4.4` wheel built successfully, and zipimport loaded its packaged `catalog_recovery.py`. These checks cover the disposable installed runtime and package contents; they do not establish live Host installation or activation.

### Current compatible-reuse candidate verification

The catalog and Host maintenance contract modules passed **172 tests** using
Python 3.11 with the explicitly selected local Core source. A subsequent focused
run passed **36 tests**, including launcher-script rejection and stronger failed
refresh byte/mtime checks. The broader focused group also passed with optional
capability probes, mode hints, wait guidance, independent maintenance and catalog
uninstall coverage. These verify offline runtime updates with catalog reuse,
exact no-op mtimes, executable/version/roster/transformation/source invalidation,
legacy evidence migration, real explicit refresh, operation-based freshness,
user-edit preservation, journal tampering and changed-CLI replay refusal.
Release-selection integration tests verify bundle validation precedes candidate
execution and same-runtime maintenance preserves its verified release binding.
This evidence does not establish a production Host installation, current Desktop
loading or current online availability.

## Accepted content change

For each model, the managed change is narrowly limited to deleting this exact line from `model_messages.instructions_template`:

```text
- Avoid performing blocking sleep or wait calls longer than 60 seconds, as they may prevent you from communicating with the user for their duration.
```

No replacement suggestion is inserted. Every other instruction, metadata field, model entry and capability is preserved. Compatibility is source-content and model-roster specific: the exact sentence must appear as one complete line in its observed neighboring context for present known models. An absent, moved, rewritten, split/partial, embedded or repeated sentence is incompatible; a model known to omit the sentence that now contains it is also incompatible. Missing known models are accepted when the remaining catalog satisfies the transformation contract. Newly available models are accepted only with one exact full-line target. Incompatible cases return a compatibility status without planning new catalog bytes; the enclosing install returns `ok: false` and leaves the prior catalog, config, receipt and Host generation intact.

## Local source observation

Catalog admission is based on the selected source's contents and integrity checks, not a CLI-version allowlist: parseable versions are retained as provenance, while model identities, the exact target sentence and its known context, target count, and export/cache freshness are validated before installation. Changed or incomplete catalog content is preserved. The observed local provider export contained 10 models, 9 with the exact removable line. The bundled export contained 11 models, 10 with the exact line and one where it was already absent. These counts establish compatibility of those exported inputs only. They are not evidence that the online source was freshly fetched.

For an online export, the adapter preserves the selected provider configuration and file-backed auth in a disposable `CODEX_HOME`, removes only an already receipt-owned root catalog override, and starts without the original model cache. Unsupported external credential stores and remaining profile catalog overrides are refused. A successful CLI exit and stdout are insufficient: acceptance also requires a newly written cache timestamp within the export interval, the expected client version, a nonempty cache identity and model list, matching cache/export model identities and any supplied templates, and an unchanged executable hash. The source evidence is `VERIFIED` only after those checks. An explicitly selected bundled source does not claim online freshness and keeps it `UNKNOWN`.

The opt-in runtime capture below exercised the bundled source, not an online refresh. A separate fresh online export was validated once against the cache/export identity and template checks; a later online attempt returned `ONLINE_FRESHNESS_UNVERIFIED` and was rejected with the prior catalog preserved. Online freshness is therefore supported by that one observation, not guaranteed for a later refresh.

## Evidence layers and current limits

The installed CLI's opt-in runtime check used a disposable `CODEX_HOME` and a local mock Responses endpoint. It observed `codex-cli 0.162.0-alpha.17.2` load the managed bundled catalog (11 models; 10 exact-template edits) and issue 15 actual local Responses JSON requests. The paired unpatched baseline also issued 15 requests; phase, model, effort and developer-marker evidence matched for every paired request. The capture observed no Authorization header and no external model request. It also observed the Controller's developer instructions, project `AGENTS.md` content and model-switch template; Implementer `gpt-6-luna/max`, Reviewer `gpt-6.1-sol/high`, and a fresh nested Investigator Scanner `gpt-6-luna/max`; a fresh child did not inherit Controller developer/history text; and a fork without an override retained its original developer instructions. This is isolated installed-process wire evidence, not a live user's Host or account test.

Two native delivery limitations were observed and reported separately from catalog acceptance. An explicit developer-instruction override on fork was absent from the outbound request; the original fork instructions remained. A cold resume after changing the role profile also omitted the updated role developer text. In both cases the managed run matched the unpatched baseline. The harness does not identify the native cause, and this change does not rewrite native fork/resume behavior.

Record these as separate states:

1. **Disk:** Host mutation was not performed in this workstream. The disposable runtime fixture read back its own catalog and config; that does not establish any user's global configuration state.
2. **Test process:** the opt-in capture directly observed the isolated installed CLI load its fixture's `model_catalog_json` and send real-shaped requests to the local mock. The current user's Codex process, catalog compatibility and activation remain `UNKNOWN`. A disk hash, receipt or `HostIntegration=ready` does not establish them.
3. **Existing session:** no pre-existing user session was inspected; whether a session created before activation has the catalog remains `UNKNOWN`.

This source and documentation work does not authorize or perform live Host maintenance. Current-process loading, existing-session behavior and a fresh online result are `UNKNOWN` absent their respective observations. The runtime check is opt-in (`THALIRIS_RUN_CODEX_RUNTIME_TESTS=1`) and is not a model-service or external-network test.
