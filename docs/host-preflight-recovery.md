# Windows launcher admission and independent Host maintenance

Python installation admission and the generated PowerShell guard share the
distlib interpreter-binding expression. Both short (`LF`) and long
(`LF CRLF`) layouts retain the exact absolute same-directory interpreter
requirement. A matching launcher hash does not override a bad binding, a
relocated runtime, an unlisted file or a changed runtime manifest.

Runtime setup and Host installation run the actual independent PowerShell
runtime verifier before returning a selectable runtime or changing the Host
generation. A parser incompatibility therefore leaves the previous installation
intact. Pending maintenance still uses the existing journal and original intent;
there is no separate recovery state machine.

If the installed runner or Hook cannot dispatch maintenance, use a separate
Python 3.11+ environment and reviewed adapter/Core checkouts, with explicit
human Host-maintenance authorization:

For the relevant procedure, use `controller-instructions --section host-maintenance`.
If the installed entry itself is broken, read the Host-maintenance section in the
reviewed checkout's `docs/thaliris-controller.md`, rendered from the canonical
`src/thaliris_codex/controller_instructions.md`, and this independent-entry guide.

```powershell
& '<independent-python>' -I -B '<adapter-checkout>/tools/thaliris_host_maintenance.py' --core-source-root '<reviewed-core-checkout>' --maintenance-contract '<absolute-contract.json>'
```

The UTF-8 contract is the normal `thaliris-host-maintenance-v1` contract. It
selects the actual human instruction, exact Host home/operation, original
installed identity and immutable executor/candidate identities and provenance.
The reviewed adapter source must match the selected executor. This entry verifies
both Python sources and packaged Markdown instruction resources against the
selected executor. `tests/test_independent_host_maintenance.py` exercises real
Windows PowerShell verification and console dispatch against a disposable home:
unknown broken controls are preserved; independently approved exact legacy bytes
can be removed with a contracted uninstall. This proves the independent path and
recoverable generation archive, not a live Host reinstall or catalog activation.
The entry verifies
the selected runtime independently and invokes only that exact executor's normal
maintenance operation, preserving ownership checks, evidence and recoverable
generation handling. It requires no installed Hook, runner or project admission.
It neither disables integration nor grants project authority. Unknown bytes stay
rejected; preserve them for review rather than approving them through a new hash.

## Project-loss catalog recovery at SessionStart

`codex-maintenance-plan codex-install` proposes `--root` as the
`catalog_recovery_project_root` by default. `--catalog-recovery-project-root`
selects another absolute project root; `--catalog-recovery-source-root` may add a
separately selected source root. These proposal fields authorize nothing until the
human-approved install contract includes them in its intent. On an actual native `SessionStart`, the Host
trampoline validates the installed manifest and runtime identity, then invokes the
pinned installed package before project dispatch; it does not import source from a
project checkout. Recovery proceeds only for a valid receipt policy and a normal
actor. Known children, readonly or fenced actors, malformed payloads, identity
conflicts and an unfinished Host transition do not authorize the catalog write.

If the selected marker is absent or no longer exact, recovery removes only the
receipt-owned `model_catalog_json` field after rechecking the current field and
catalog digest. It restores the previously absent configuration field and retains
the catalog file, reporting `backing_artifact_status: RETAINED_REFERENCE_SAFE`.
A selected missing source root has the same effect. A detected field edit reports
`USER_CHANGED_PRESERVED`; changed catalog bytes report `CATALOG_CHANGED_PRESERVED`.
Absent legacy policy, a pending transition, malformed payload, or a damaged or
unverifiable runtime or receipt yields an unknown or failed outcome without
deleting data. A pending transition must be replayed with its original maintenance
contract. When a project is still available, the catalog stays managed. The
original native Hook payload bytes and ordinary Hook result are forwarded
unchanged when a project marker is available for normal dispatch.

Recovery records restoration provenance only after removing the exact owned
field. An already-absent field without prior proof reports
`RECOVERY_PROVENANCE_UNKNOWN` and cannot authorize reinstall reclaim; an existing
completed proof permits one exact claim and successful reinstatement clears it.
The field writer compares bytes again before atomic replacement,
but a non-cooperating writer can still edit in the interval between the final
comparison and replacement, so preservation of a simultaneous unobserved edit is
not guaranteed. The human accepted this existing boundary: preserve changes
already observed by the byte recheck, retain the backing file, and disclose the
remaining writer interval. That decision is settled for this scope; it is not a
pending approval.

This is a check on the next Host SessionStart invocation; it is not immediate
project-deletion detection, a filesystem watcher, or a project restore operation.
Changing source files does not update an already running Codex process. Live Host
activation and session behavior remain unknown until observed after authorized
installation in a fresh native session. The
[model-catalog maintenance report](model-catalog-maintenance-report.md) describes
receipt migration, retained-file reclamation and compatibility outcomes.

Before recovery, preserve original installation/configuration and failure evidence
outside version control. After recovery, stop using the independent entry, run
the ordinary pinned bootstrap, and verify native role routing. Host catalog and
session activation remain UNKNOWN until observed in a fresh native session where
required. Disk registration is not activation, and successful preflight is not
task acceptance or human/Root authentication. Ordinary upgrades retain the normal
maintenance contract and need no extra emergency approval or permanent mode.
