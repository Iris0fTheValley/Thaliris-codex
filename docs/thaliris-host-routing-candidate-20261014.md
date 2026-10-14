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

Source SHA-256 values are `0a6d98e9c8e66235f8845e27759799c3e42b4657b232ce9b3ad594a34ce42f02`
for `lifecycle.py` and
`7d820cdd3f12de47d0143f12c9f7eeceaca085e9501d7226329bf649a1ce36d7` for
`profile_compatibility.py`.

## Candidate and Host evidence

The candidate wheel is version 0.4.4 with SHA-256
`136aad11fa7b7109166da55e522163a255970d579a7e43e29085f446ee3772a9`. Its two
changed modules match the source hashes above, and the isolated runtime records
that wheel digest as its direct installation provenance. The standard runtime
setup and public `runtime-check` passed. A read-only `codex-maintenance-plan`
also passed with `ownership_approved: false` and no project files touched. Its
review-only contract states that formal Host installation, upgrade, and removal
are not authorized.

The existing desktop baseline used Codex app 26.1007.2314.0 and the installed
0.4.4 adapter, which did not contain these defaults. Its ordinary Reviewer
default resolved to Sol/medium instead of the required Sol/high; an explicit
Luna/max selection was preserved. The candidate has not been activated in the
formal Host. Candidate `runtime-check` is PASS; actual candidate Native
`turn_context`, `agent_role`, and Hook diagnostics remain UNKNOWN because the
available child-spawn interface does not select the prepared Gitless workspace
and its temporary `CODEX_HOME`. No substitute run was used.

The exact candidate Native probe is still needed before claiming that a fresh
default Reviewer receives Sol/high and an explicit Luna/max Reviewer receives
Luna/max. The current desktop baseline does not establish candidate behavior.

## Verification and limits

The full source suite passed: 1,404 passed, 10 skipped, and 1 xfailed. Focused
tests against the installed candidate wheel passed: 173 passed and 3 skipped.
The suite includes pre-admission defaults for NO_TASK and inactive state,
sparse and explicit selections, generic-role passthrough, Gitless public Hook
routing, readonly/fenced precedence, and absence of new task-authority or
reservation state.

No formal Host write was attempted. The previous temporary authentication
staging cleanup remains blocked by environment policy; its contents were not
read or hashed, and no cleanup workaround was attempted. This staging is not
part of the repository.
