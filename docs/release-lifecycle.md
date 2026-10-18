# Release lifecycle

The release client selects a bundle, verifies both wheel archives, prepares a
runtime at its permanent physical path, and executes that candidate's own plan
and installer. Package versions describe compatibility; they never establish a
release or installation identity. The existing `thaliris codex-maintenance-plan`,
`codex-install` and `codex-uninstall` interfaces remain available.

## Human terminal interface

System Python 3.11 or newer is the only client prerequisite. Obtain and trust
`thaliris-bootstrap.py` from a selected release first. Obtain that release's
`release.json` SHA-256 from an independently trusted selection, then run:

```powershell
py -3.11 thaliris-bootstrap.py install --manifest https://github.com/Iris0fTheValley/Thaliris-codex/releases/download/RELEASE/release.json --manifest-sha256 TRUSTED_DIGEST --human-instruction "Install this exact Thaliris release into my Codex home."
```

Replace `RELEASE` and `TRUSTED_DIGEST` with the actual selected tag and 64-digit
digest. The instruction must be the actual human request. The client creates and
removes its own disposable pip bootstrap environment, installs the verified
archives there, and prepares a dedicated runtime without pip, setuptools or
executable `.pth` files. No checkout, manual pip/venv setup or project pytest run
is needed. The base Python standard library and operating system remain trust
dependencies. A standalone executable that works without system Python is deferred.

Use the same interface with these actions:

| Action | Behavior |
| --- | --- |
| `prepare` | Prepare and verify a candidate without changing the Host. |
| `install` | Generate a durable exact plan and execute the candidate installer. |
| `update` | Select the requested release and apply the same owned-byte installation contract. |
| `repair` | Reuse/reconstruct a verified candidate and retry installation under the same ownership rules. |
| `uninstall` | Execute the selected release's uninstaller, preserving unowned bytes and runtime/recovery evidence. |
| `status` | Read available release, candidate validity, installed disk identity, project generation facts and pending transition facts. |

`thaliris-release` (installed console) and
`python -I -B -m thaliris_codex.release_manager` expose the same actions after a
release environment exists. `--home` selects a Codex home, `--project` selects the
project whose definition facts are diagnosed, and `--cache` selects the final
physical runtime/state directory. Windows defaults use the current Codex package's
physical LocalCache; other platforms require `--cache`. A staged/offline bundle
can use a local manifest path and `--artifacts DIRECTORY`.

Maintenance actions save the exact low-level contract and return `saved_contract`.
If maintenance becomes pending, resume with `--resume SAVED_CONTRACT` and an actual
human retry instruction. This replays the original contract bytes, selected
executor, instruction, prior installation identity and recovery policy. It never
generates approval for a partial generation. Install/update/repair all retain the
normal ownership rules: neither damaged receipts nor modified runtime files gain
permission for broad overwrite or legacy adoption. Resolve those reported manual
actions explicitly. `--refresh-model-catalog` requests an actual upstream refresh;
ordinary same-release maintenance keeps the default catalog lifecycle behavior.

The high-level maintenance interface currently runs from a human terminal.
Managed shell automation is denied for public install/update/repair/uninstall
console, module and bootstrap forms, including compound calls. Automated Host
maintenance retains the existing checked, standalone exact-contract route and its
actor guards. Missing actor fields never establish Controller identity. A future
high-level native authority transport needs separate review; changing command
spelling or the human-instruction string supplies no such authority.

## Identity and reuse

`release.json` is canonical UTF-8 JSON and binds the expected repository, release
tag, full Core and Adapter source commits, both wheel filenames and SHA-256
digests, Python compatibility, Core state schema, Adapter protocol, managed hook
ABI, maintenance contract and runtime manifest format. Artifacts must name that
repository's exact release download paths. The runtime selection carries the
complete release binding. Both installed `direct_url.json` archive hashes must
match the release, in addition to validating the complete installed runtime
manifest and permanent-location anchor. Version equality cannot substitute.

Successful candidates have separate complete records outside their runtime.
Every reuse validates the original physical path, saved complete release binding,
saved runtime SHA-256, Core and Adapter provenance, console smoke and Host preflight.
Drift produces a cache miss and a new UUID directory; it never mutates the old
runtime. Failed attempts and concurrent attempts likewise retain distinct leaves.
Repeated updates use the installer to evaluate exact bytes and ownership; there
is no version-based shortcut that can report a corrupt installation as current.

