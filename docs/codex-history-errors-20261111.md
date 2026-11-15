# Selected Codex history: command errors and recovery

This report reconciles a small set of historical workflow errors with the current
repository source. It covers only the selected sessions and turns listed below; it is
not an exhaustive history scan, a release verdict, or evidence of live Host activation.

## Findings and current recovery

| Historical case | Current evidence and supported recovery |
| --- | --- |
| Codex 0.5.2/0.5.3 PowerShell preflight hit the default `Restricted` execution policy. | The 0.5.5 preflight source runs the hash-checked bytes as a script block; [runtime recovery](thaliris-runtime-recovery.md#restricted-powershell-execution-policy) documents the fix and version boundary. This repository source does not establish that a Host has activated it. |
| `task-get` was called with the selected Task ID, producing `TASK_OBJECT_NOT_FOUND` with zero matches. | Core now explains that `task-get` requires an exact object ID when its argument equals the selected Task ID. CLI help states the distinction. Use `task-status` for the selected task, `task-show` for diagnostics, and retry with a current object's exact ID. A different missing ID retains the bounded not-found diagnostic. |
| A new evidence dispatch was refused because a selection or reservation was already pending. | Inspect the selected task's existing state before retrying. Only the owning Controller can cancel an unconsumed `next_dispatch` through `task-evidence-register` with `cancel_next_dispatch`. A pending authorized-spawn reservation follows its recorded native lifecycle; cancellation of an unconsumed selection does not clear that reservation. |
| `task-observe` lacked an exact handoff association. | Supply the exact selected `--handoff-id`. When the association is missing, return the observation and sources for Controller to register against the exact native-bound handoff. Do not use the Task ID as a handoff ID or infer an association. |
| `task-close --role` and `controller-instructions --section task-close` were attempted. | The CLI accepts `task-close --base-revision N`; the Hook supplies task and role binding. `completion` is the supported Controller guidance section for product/native completion and mechanical closure; `task-recovery` is available for recovery procedures. |
| Release watcher run `40635075737` exited with code 1 and truncated output. | The available record does not identify a cause or establish a workflow conclusion. Both remain UNKNOWN. |

## Evidence boundaries

The PowerShell recovery is verified in the current repository source at
`src/thaliris_codex/host_preflight.py` and described in
`docs/thaliris-runtime-recovery.md`. The pending-dispatch refusal is in
`src/thaliris_codex/codex_adapter.py`; supported Controller section names are in
`src/thaliris_codex/controller_instructions.py`; and the `task-close` parser is in
`src/thaliris_codex/cli.py`. The Core task-object recovery and CLI help are implemented
in the sibling `core/Thaliris` repository.

These checks establish source and documentation state only. They do not prove live
Host activation, identify the release watcher failure, or generalize beyond the
selected history.

## Selected historical sources

- Thread `thread01a17ff1-7fff-7271-be7f-1a39d9236b98`, turns
  `01a1808a-93d8-7fc3-b524-9bf4f63a655d` and
  `01a1808f-ff3f-77a3-9fe3-d6dbd01c347e`: earlier PowerShell preflight refusal and
  subsequent repository fix; live Host activation remains UNKNOWN.
- Thread `thread01a18540-5a8b-7b60-86f7-9105e43a57e0`, turn
  `01a1c88f-7976-7820-8e4a-19b34c088e17`: task ID used as a `task-get` object ID.
- Thread `thread01a191ba-342e-7693-a1d4-b1b0d33fffc7`, turn
  `01a191ba-37f9-75c2-aec2-69e917c53fef`: missing handoff association, invalid
  `task-close` role flag and guidance section, and truncated release-watcher output.
