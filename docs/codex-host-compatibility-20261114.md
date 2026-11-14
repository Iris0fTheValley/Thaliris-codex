# Codex Host compatibility by capability and hook shape (2026-11-14)

This record replaces exact-version Host compatibility with capability and
hook-shape checks. It supersedes the version allowlists described in the
[2026-10-28](codex-host-compatibility-20261028.md) and
[2026-11-11](codex-host-compatibility-20261111.md) records. Those records stay
as history. The builds listed below are evidence observed on this date, not
requirements: a build that is not listed takes the same checks.

## What decides support

| Surface | Before | Now |
| --- | --- | --- |
| `features.multi_agent_v2.multi_agent_mode_hint_text`, `developer_instructions` | Exact `codex-cli` allowlist fast path, else isolated probe | Isolated probe for every build; a definitive result is cached per binary SHA-256, config leaf and probe source (`~/.thaliris/host-capability/`) |
| Probe wrong-type evidence | stderr regexes (`invalid type: integer … expected a string`, untagged `FeatureToml`) | Behaviour: non-zero exit before any Responses request, then a successful repeat of the accepted run. Error text only corroborates; a failure attributed to an unrelated config location stays `UNKNOWN` |
| Binary selection for the probe | `codex` on `PATH` only | `THALIRIS_CODEX_EXECUTABLE`, then `PATH`, as in the adapter's provenance path |
| Model catalog online freshness | Cache `client_version` had to equal the parsed CLI version | The isolated cache's own `client_version` is the key; a parsed CLI version only corroborates, and a contradiction stays unverified |
| Model catalog provenance | Unparseable version line blocked export and reuse | Version line is provenance; absent or unparseable is `UNKNOWN`. Reuse stays bound to the binary SHA-256, and launchers never qualify |
| Hook shape | Not checked | `doctor` and `codex-install` report `host_hook_shape` from the Host's embedded generated hook schemas |

`UNKNOWN` and `INCOMPATIBLE` keep the previous outcome: the user's value is
preserved and nothing is written. `VERSION_SUPPORT_UNKNOWN` stays as the
persisted status name so existing receipts and transition journals remain valid.

## Hook-shape check

Codex compiles `codex-rs/hooks/schema/generated/*.command.input.schema.json` into
the CLI with `include_str!`
([schema_loader.rs](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/hooks/src/engine/schema_loader.rs)).
`hook_shape.embedded_schemas` reads those JSON objects from the binary's bytes;
it never runs the binary. `app-server generate-json-schema` exposes only the
`HookEventName` enum, not the hook input schemas, so it is not used.

The check requires, for each of the seven registered events, a schema whose
`hook_event_name` constant matches, and every input key the adapter reads
(alternatives such as `tool_name|tool` or `tool_use_id|call_id|tool_call_id`
count once). `agent_id` and `agent_type` must be declared for prompt and tool
events but are absent for root actors at runtime. Observed multi-agent tool names
are matched against `POST_TOOL_MATCHER`; without observations the matcher result
is `UNKNOWN`. A custom `features.multi_agent_v2.tool_namespace` in user config is
read, never written, and reported `INCOMPATIBLE` when the matcher cannot select
its names. The overall result is never a runtime refusal.

At runtime, a hook payload that lacks a required key keeps its existing
fail-closed handling. The session's `runtime.json` gains at most 16 entries
`{"status": "UNKNOWN", "event": …, "missing_keys": […]}`, and `doctor` lists them
under `host_hook_shape.runtime_payload_gaps`.

## Observed builds (evidence)

| Build | Binary SHA-256 | Hook shape | Mode hint probe | Wait guidance probe |
| --- | --- | --- | --- | --- |
| `codex-cli 0.165.0` (`%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`, on `PATH`) | `d4b2e6a054ea1dfe53217f9d8942c5f8a9f4b76171a1e0bb76ced5759915300a` | COMPATIBLE (embedded schemas) | SUPPORTED | SUPPORTED |
| `codex-cli 0.167.0-alpha.4.1` (Desktop `OpenAI.Codex_26.1106.6628.0`) | `83f5c2dd2ac2902e0d96ba5d8ccdd27d513f57df4a9ab73e06a5a518028e9a2f` | COMPATIBLE (embedded schemas) | SUPPORTED | SUPPORTED |
| `codex-cli 0.169.0-alpha.11.1` (Desktop `OpenAI.Codex_26.1111.2228.0`) | `094d4db493de22025712cc5963854e7654b7c97f4cee795e3e986270a0f4f6b4` | COMPATIBLE (embedded schemas) | SUPPORTED | SUPPORTED |
| Upstream `rust-v0.169.0` source schemas (test fixtures) | n/a | COMPATIBLE | not run (no binary downloaded) | not run |

The probes ran in disposable homes against a loopback sink. On every build the
integer run exited non-zero before any request. On `0.169.0-alpha.11.1` it exited
1, and stderr corroborated with
``in `developer_instructions` `` and, for the mode hint, the untagged
`FeatureToml` error ``in `features.multi_agent_v2` ``. The generated hook input
schema blobs are identical from `rust-v0.165.0` to `rust-v0.169.0`; the pinned
fixtures and their blob SHAs are in
`tests/fixtures/codex-hook-schemas/rust-v0.169.0/`.

## Upstream 0.168–0.169 changes reviewed (source, `rust-v0.169.0`)

- `features.multi_agent` is deprecated in favour of `agents.enabled` (#59479).
  `features.multi_agent_v2` stays a stable feature, and when it is enabled it is
  selected before `agents.enabled` is consulted
  ([config/mod.rs](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/config/mod.rs#L1742)).
  The adapter never writes `features.multi_agent`. No change is needed.
- `MultiAgentV2ConfigToml` still declares `multi_agent_mode_hint_text: Option<String>`
  ([feature_configs.rs](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/features/src/feature_configs.rs#L352)),
  and an empty custom value still renders no `<multi_agent_mode>` fragment
  ([multi_agent_mode_instructions.rs](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/context/multi_agent_mode_instructions.rs)).
- Guidance changes (#59732 omit guidance when `disable_native_tools`, #59531 roster
  in environment context, #60011 hosted tools) do not touch the leaf. The adapter
  does not set `disable_native_tools`.
- Hook tool names are `namespace + name` for namespaced tools
  ([tools/mod.rs](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/tools/mod.rs#L50)).
  The default V2 namespace `collaboration` is matched by `POST_TOOL_MATCHER`.

## Known limits

- A custom V2 `tool_namespace`, and the V1 `multi_agent_v1` namespace (present
  since at least `rust-v0.162.0`), produce hook names such as `teamspawn_agent` or
  `multi_agent_v1send_input` that `POST_TOOL_MATCHER` and `_tool_basename` do not
  select. The check reports this; the matcher itself is unchanged here.
- A launcher script (`.cmd`, `.ps1`, `.js`, `#!`) gives no binary identity: the
  config probe runs each time, catalog reuse is not available, and the hook-shape
  check is `UNKNOWN`.
- macOS managed preferences cannot be proven absent, so the config probe stays
  `UNKNOWN` there.
- None of these checks prove that a running Desktop session loaded the config or
  hooks.
