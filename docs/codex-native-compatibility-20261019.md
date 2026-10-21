# Native compatibility observations, 2026-10-19

The candidate accepts the exact official parent thread, turn, spawn call,
`subAgentActivity(kind=started)`, child UUID and returned agent path evidence
independently of CLI version. It still requires initialized home agreement,
exact Hook/reservation correlation, unique items across all pages, live parent
association and corroborating child Hooks. Version provenance alone cannot bind
a child. Missing, duplicate, stale, malformed or conflicting edges remain unbound.

Optional `model` and `reasoningEffort` fields record routing observations only.
Absent/null fields remain UNKNOWN for older Hosts; present malformed fields report
INVALID and differing selections report MISMATCH. These observations do not grant
or revoke authority, replace identity, or change existing execution constraints.

Wait capabilities are outside this native identity and Hook-dispatch acceptance.
This record does not establish effective duration, completion wake, message wake,
user interruption, automatic resume or production wait behavior. Those facts remain
UNKNOWN and are not changed or validated by this Native milestone.

`python -m scripts.verify_native_spawn_runtime` builds the candidate from source
wheels in an isolated runtime and runs the actual 0.163 CLI and app-server against
a loopback Responses mock. The candidate's Core wheel comes from the authoritative
sibling `core/Thaliris` source; the adapter wheel comes from this checkout. The
installed modules resolve only inside the disposable candidate venv (Core and
adapter are both 0.4.6).

The managed acceptance run observed 8 Host-discovered handlers from the workspace
cwd: all 7 candidate registrations plus one preserved user Hook, with no Host
warnings or errors. The app-server returned and trusted only the 7 exact candidate
handler keys through `hooks.state`; all 7 were enabled and dispatchable. A
pre-existing disabled user Hook state and other `config.toml` values survived the
trust write. The actual native run dispatched `UserPromptSubmit`, `PreToolUse`,
`PostToolUse` and `SubagentStart`. The resulting fresh child binding matched the
exact parent, turn, call, returned path and child UUID, and the selected ordinary
Focused profile's native spawn edge recorded `gpt-6.1-sol` / `high`. The profile's
instructions were present in the child provider request. Wrong-parent, stale-turn,
wrong-call and wrong-path probes were refused. The run made three local Responses
requests and zero external model requests. Unknown JSON bytes were verified in a
separate merge-only assertion; they are not injected into the Host fixture because
the 0.163 parser rejects unsupported top-level `hooks.json` fields. The managed
receipt is `tests/fixtures/codex-0163-alpha10-native-c1-managed-candidate.json`.

