# Historical Codex admission fix

This archive preserves four original Git patches and a byte-verified source
snapshot from the final admission-fix commit. It is historical pending-proposal
evidence; it is not active source or the current compatibility/security
contract.

The historical implementation added SessionStart SHA-256 observations for
existing Thaliris role-profile files and denied task-start when the bytes under
an existing profile filename changed. In the current extracted Codex candidate,
a changed profile's content does not produce that historical denial; the
existing-profile-content regression remains UNKNOWN. The old guard and the
current result are intentionally recorded as different behavior. This archive
does not assert code or behavioral equivalence.

provenance.json records the original commit series, full Git blob IDs,
SHA-256 digests and byte lengths for every archived source/profile file, and
hashes for each raw format-patch file. The source snapshot includes the
adapter, lifecycle and role registry, the affected regression test, and the
profile files present in that historical commit.
