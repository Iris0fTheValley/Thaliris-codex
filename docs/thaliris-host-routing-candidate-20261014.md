# Codex role-routing candidate, 2026-10-14

This record covers the ordinary-role model routing candidate built from the
Thaliris Codex 0.4.4 source on 2026-10-14. It prepares a reviewable candidate
and read-only Host plan; it does not authorize or perform formal Host
installation, upgrade, or removal.

## Source behavior

PreToolUse supplies model and effort defaults for exact registered ordinary
Thaliris roles after the applicable isolation, readonly, fence, task-control,
role, and execution-constraint guards. ACTIVE tasks retain their managed
freshness, owner, delegation, and authority checks before routing and reservation.
NO_TASK and inactive paths update native arguments only and create no task
reservation or lifecycle binding. Explicit non-empty selections and Native's
configured effort remain intact. Generic native roles and static Astra profiles
keep their prior behavior.

The profile check now matches the established Native handling of one invalid
`agents` configuration section: it skips that section and continues looking in
the layer's `agents/` directory and later layers. Missing targets, same-name
model conflicts, and unresolved working-directory evidence still refuse model
routing. Profile files and configuration bytes remain unchanged.

Hook root selection now honors a valid payload `cwd` directory when Git cannot
discover a repository there. A Git repository discovered from that directory
still selects its repository root; missing, invalid, or non-directory `cwd`
evidence retains the launch-root fallback. This keeps routing and existing
readonly, fence, isolation, and task-authority checks attached to a Gitless
payload workspace without creating reservations or task state.

Source SHA-256 values are `688e806c38588c5a33e8655aafad9309ebed865454c1320c6da66bca2863869f`
for `lifecycle.py` and
`7d820cdd3f12de47d0143f12c9f7eeceaca085e9501d7226329bf649a1ce36d7` for
`profile_compatibility.py`.

## Candidate and Host evidence

The final candidate wheel is version 0.4.4 with SHA-256
`33cf99897dae177bcb07bb4038d0ded09cdb70d6b61f1958cba18736a092f359`. All 23
Python modules in the wheel and installed runtime match the current source, and
the installed direct URL records that wheel digest. Normal `runtime_setup.create`
used the reviewed Core 0.4.4 wheel (`a7261b57a911de85ca5c5ca577645c6f984ce4d827a39e883562b32e3857cead`)
and produced candidate runtime digest
`8812f8219ce95f4b0eb2ecb3aa462ba90c09e9cb3eb1764e5c44aea8d1e39227`.
The setup console smoke and public `runtime-check` both passed. The exact
runtime manifest digest remained stable after `runtime-check`, with bytecode
disabled and no generated `.pyc` files.

The existing desktop baseline used Codex app 26.1007.2314.0 and the installed
0.4.4 adapter, which did not contain these defaults. Its ordinary Reviewer
default resolved to Sol/medium instead of the required Sol/high; an explicit
Luna/max selection was preserved. The candidate has not been activated in the
formal desktop Host.

The exact candidate was installed through the normal path into a separate
capability-probe `CODEX_HOME` with no prior installed manifest; Hook trust
reported `TRUSTED 7/7`. A fresh Native run then spawned a no-task Reviewer from
the Gitless payload workspace without a model or effort selection and with
`fork_turns: none`. The observed child `agent_role` was `thaliris-reviewer` and
its actual `turn_context` reported `gpt-6.1-sol/high`. A second spawn for the
same role with explicit `gpt-6-luna/max` retained Luna/max. Both child
completion markers were observed. The workspace remained without `.git`,
`.context`, `.codex`, `.agent-memory`, and `.milestones` before and after the
run. Native CLI events recorded WebSocket/TLS EOF retries before successful
fallback; the actual child contexts were still observed. No separate
Hook-specific diagnostic appeared in those Native calls, so that diagnostic
remains UNKNOWN.

An earlier isolated update attempt was refused because its prior runtime had
18 unmanifested `.pyc` files; it returned `changed: false` and `files: []`, and
that runtime was left unchanged. The accepted candidate verification used the
separate capability-probe home above. The desktop Host remains on its earlier
adapter, and the isolated candidate result does not establish desktop
activation.

## Verification and limits

The source suite passed with 617 passed and 1 xfailed; focused source tests
passed with 84 passed. The focused pre-admission route suite also passed against
the installed final wheel. Those tests cover NO_TASK and inactive defaults,
sparse and explicit selections, generic-role passthrough, Gitless payload cwd,
invalid-cwd fallback, readonly/fenced/isolation guards, active authority
preservation, and absence of new task-authority or reservation state. Wheel
module hashes matched source and installed bytes, and public `runtime-check`
reported `ok: true`.

No formal desktop Host write is evidenced by this work. The isolated candidate
Native run confirms the ordinary Reviewer default and explicit Luna/max
preservation; Hook-specific Native diagnostics and formal desktop activation
remain UNKNOWN.