The earlier reader-only receipt, `tests/fixtures/codex-0163-alpha10-native-contract.json`,
remains a separate historical run and did not exercise managed Hook binding. The
official 0.163 app-server test requests `hooks/list` for the workspace cwd while
loading user hooks from `CODEX_HOME`; it also demonstrates the `hooks.state`
trust-hash write used by this isolated run. See the [v0.163 hook-list tests](https://github.com/openai/codex/blob/rust-v0.163.0-alpha.10.2/codex-rs/app-server/tests/suite/v2/hooks_list.rs).

Read-only process inspection found Desktop package 26.1013.4894.0 running an
app-server executable from binary revision `896a0166b774037a`. Running that exact
executable's version command reported `codex-cli 0.163.0-alpha.10.2`. A separate
read-only initialized connection corroborated its requested Codex home but exposed
no `serverInfo.version`; daemon version, control authority and live role catalog
remain UNKNOWN. This connection neither subscribed to nor resumed a Desktop child.

The pinned installed Thaliris runtime differs from the repository candidate: its
`codex_app_server.py` has no `native_spawn_identity`. Its existing managed child
binding therefore does not prove the candidate reader or candidate Hooks ran in
production. No Host installation, security-anchor change or production
configuration write was made. Signed-in Desktop Hook activation and effective
production runtime behavior remain UNKNOWN.

The selected upstream comparison reports unchanged role discovery, loading,
configuration and role application between `rust-v0.162.0-alpha.17.2` and
`rust-v0.163.0-alpha.10.2`. Existing config ownership, transaction and recovery
paths stay authoritative; a new version string alone is no reason to change them.

The supplied simple session parsed without JSONL errors. Its `turn_context` and
`world_state` record types and `response_item` subtype `additional_tools` are now
counted as known by the offline auditor; their contents supply no child identity,
authorization or completion evidence and remain absent from reports. Unknown
future types still use the privacy-preserving unknown/unclassified buckets.

Official field definitions: [0.163 activity items](https://github.com/openai/codex/blob/rust-v0.163.0-alpha.10.2/codex-rs/app-server-protocol/src/protocol/v2/item.rs#L395-L406),
[additional tools](https://github.com/openai/codex/blob/rust-v0.163.0-alpha.10.2/codex-rs/protocol/src/models.rs#L1025-L1035),
[turn context](https://github.com/openai/codex/blob/rust-v0.163.0-alpha.10.2/codex-rs/protocol/src/protocol.rs#L3412-L3457).

## 2026-10-21 release and real-Luna status

The official [Codex release list](https://github.com/openai/codex/releases) showed
0.163.0 as the latest stable release and 0.164.0-alpha.9 as the newest
pre-release on this date. The local CLI reports `codex-cli 0.163.0-alpha.11`;
the selected Desktop package is 26.1016.6573.0. In the relevant Hook engine
surface, stable 0.163.0 lists `SubagentStart` and `SubagentStop`, while
0.164.0-alpha.9 adds `PreModelRequest` and `PostModelRequest` ([0.163 Hook
engine](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/hooks/src/engine/mod.rs),
[0.164 alpha.9 Hook engine](https://github.com/openai/codex/blob/rust-v0.164.0-alpha.9/codex-rs/hooks/src/engine/mod.rs)). The candidate ignores
unknown events, so those model-request observations do not alter its child
identity or lifecycle state.

The alpha.11 candidate Hook mechanics receipt is
`tests/fixtures/codex-0163-alpha11-native-luna-mechanics.json`. It records seven
trusted and dispatchable candidate handlers, an exact native child edge and
`gpt-6-luna` / `max` routing in the isolated app-server. Its provider was a
loopback synthetic Responses server: the receipt records three local requests
and zero external model requests. It proves Hook dispatch and routing mechanics,
not Luna reasoning or child completion.

The isolated real-Luna probe used the app-server's documented
`account/login/start` schema with `type: chatgptAuthTokens`, the existing
access token and account ID in memory, and no refresh token. The app-server
accepted it, made no refresh request, wrote no isolated `auth.json`, and left
the source auth file unchanged. The earlier `login --with-access-token`
rejection was the wrong endpoint for ChatGPT OAuth credentials; it did not show
that no safe local authentication path existed.

One real parent turn and one fresh `thaliris-investigator` child turn ran on
`gpt-6-luna` / `max`. The native spawn edge identified one child, and the
parent invoked native wait once. That wait returned a message with
`timed_out: false`; the message itself did not establish terminal status. The
isolated app-server then reported `turn/completed` for both exact parent and
child turns, followed by one exact child `thread/read` reconciliation whose
selected turn was `completed` (the post-restart thread status was `notLoaded`).
The app-server did not expose exact provider HTTP request counts or token usage.

This real run did not produce a candidate `SubagentStart` runtime record or an
exact candidate child lifecycle binding. The cause remains UNKNOWN: the stored
evidence cannot distinguish an event not generated, not dispatched, or a real
Hook command that did not reach the candidate. Do not infer Start or managed
binding from child completion. Error/exception recovery behavior was not
exercised. Separately, the zero-external-request V2 loopback probe recorded a
sanitized `SubagentStart` trampoline entry and adapter exit code 0, and the
same synthetic run bound its exact native child. This shows the isolated
candidate path can work on the tested alpha.11 app-server; it does not explain
the real run's missing Start evidence. The loopback receipt remains separate
at `tests/fixtures/codex-0163-alpha11-native-luna-mechanics.json`; the real
probe/auth receipt is `tests/fixtures/codex-0163-alpha11-native-luna-auth.json`.

The follow-up review also found a bounded relative-workdir routing defect:
the second Hook pass could append a relative `workdir` to the already selected
repository. Relative CLI roots now resolve against the unchanged payload `cwd`;
the repository-association regression covers both passes with a real selected
association. This changes navigation consistency only and adds no authority.

No production Hook or runtime installation was performed. Production Host
activation, production child lifecycle binding, effective native wait behavior
and exception recovery remain UNKNOWN.