Release-backed Host ownership uses a version-3 receipt with an explicit release
binding capability. The earlier version-1 and version-2 readers reject that
format. Legacy receipts remain readable, while an unrecognized release-binding
field in a legacy receipt is not promoted to release ownership.

Status keeps runtime identity, available-release skew, project facts, pending
transition state, live Host loading and restart completion as separate facts.
Loaded Host identity and restart completion remain `UNKNOWN` because disk
inspection does not observe the running Host. It also checks receipt-owned files,
the managed global instruction block, owned hook entries and the saved catalog,
mode-hint and wait-guidance fragments. User edits in shared files are preserved
and reported separately from runtime identity. Project generation facts are
read-only diagnostics; they do not authorize an old reader to trust future bytes.
`project_host_relation` compares the project's managed instruction digest with the
current reader and the exact validated installed runtime's read-only bootstrap
diagnostic, after the current Core and Adapter wheel hashes match the selected
manifest. `HOST_UPDATE_REQUIRED` means the project matches the current renderer
while the installed runtime expects different bytes; status recommends updating
the runtime before project initialization. A changed project reports `DIFFERENT`,
and missing or unverified reader evidence reports `UNKNOWN`. This comparison uses
the rendered instruction digest, not package version, and does not report whether
the running Host loaded either copy.
Status includes a read-only candidate reference inventory and preserves drift
evidence. Automatic runtime/failed-attempt garbage collection is deferred: there
is no complete native loaded-runtime reference oracle, and no safe deletion grant
is inferred from an apparently unused cache record.

## Build, gates and trust

`release/core.lock.json` is the single authoritative default Core pairing used by
both CI and release builds. It selects Core
`973f0f73b79142783be1eff6e6a639743de310a0`: the earlier CI pin
`2766a9ddee6671bd9154f2e067d630377a31799c` lacks explicit non-Git behavior required
by current Adapter acceptance. Both report version 0.4.6, which illustrates why
version checks alone are insufficient. Manual CI `core_ref` is a compatibility
experiment and does not change the release lock.

The tag-triggered `release.yml` workflow first calls the complete `ci.yml` source
suite as a reusable workflow, with no compatibility override, so release
validation uses the reviewed Core lock. It then builds each final wheel once,
constructs the manifest from those archives and exact checkouts, and generates
GitHub build attestations. Six Windows/Ubuntu Python 3.11–3.13 gates download those same bytes,
verify attested repository/workflow/source tag/source commit, then exercise the
actual artifacts through disposable bootstrap, runtime and temporary Host
integration. The final publish job depends on every gate and publishes only that
downloaded bundle. It never rebuilds for publication. The native Codex hook trust
operation is modeled in disposable Host tests; actual live Host loading is a
separate unverified platform boundary.

An attestation verifier should constrain all of these externally selected facts:

```text
gh attestation verify release.json --repo Iris0fTheValley/Thaliris-codex --signer-workflow Iris0fTheValley/Thaliris-codex/.github/workflows/release.yml --source-ref refs/tags/RELEASE --source-digest EXPECTED_ADAPTER_COMMIT --deny-self-hosted-runners
```

Apply the same checks to the bootstrap and wheel files if selecting trust through
GitHub attestations. GitHub documents [attestation generation and permissions](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations),
[verification identity constraints](https://cli.github.com/manual/gh_attestation_verify)
and [release publication APIs](https://docs.github.com/en/rest/releases/releases#create-a-release).
The workflow requires repository/platform attestation support and configured
workflow token permissions. Those remote capabilities, protected tag policy,
successful matrix execution and any published release are not established by
local tests or this document.

The stdlib client deliberately requires an externally selected manifest digest.
It does not implement an online Sigstore verifier or trusted automatic `latest`
discovery. A SHA-256 downloaded beside an unsigned manifest is insufficient. This
means a user must obtain a reviewed digest separately (or verify the GitHub
attestation with independently selected repository, workflow, tag and commit).
This practical UX limitation is retained until the full external trust/discovery
behavior is verified. The bootstrap itself must also be trusted before execution;
the manifest cannot retroactively authenticate code already running.

## Source development

Source checkouts use the existing editable development/test workflow and selected
Core checkout. Release clients do not run it. Local builds from uncommitted source
are verification fixtures and cannot claim publishable source provenance. The
release manifest builder rejects tracked source changes and requires the selected
release tag to resolve to the Adapter checkout commit. Final artifact publication
and production Host maintenance require their separate actual authority.
