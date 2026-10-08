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

```powershell
& '<independent-python>' -I -B '<adapter-checkout>/tools/thaliris_host_maintenance.py' --core-source-root '<reviewed-core-checkout>' --maintenance-contract '<absolute-contract.json>'
```

The UTF-8 contract is the normal `thaliris-host-maintenance-v1` contract. It
selects the actual human instruction, exact Host home/operation, original
installed identity and immutable executor/candidate identities and provenance.
The reviewed adapter source must match the selected executor. This entry verifies
the selected runtime independently and invokes only that exact executor's normal
maintenance operation, preserving ownership checks, evidence and recoverable
generation handling. It requires no installed Hook, runner or project admission.
It neither disables integration nor grants project authority. Unknown bytes stay
rejected; preserve them for review rather than approving them through a new hash.

Before recovery, preserve original installation/configuration and failure evidence
outside version control. After recovery, stop using the independent entry, run
the ordinary pinned bootstrap, and verify native role routing. Host catalog and
session activation remain UNKNOWN until observed in a fresh native session where
required. Disk registration is not activation, and successful preflight is not
task acceptance or human/Root authentication. Ordinary upgrades retain the normal
maintenance contract and need no extra emergency approval or permanent mode.
