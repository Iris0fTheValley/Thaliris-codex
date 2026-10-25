# Runtime drift and administrative recovery

Thaliris follows Detect -> Diagnose -> Decide -> Repair/Accept -> Continue.
Runtime drift is evidence for a decision. Ordinary repository reads, source
edits, focused tests, investigation, and repairs remain available with managed
assurance UNKNOWN. An unexplained change denies only the affected dangerous
control operation. A legitimate upgrade can be selected at a new isolated
runtime path; the old manifest is archived, owned generated definitions are
updated, and user-owned collisions are preserved for an explicit decision.

Host maintenance uses [separate explicit intent and authorized byte ownership](thaliris-host-maintenance.md). Supported uninstall followed by normal immutable reinstall replaces the old-compatible-checkout recovery recipe; project admission is an independent control decision. Unknown role documentation is preserved as manual follow-up. No runtime renderer or manifest by itself supplies historical authorization.

`doctor` reports concrete paths and expected/actual hashes for runtime files,
Python bytecode, hooks, and profile definitions. A changed package or `.pyc`
file must not execute before platform validation. Python `-B` suppresses writes
but can still read caches, so caches remain executable inputs in the exact
manifest. An ordinary workspace source edit is outside that installed-runtime
boundary. CLI version, responding daemon version, topology, configuration,
authorization, running state, and health are separate observations. Same
executable path, inherited environment, PID, process ancestry, and SessionSource
do not prove daemon ownership or current Controller identity.
Installation rejects an existing manifest that is a nonfile, symlink, junction,
or has a linked ancestor before any installed-package import or executable
probe. Host installation ownership also cannot cross a linked home ancestor.

The Windows entrypoint pins a separate PowerShell preflight by hash and checks
the complete runtime before invoking Python. Its inline degraded policy is a
compressed generated literal so the physical command stays below cmd's 8191
character limit. The outer Host command uses a quoted PowerShell `-Command`
gzip loader for the same closed generated literal; ownership recognition
decodes it and requires exact regenerated command equality. It does not
evaluate hook input as code. A damaged runtime,
preflight, or trampoline emits a precise diagnostic and preserves ordinary
work. Managed state writes and unsafe authority grants remain denied.

## A running Host that still loads an earlier install

`codex-install` changes files on disk. A running Codex app-server keeps the
hook commands it loaded at startup, which is why a changing install reports
`install_status: RESTART_CODEX_ONCE`. Those loaded commands still pin the
earlier runtime manifest digest. If that digest fails against the current
`thaliris-install.json`, the on-disk preflight checks three things, on this
failure path only:

- the old pin is the runtime manifest of an archived committed generation in
  `thaliris-host-generations/`;
- the current manifest is the `after` manifest of a committed generation, and
  that generation's trampoline and preflight bytes match the files on disk;
- the current runtime passes the full runtime check.

If all three hold, the preflight reports `THALIRIS_RUNTIME_STALE_HOST_LOAD`:
the process still runs hook arguments of an earlier committed generation and the
installed generation is current. Otherwise it keeps `THALIRIS_RUNTIME_DRIFT`.
Both diagnoses apply the same degraded policy. Control stays denied, ordinary
work stays available and assurance stays UNKNOWN. Neither proves which identity
the Host loaded. There is no hot reload, so restart Codex (the app-server) once.
Task, authority and Controller association are kept on disk.

The diagnosis cannot reach every stale load. If the upgrade also replaced the
trampoline or preflight, the loaded command's own inline check fails first, and
its inline recovery code (from the earlier install) reports
`THALIRIS_RUNTIME_DRIFT: platform preflight unavailable`. The new check cannot
be added to that loaded command: the old code is embedded in it, and the
generated command already sits close to cmd's 8191-character line limit. Right
after an install that reported `RESTART_CODEX_ONCE`, treat this diagnosis the
same way and restart once. If it persists after the restart, it is real drift.
The upgrade from adapter 0.5.2 to 0.5.3 is such a case.

### Continuing the same Controller after the restart

- **Resumed thread.** The session association
  (`.context/audit/session-tasks/<session hash>.json`), the immutable lifecycle
  owner and the persistent task authority are files, and the restart does not
  touch them. A resumed thread that keeps its native session id needs no
  `task-associate`; re-read with `task-status` and continue. That Codex keeps
  the session id on resume is expected but has not been observed for every Host
  version.
- **New thread.** Associate it with `task-associate --expected-authority-sha256
  <hash>`. It is not the immutable owner, so it cannot create or consume a
  `next_dispatch` preselection. Use a readable `thaliris-evidence:` handoff
  marker instead. Managed spawns rely on the persistent task authority.
