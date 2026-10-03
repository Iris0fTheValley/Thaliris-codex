# Thaliris Codex adapter

This is the Codex Host adapter for [shared Thaliris Core](https://github.com/Iris0fTheValley/Thaliris), not an independent Core. It imports Core rather than bundling a copy.

The `thaliris-codex` distribution uses `thaliris_codex` and preserves the `thaliris` and `context` Codex commands. It owns native bootstrap, lifecycle, Hook trust, actor identity, doctor, recovery and generated model profiles. Core supplies the ledger, retrieval, evidence, memory and `thaliris.authority` API.

Use an isolated Python 3.11+ environment. Install reviewed Core before the adapter:

```sh
python -m pip install 'git+https://github.com/Iris0fTheValley/Thaliris'
python -m pip install --no-deps 'git+https://github.com/Iris0fTheValley/Thaliris-Codex'
thaliris version
```

For local development install `../Thaliris[test]`, then this repository with `--no-deps -e '.[test]'`, and run `pytest`. A real Host installation needs both wheels in a dedicated environment with system site packages disabled; executable or path-extending editable `.pth` files are rejected. The entire environment, including shared Core, remains pinned by the runtime manifest. Installing packages does not prove Host enablement, authorization or health.

See [integration](adapter/codex/README.md), [authority](docs/thaliris-task-authority.md), and [recovery](docs/thaliris-runtime-recovery.md). The [shared documentation](https://github.com/Iris0fTheValley/Thaliris/tree/main/docs), [ABCD protocol and historical evidence](https://github.com/Iris0fTheValley/Thaliris/tree/main/benchmarks/abcd) stay in main. [Thaliris-DSH](https://github.com/Iris0fTheValley/Thaliris-DSH) is a sibling Host adapter using the same Core.

Shared semantics leave judgment with models: INDEX is model-maintained semantic navigation; Core only checks paths, CAS, size and links. The Controller selects retained knowledge, and role results never automatically become durable memory.

Historical migration regressions read original immutable Git blob bytes from `tests/fixtures/history/provenance.json`, validating both Git blob and SHA-256 identities. Current generated profiles do not establish historical ownership.

The [historical admission-fix archive](docs/historical/admission-fix/README.md) preserves the original patches and profile-byte source snapshot. Its profile-content rejection behavior is not the current active contract.
