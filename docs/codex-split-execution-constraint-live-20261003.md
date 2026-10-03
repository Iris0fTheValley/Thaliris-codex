# Split-package role execution smoke

On 2026-10-03, real OAuth Codex CLI `0.159.2` ran two disposable repositories
with separate Codex/user homes and a dedicated, non-editable runtime built
from the actual split Core and Codex adapter checkouts. Authentication was
copied securely without reading, printing or hashing its contents. All seven
hooks were installed and trusted through the official app-server.

Core candidate: `575652df9d1ebc45c6aa51609db67945e40e6c44` (0.4.3).
Adapter source candidate: `2a535206772f1c8b3107c1aaf59b4f5c7bdeb234` (0.4.3).
All six Core and twelve adapter Python source files matched the installed
wheel packages byte for byte. The Core wheel contains only `thaliris`; the
adapter wheel contains only `thaliris_codex`. The runtime manifest pins both.
Launcher SHA-256: `55c2f36067eaac1ee4bbf3301c3e5e367e5b2c7e43d2991cded41fb250532ee6`.

| Case | Controller | Focused Implementer | Reviewer | Closure |
| --- | --- | --- | --- | --- |
| C, explicit luna-only | gpt-6-luna / xhigh | gpt-6-luna / xhigh | gpt-6-luna / xhigh | DONE, revision 2 |
| D, default | gpt-6.1-sol / medium | gpt-6.1-sol / high | gpt-6.1-sol / high | DONE, revision 2 |

These models and efforts were checked against every selected native rollout
`turn_context`. All four children retained their existing semantic role and
native profile names, were exactly bound, and reached `STOP_ATTESTED` after
name-bound native completion observations. Both constrained children recorded
`execution_constraint_model_status: MATCH`. Default children carried no
constraint model status. Reviewer tool calls only read the marker. Each task
closed through the ordinary managed CLI with a genuine one-shot Hook proof.
No profile override, fake attestation or lifecycle edit was used.

The first C launch used an incorrectly abbreviated workspace path in its
task-start command and failed with Windows error 267. It created no task and
spawned no child. That process was stopped; a fresh session used the exact
initialized workspace and completed normally. The failed evidence remains
separate from the successful C2 observations.

Focused verification: 33 Core authority/neutral CLI tests and 107 adapter
constraint, authority, package-boundary, role, generated-document and lifecycle
tests passed. All eleven default generated profiles independently matched
immutable split baseline `158690bdc087fbe3ce5f4c61e4a356ddbac89e0e` byte for byte.
No full suite, benchmark or global runtime upgrade was performed.

The local frozen public evidence report SHA-256 is `d634d26e8bc96696ec5e6e5a9ddbee9c84cbb2538efe2b8ed52f9faed51a3cdd`.
This probe establishes the listed CLI sessions and split runtime only. Host
catalog loading, unobserved CLI overrides, other builds and Desktop behavior
remain UNKNOWN. The post-selection model check cannot prevent the first model
invocation; missing/mismatching models are covered by focused fail-closed tests.
The older [monolithic probe](codex-role-execution-constraint-live-20261003.md)
remains explicitly historical. The [port map](split-execution-constraint-port.md)
accounts for every surface of the original fix.