- **Controller session hash.** Do not pass `--controller-session-id-hash` by
  hand. The Hook supplies the current value, and a copied value from another
  thread is refused.
- **Children from before the restart.** Their ledger records stay. Whether
  their native threads survived is UNKNOWN. Observe them with `list_agents`,
  and do not reuse them with `followup_task`. Dispose any that you no longer need
  and that stay unresolved with `task-dispose-dependency`, then dispatch fresh
  children. A conflict that a refusal names is disposed with exactly the command
  that refusal prints.
- **Unconsumed preselection.** The owning Controller can withdraw a stale
  `next_dispatch` with `{"cancel_next_dispatch":{"reason":"..."}}` in
  `task-evidence-register`.

Codex 0.159.2's immutable source supplies `agent_id`/`agent_type` on native
ThreadSpawn PreToolUse/PostToolUse events. Its shared `session_id` is inherited
by descendants. Built-in Review delegates use another source variant and omit
agent fields while sharing that session. Thus absence of fields or a matching
owner session alone cannot authorize Controller control. Actor assurance
remains UNKNOWN. An explicit Controller selection of actual human task intent
can establish a persistent external anchor under the accepted governance
boundary; the Hook observes the operation, never human authorship. Definition
readiness is `READY` while actor assurance stays UNKNOWN; admission still requires
the selected human contract. Legacy `DEFINITION_READY_ACTOR_UNKNOWN` responses
carry the same separation. A bootstrap digest or single-use Hook bearer is not
required for explicit contract admission.
See [persistent task authority](thaliris-task-authority.md) for admission,
reconnect recovery, tampering protection and execution modes. Bound children retain their existing
identity, isolation, and readonly rules. The fixture
`codex-0159-actor-source-contract.json` describes upstream serialization, not a
live capture. See [the immutable runtime source](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/core/src/hook_runtime.rs)
and [the Review delegate source](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/core/src/tasks/review.rs).

With no ACTIVE managed task, ordinary fresh role delegation remains available
without creating a managed reservation, owner, or binding. Named Thaliris
spawns still require `fork_turns="none"`. The Controller's semantic routing
agreement remains in force; UNKNOWN mechanical admission does not appoint a
second Controller or let Root take over substantial executor work.
During platform drift, the fallback admits only a named fresh spawn from an
unlinked Git worktree with a safely absent task slot and no existing recovery
fence. A different payload working directory, any native child identity,
inherited context, model override, existing state (including unreadable or
inactive state), or session reuse is denied. These deliberately bounded disk
observations grant no Controller authority or managed child binding.

An informed user can delegate offline administration when an old task cannot
be recovered through the managed chain. Disconnect the global Thaliris hooks
and global startup block first. The separate reviewed repository source runner
`tools/thaliris_offline_recovery.py --core-source-root <reviewed-core-checkout>` accepts the exact task UUID, revision,
state SHA-256, lifecycle SHA-256 (or `ABSENT`), and an explicit reason, with
`--operator-asserted-user-delegation --integration-disconnected`. The Core
argument must name an explicit reviewed Core source checkout containing
`src/thaliris/core.py`; an installed Core package is not a reviewed checkout.
Use a trusted platform Python with `-I -B`; the runner compiles the repository's
`.py` files directly and never imports installed Thaliris or repository
bytecode caches.
It holds the repository lock, verifies the exact packet, archives original
state and lifecycle bytes verbatim (including the incomplete goal), fences
extractable session and agent identities even in partial or malformed ledgers,
verifies the archives/fences, and releases the old slot. It never completes the
old task or creates a new Controller, task, child binding, or readonly exemption.
The final release reobserves lifecycle bytes, including an `ABSENT` packet.
Any late appearance retains the task slot for a new exact archival/fencing
decision; evidence already archived during the failed attempt remains intact.

The authority mode is
`OPERATOR_ASSERTED_USER_DELEGATED_ADMINISTRATION`. Flags are operator assertions,
not cryptographic human consent. Disk disconnection is an operational condition,
not proof of what a running Host loaded. Shared unrestricted OS shell access
provides governance, not privilege separation. Every automated actor, including
an ambiguous Root, is denied this operation while integration is present; an
external human operator can disconnect integration first. The ledger records
old owner assurance, unbound identity, incompatible fields, identity extraction
completeness, and Host termination as UNKNOWN. Attempt native termination or
observation for known old children where available; missing death proof does
not permanently lock informed offline recovery. A damaged existing fence is
preserved and requires a separate informed repair.
