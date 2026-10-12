# Codex Host model-catalog maintenance report

This report describes the Host-wide Codex model-catalog path. It is not a Thaliris project-local role profile: the managed surface is the root configuration field `model_catalog_json`, shared by models in the Host's `CODEX_HOME`. The accepted managed catalog lives at `CODEX_HOME/thaliris-model-catalog.json`; project source edits alone do not run the Host maintenance operation.

## Provenance and ownership

The `native_model_catalog` receipt records the selected catalog path, prior-absence state, exact managed fragment, catalog SHA-256, and source evidence (`kind`, `cli_version`, `upstream_sha256`, and freshness evidence). This separates three facts: a catalog bundled with a CLI build, a catalog actually fetched online, and the managed catalog derived from one of those sources. The managed file is a projection with an ownership receipt; it is not itself a fresh upstream response.

The `codex-install` maintenance contract handles installation, upgrades and intentional low-frequency refresh. Online is the default source. Selecting `bundled` is explicit and leaves online freshness `ONLINE_FRESHNESS_UNKNOWN`; an existing online catalog is not silently downgraded. Source failures preserve the prior catalog with `UPSTREAM_REFRESH_FAILED_PRESERVED`. User-edited root configuration or catalog bytes are preserved with the appropriate `USER_*_PRESERVED` outcome rather than overwritten. If the source produces the same catalog, the operation writes no catalog, configuration or receipt bytes. Catalog changes use the existing version-journal and recovery path.

## Accepted content change

For each model, the managed change is narrowly limited to deleting this exact line from `model_messages.instructions_template`:

```text
- Avoid performing blocking sleep or wait calls longer than 60 seconds, as they may prevent you from communicating with the user for their duration.
```

No replacement suggestion is inserted. Every other instruction, metadata field, model entry and capability is preserved. A missing, repeated or embedded target does not trigger fuzzy replacement: the implementation returns its compatibility status and preserves the prior catalog. Instructions supplied for newly available models remain intact.

## Local source observation

Admission is pinned to the exact output `codex-cli 0.162.0-alpha.17.2`; other versions return `VERSION_SUPPORT_UNKNOWN`. The observed local provider export contained 10 models, 9 with the exact removable line. The bundled export contained 11 models, 10 with the exact line and one where it was already absent. These counts establish compatibility of those exported inputs only. They are not evidence that the online source was freshly fetched.

For an online export, the adapter preserves the selected provider configuration and file-backed auth in a disposable `CODEX_HOME`, removes only an already receipt-owned root catalog override, and starts without the original model cache. Unsupported external credential stores and remaining profile catalog overrides are refused. A successful CLI exit and stdout are insufficient: acceptance also requires a newly written cache timestamp within the export interval, the expected client version, a nonempty cache identity and model list, matching cache/export model identities and any supplied templates, and an unchanged executable hash. The source evidence is `VERIFIED` only after those checks. An explicitly selected bundled source does not claim online freshness and keeps it `UNKNOWN`.

The opt-in runtime capture below exercised the bundled source, not an online refresh. No successful fresh online response was observed in this workstream, so current online freshness remains `UNKNOWN`.

## Evidence layers and current limits

The installed CLI's opt-in runtime check used a disposable `CODEX_HOME` and a local mock Responses endpoint. It observed `codex-cli 0.162.0-alpha.17.2` load the managed bundled catalog (11 models; 10 exact-template edits) and issue 15 actual local Responses JSON requests. The paired unpatched baseline also issued 15 requests; phase, model, effort and developer-marker evidence matched for every paired request. The capture observed no Authorization header and no external model request. It also observed the Controller's developer instructions, project `AGENTS.md` content and model-switch template; Implementer `gpt-6-luna/max`, Reviewer `gpt-6.1-sol/high`, and a fresh nested Investigator Scanner `gpt-6-luna/max`; a fresh child did not inherit Controller developer/history text; and a fork without an override retained its original developer instructions. This is isolated installed-process wire evidence, not a live user's Host or account test.

Two native delivery limitations were observed and reported separately from catalog acceptance. An explicit developer-instruction override on fork was absent from the outbound request; the original fork instructions remained. A cold resume after changing the role profile also omitted the updated role developer text. In both cases the managed run matched the unpatched baseline. The harness does not identify the native cause, and this change does not rewrite native fork/resume behavior.

Record these as separate states:

1. **Disk:** Host mutation was not performed in this workstream. The disposable runtime fixture read back its own catalog and config; that does not establish any user's global configuration state.
2. **Test process:** the opt-in capture directly observed the isolated installed CLI load its fixture's `model_catalog_json` and send real-shaped requests to the local mock. The current user's Codex process, catalog compatibility and activation remain `UNKNOWN`. A disk hash, receipt or `HostIntegration=ready` does not establish them.
3. **Existing session:** no pre-existing user session was inspected; whether a session created before activation has the catalog remains `UNKNOWN`.

This source and documentation work does not authorize or perform live Host maintenance. Current-process loading, existing-session behavior and a fresh online result are `UNKNOWN` absent their respective observations. The runtime check is opt-in (`THALIRIS_RUN_CODEX_RUNTIME_TESTS=1`) and is not a model-service or external-network test.
