# Codex host compatibility record — 2026-10-28

Version-bound compatibility maintenance for the local Codex host and the newest
upstream builds that the adapter can reuse without behavioural change. It follows
[the 2026-10-08 record](codex-host-compatibility-20261008.md); nothing here claims
live Desktop activation.

## Builds covered

| Build | Evidence | Result |
|---|---|---|
| `codex-cli 0.165.0` (local, upstream `rust-v0.165.0` Latest, `e374836b`) | source diff from `rust-v0.162.1` and isolated probe on the installed CLI | compatible; added to the config fast path |
| `0.166.0-alpha.5` (upstream `rust-v0.166.0-alpha.5`, `cc756aad`) | source diff from `rust-v0.165.0` only | mechanically compatible; uses the isolated probe, no fast path |

## Adapter changes

- The isolated config probe failed closed (`VERSION_SUPPORT_UNKNOWN`) for
  `multi_agent_mode_hint_text` on 0.165.0. The leaf sits inside the untagged
  `FeatureToml<MultiAgentV2ConfigToml>` (bool-or-table), so serde reports a
  wrong-typed leaf as `data did not match any variant of untagged enum FeatureToml
  in features.multi_agent_v2` rather than `invalid type: integer, expected a
  string`. That enum is unchanged since `rust-v0.162.1`; earlier builds only passed
  through the version fast path. The probe now accepts this diagnostic for the mode
  hint only. The integer value is the only difference from the two accepted runs.
  `developer_instructions` still requires its own string-type diagnostic.
- `codex exec` reads piped stdin (`Reading additional input from stdin...`) and
  waits for EOF. An inherited open pipe held the probe until its 15 s timeout.
  The probe now runs the CLI with a closed stdin.
- `codex-cli 0.165.0` joins the mode-hint and wait-guidance fast paths after
  the live probe on that exact build returned `SUPPORTED` for both fields: the
  sentinel was rendered as `<multi_agent_mode>…</multi_agent_mode>`, the empty
  string suppressed the fragment, `developer_instructions` reached the developer
  prompt, and both integer values were rejected before any request.

## Surfaces compared

| Surface | 0.162.1 → 0.165.0 | 0.165.0 → 0.166.0-alpha.5 |
|---|---|---|
| Hook command input/output schemas used (`pre/post-tool-use`, `session-start`, `subagent-start/stop`, `stop`, `user-prompt-submit`) | unchanged; new `model-request` event only | unchanged |
| Hook dispatch (`hooks/src/engine`) | payload passed as JSON value instead of string; plugin trust and environment-scoped hooks added | minor |
| V2 spawn/wait tool specs (`multi_agents_spec.rs`, `multi_agents_common.rs`) | unchanged | unchanged |
| V2 spawn handler | refactored into `thread_spawn::spawn`; same `task_name`/`message`/`fork_turns`/`agent_type`/`model`/`reasoning_effort` arguments | spawn moved under `agent/host`; tool arguments unchanged |
| Wait bounds (`DEFAULT_MULTI_AGENT_V2_{MIN,DEFAULT,MAX}_WAIT_TIMEOUT_MS`) | 10,000 / 30,000 / 3,600,000 ms | same |
| `MultiAgentV2ConfigToml` | adds `preserve_fork_prefix` (full forks only) and `disable_native_tools`; `multi_agent_mode_hint_text` unchanged | unchanged |
| Mode-hint rendering | body now a `ContentItem`; tags and text unchanged | unchanged |
| Role loading (`agent/role.rs`, `child_config.rs`) | adds layer bindings and optional `SubagentDefaultContextLimits` | unchanged |
| Model cache `client_version` | still whole `major.minor.patch` | same |
| Bundled catalog (`models.json`) | adds `gpt-6.1-terra`; catalog surgery reports `COMPATIBLE`, 11 exact template matches | same result |

## Not verified

- No live Desktop/app-server session on these builds loaded the updated Hook.
- `0.166.0-alpha.5` was compared at source level only; no binary was run.
- Native wait runtime facts and child-completion re-entry remain `UNKNOWN`, as
  before. CLI versions never establish them.
