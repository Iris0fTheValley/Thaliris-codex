# Codex host compatibility record — 2026-10-08

This is a version-bound compatibility observation for the local Codex host. It
does not claim that another CLI, Desktop, app-server, or rollout surface has the
same behaviour, and it does not promote the observed build into the pinned wait
capability set. It is a compatibility-maintenance record, not a feature-adoption
one.

## Observed local host

- CLI executable (resolved by the installed Codex package, not by `PATH`):
  `C:\Program Files\WindowsApps\OpenAI.Codex_26.1002.7124.0_x64__2p2nqsd0c76g0\app\resources\codex.exe`
- MSIX package identity: `OpenAI.Codex_2p2nqsd0c76g0`, version
  `26.1002.7124.0`
- `codex --version` output: `codex-cli 0.162.0-alpha.2`
- responding app-server version: `UNKNOWN`
  - `initialize.userAgent` returned
    `thaliris-host-compat-probe/0.162.0-alpha.2 (Windows 10.0.26200; x86_64) unknown (thaliris-host-compat-probe; 1)`
    but that field is a client/agent description string, not a structured
    server identity, and this adapter deliberately does not read a daemon
    version out of it.
  - `initialize.serverInfo` is absent in this build, so the previously recorded
    evidence path `initialize.serverInfo.version` yields `UNKNOWN`.
  - There is no other authoritative runtime evidence for the responding daemon,
    so the daemon/app-server version stays `UNKNOWN` and `daemon_control_authority`
    and `live_role_catalog` stay `UNKNOWN`.

## Previous certified boundary

The text-pinned wait boundary recorded in
[codex-host-capability-20260920.md](codex-host-capability-20260920.md) is `codex-cli 0.155.1`
(upstream `rust-v0.155.1`). The adapter's pinned capability set is
`0.153.4`, `0.154.0`, `0.155.1`, plus the source-verified prerelease
`0.155.0-alpha.9.2`. The observed `0.162.0-alpha.2` is outside that set.

## Surfaces inspected

Only surfaces this adapter actually consumes were inspected.

| Surface | 0.162.0-alpha.2 | Classification |
|---|---|---|
| `initialize` response shape | `codexHome`, `platformFamily`, `platformOs`, `userAgent` | changed but mechanically compatible |
| `initialize.serverInfo` | absent | changed; already fails closed to `UNKNOWN` |
| `hooks/list` params (`cwds`) | unchanged | unchanged |
| `HookMetadata` fields (`key`, `sourcePath`, `handlerType`, `command`, `matcher`, `timeoutSec`, `source`, `isManaged`, `enabled`, `trustStatus`, `currentHash`, `eventName`) | all present | unchanged |
| `HookTrustStatus` values | `managed`/`untrusted`/`trusted`/`modified` | unchanged |
| `HookSource` values | still includes `user`, `plugin`, `project` | unchanged (additions only) |
| `config/read` params (`includeLayers`, `cwd`) and user-layer `version` | unchanged | unchanged |
| `config/batchWrite` params (`edits`, `filePath`, `expectedVersion`, `reloadUserConfig`, `keyPath`, `mergeStrategy`) | unchanged | unchanged |
| Host hook event names used by Thaliris (`preToolUse`, `postToolUse`, `sessionStart`, `userPromptSubmit`, `subagentStart`, `subagentStop`, `stop`) | all present | unchanged |
| Hook input keys (`agent_id`, `agent_type`, `session_id`, `turn_id`, `tool_name`, `tool_input`) | present in the binary | unchanged |
| Hook output keys (`hookSpecificOutput`, `hookEventName`, `additionalContext`, `permissionDecision`, `permissionDecisionReason`, `systemMessage`, `suppressOutput`) | present in the binary | unchanged |
| `currentHash` encoding | now `sha256:<hex>` | changed but mechanically compatible |
| `app-server` subcommands (`daemon`, `proxy`, `generate-ts`, `generate-json-schema`) | present | out of scope for adoption |

New host events that this adapter does not register (`permissionRequest`,
`preCompact`, `postCompact`, `sessionEnd`, `interrupt`) are additions on the
host side. Thaliris registers handlers for none of them, so they are out of
scope for adoption and change nothing in the current execution path.

## What was actually verified

1. `codex app-server generate-json-schema` was used to obtain the build's own
   authoritative protocol schemas, which is where the `initialize` and hook
   metadata shapes above come from.
2. A read-only stdio session against the real Codex home confirmed
   `hooks/list` returns exactly the seven expected handlers, all `enabled`,
   all `trustStatus = "trusted"`, with `source = "user"`, `isManaged = false`,
   `handlerType = "command"`, `timeoutSec = 60`, and `currentHash` in the
   `sha256:` form.
3. The trust **write** path was exercised against a scratch `CODEX_HOME`
   containing a copy of the real `hooks.json` and a `config.toml` without
   `hooks.state`. All seven handlers began `untrusted`; the
   `config/batchWrite` upsert of `hooks.state` returned `status = "ok"` with
   `filePath` equal to that scratch home's `config.toml`; all seven then
   reported `trusted` and `enabled`. `config/read` returned exactly one user
   layer, with a `version` string and seven `hooks.state` entries. The
   uninstall-side `expectedVersion` path is therefore still satisfiable.
4. No experimental feature was enabled, no new hook event was registered, and
   no trust state in the real Codex home was modified by this investigation.

## Behaviour deliberately not changed

`0.162.0-alpha.2` is **not** added to the pinned wait capability set. Adding it
would flip `host_explicit_blocking_wait` from `UNSUPPORTED`/`UNKNOWN` to `PASS`
and `selected_continuation_mode` from `UNAVAILABLE` to `BLOCKING_WAIT`, which is
a product-behaviour change and not part of compatibility maintenance. The
observed host therefore continues to fail closed:

- `host_explicit_blocking_wait` → non-`PASS`
- `selected_continuation_mode` → `UNAVAILABLE`
- `NATIVE_CHILD_COMPLETION_REENTERS_ROOT` → `UNKNOWN`

Because the pinned set is unchanged, no adapter output string changes either:
the reason reported for this host remains the existing
`no version-pinned wait capability is recorded for this Codex host`.

## Remaining unknown

- Live hook **payload fidelity** on `0.162.0-alpha.2` is `LIVE_NOT_OBSERVED`
  here. Hook input/output key names are present in the binary, but a real
  dispatched hook payload in a fresh session was not captured by this work.
- Whether the responding app-server build is the same build as the CLI is
  `UNKNOWN`; only `codexHome` agreement was observed.
- Native role-catalog activation remains `UNKNOWN`; disk profile equality is
  not native activation.
- Because the observed build is an `alpha` prerelease, it is not a suitable
  basis for a stable-version compatibility claim.

## New upstream capabilities observed but not adopted

These were noticed while ensuring they do not break the current adapter, and
are explicitly deferred to a separate product decision:

- mailbox / agent messaging primitives and new `wait_agent` semantics
- completion notifications and automatic child completion delivery
- new multi-agent V2 orchestration and scheduling/suspension behaviour
- additional hook events (`permissionRequest`, `preCompact`, `postCompact`,
  `sessionEnd`, `interrupt`)
- app-server `daemon` / `remote-control` management surfaces
