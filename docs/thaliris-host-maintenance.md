# Host maintenance and project admission

Host maintenance has its own explicit intent. It does not borrow a project's
task authority, initialize a project, approve its unknown AGENTS control block,
change a task boundary, or unfence an actor. An arbitrary workspace is sufficient.
Known children, readonly actors and fenced sessions remain denied. An actor with
missing native identity remains UNKNOWN; the intent is shared-OS governance,
not mechanical authentication of a human or positive Controller proof.

Use the [normal packaged runtime setup](../README.en.md) to install both reviewed
packages in a new dedicated Python 3.11+ environment. The installer creates it
without ensurepip and uses the separate bootstrap's pip; setuptools and build
tools never enter the runtime. System site packages stay disabled and no
executable/path-extending `.pth` files are accepted.
Use full immutable Git commit refs or verified artifact SHA-256 pins. Do not
upgrade packages in the already pinned runtime directory. The current installed
runtime and the approved candidate are separate identities. The approved
candidate package must execute installation and render its own generation. The
caller must execute the selected installed package, not development source via
PYTHONPATH.

The bootstrap environment may contain Python 3.11's normal setuptools `.pth`;
it is outside the pinned runtime and is never copied into it. No manual package
removal or `.pth` editing is part of normal installation. If setup fails after
the redirect check, keep the candidate as evidence and choose a new directory
after correcting the reported input. A redirected empty leaf created by that
attempt is removed; preexisting and nonempty directories are preserved.

Runtime location is a lifecycle identity invariant. With no `--runtime` override,
setup discovers the current Codex Host's package family, resolves its existing
LocalCache with `GetFinalPathNameByHandleW`, and creates a new uniquely named
candidate beneath that physical base. A bootstrap launched outside Codex queries
only the exact `OpenAI.Codex` package registration and rejects missing or
ambiguous results. No Store internal path is part of the normal install steps.
An explicit `--runtime` remains supported and is checked for final physical identity.
Create the venv directly at that final directory before installing either package;
a redirected explicit path is rejected before venv/package creation.
Do not copy, move or rename an installed venv. Its pinned location anchor and
pip launcher's absolute interpreter binding must agree with the final directory.
Rehashing or rebasing a relocated candidate cannot make it valid, including when
the original interpreter survives and the copied launcher can still execute.

Setup invokes the normal public `thaliris.exe runtime-check` from the final path
and checks its actual interpreter, prefix and package origin. Selection repeats
this side-effect-free smoke after byte/isolation/provenance checks and before
maintenance contract generation or Host mutation. Child environments set
`PYTHONDONTWRITEBYTECODE=1`; retain that setting in the shell used for planning and
maintenance. Preparation, executor/candidate selection and installation use the
same final directory. Old owned manifests remain readable for diagnosis and
ownership; a newly selected executor/candidate must have the setup location
anchor and support `runtime-check`. Prior-generation verification preserves the
original safety and exact-file checks without inventing new runnable/location
assurance or withdrawing its independent receipt ownership.
Preserve an invalid relocated candidate and recreate in a fresh final directory,
without patching its launcher or substituting `python -m` for the public entry.

`codex-maintenance-plan` is read-only. It reports the exact candidate runtime
identity and an intent object from the supplied actual human instruction. Its
ownership snapshot is inspection evidence only: it never approves existing files.
For example, in PowerShell, after installing the immutable candidate wheels:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$exe = $runtime.executable # returned by the packaged runtime setup
$plan = (& $exe codex-maintenance-plan codex-install --executable $exe --source-pin 'git+https://github.com/Iris0fTheValley/Thaliris-codex.git@<reviewed-full-40-character-commit>' --human-instruction 'Install the reviewed Thaliris Host integration requested by the user.' | ConvertFrom-Json)
[IO.File]::WriteAllText((Join-Path (Get-Location) 'host-install-intent.json'), ($plan.maintenance_contract | ConvertTo-Json -Depth 16), [Text.UTF8Encoding]::new($false))
& $exe codex-install --maintenance-contract (Resolve-Path .\host-install-intent.json)
```

The full commit placeholder must be replaced with the independently reviewed
published revision. For an artifact, use `sha256:<verified-wheel-SHA-256>`.
The contract binds `operation`, `codex_home`, `human_instruction`, the `executor`
and `candidate` executable/runtime/source identities, the exact current
`installed_runtime_sha256` (or `ABSENT`), and `execution_constraint` when selected.
Use the same `--execution-constraint luna-only` in planning and installation for
that dedicated installation. This Host contract does not replace a task's
separate execution-constraint declaration.

All candidate launcher/package/runtime identity, isolation, safe path, import
origin, ABI probe, existing runtime drift, ownership and control conflict checks
complete before any profile, instruction, trampoline, manifest or trust mutation.
An incomplete native hook trust update is reported separately from installed disk
definitions. Installing writes `thaliris-ownership.json`, bound to the exact
runtime manifest and the authorized maintenance contract. It records exact
profile/script bytes, the global instruction span and generated hook entries.
Later candidates can replace these authorized bytes without embedding the next
generation's outputs in an old historical hash table.

The upgrade surface includes candidate profiles and profiles recorded by the
prior authorized receipt. A retired profile is deleted only when its exact old
bytes still match that receipt. An edited retired profile blocks upgrade before
writes; uninstall preserves edited profiles. Unrelated profiles are preserved.

### Native multi-agent mode hint compatibility

This narrow compatibility edit uses the source-verified Codex CLI builds
`0.162.0-alpha.17.2`, `0.162.0-alpha.2`, `0.162.0`, and `0.162.1` as an exact
fast path, rather than treating a version family as sufficient evidence. Other
CLI builds with a successful version response undergo an isolated capability
check: a disposable `CODEX_HOME` and workspace configure the candidate field,
execute finite synthetic tasks against a loopback Responses sink, verify its developer
prompt effect, and confirm that the field rejects an integer. It does not copy
current-user configuration or authentication. On Windows it resolves ProgramData
with `SHGetKnownFolderPath(FOLDERID_ProgramData)` and checks
`OpenAI/Codex/config.toml` and `requirements.toml`; on Linux it checks
`/etc/codex/config.toml`, `requirements.toml`, and `managed_config.toml`. Existing
paths or any lookup/stat failure return `VERSION_SUPPORT_UNKNOWN` without running
`exec`. macOS managed preferences cannot be proven absent here and therefore also
remain `VERSION_SUPPORT_UNKNOWN`. When the local system layers are proven absent,
the probe passes `--disable hooks --disable plugins`; those flags do not disable
managed hooks on their own, which is why the system-layer preflight runs first. A contradictory captured
effect reports `CAPABILITY_INCOMPATIBLE`; incomplete or ambiguous evidence reports
`VERSION_SUPPORT_UNKNOWN`, and neither status authorizes a write. The alpha
`0.162.0-alpha.17.2` and stable `0.162.0`/`0.162.1` sources agree that the schema declares the field as a string,
the native mode resolver recognizes `Some("")`, and the instruction renderer
returns no text for an empty custom value. The alpha revision's native regression
covers this behavior:
[schema](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/config.schema.json#L2927),
[mode resolver](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/session/multi_agents.rs#L77),
[instruction renderer](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/context/multi_agent_mode_instructions.rs#L14), and
[native regression](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/app-server/tests/suite/multi_agent_mode.rs#L387). The stable source paths are also recorded at
[0.162.0 schema](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/core/config.schema.json),
[mode resolver](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/core/src/session/multi_agents.rs),
[instruction renderer](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/core/src/context/multi_agent_mode_instructions.rs),
[0.162.1 schema](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/core/config.schema.json),
[mode resolver](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/core/src/session/multi_agents.rs), and
[instruction renderer](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/core/src/context/multi_agent_mode_instructions.rs).
For `0.162.0-alpha.2`, the source witness is upstream tag
`rust-v0.162.0-alpha.2`, peeled commit
`74e804deeb1241d5fe699b31fb319f7d46454c42`. It writes the empty string to
`features.multi_agent_v2.multi_agent_mode_hint_text` only when that user-level
leaf is absent. At this CLI revision, the empty value suppresses the native
default explicit-request-only mode hint. A contradictory or indeterminate
capability check, an existing empty or custom value, or unsupported TOML
structure is preserved. An existing
`features.multi_agent_v2.enabled` value is retained.

Safe insertion supports ordinary `[features.multi_agent_v2]` and
`[features]`/root dotted boolean forms. Inline, quoted, special, or alternate
legal layouts (including whitespace variants such as
`[ features . multi_agent_v2 ]`) are conservatively reported as
`STRUCTURE_UNSUPPORTED_PRESERVED`. If a migrated table later gains user
structure, uninstall removes only the owned hint and preserves the current
`enabled` value and surrounding content.

For a first install or upgrade, use the existing immutable-candidate flow:
create the normal `codex-maintenance-plan codex-install` intent, then run
`codex-install --maintenance-contract FILE` with that exact approved contract
and candidate, bound to the exact current installed-runtime identity as described
above. No separate config editor or broader config ownership is added.
The result reports `native_mode_hint_compatibility`; a completed managed value
is `MANAGED` (an already managed value can report `changed: false`). Before
relying on it, inspect the user `config.toml` leaf and the matching
`native_mode_hint` record in `thaliris-ownership.json`: the record binds the
absolute config path, `prior.present: false`, and the exact owned fragment.
The whole config file is not added to `owned_bytes` or to generation rollback
ownership. `thaliris-host-transition.json` must be absent after completion. If
it remains, do not start a new maintenance operation; replay the original
operation with its same contract and approved executor. During an interrupted
install, the journal's `finish` record carries the field record, planned status,
and write phase/result. If the outcome after an interruption is uncertain, the
field is preserved with `APPLY_OUTCOME_UNKNOWN_PRESERVED` rather than reinserted.
The field writer rereads bytes immediately before atomic replacement, but this
does not provide compare-and-swap protection against an external editor racing
that final check.

For these four source-verified 0.162 CLI builds, or another build that passes the
isolated capability check, the existing install/upgrade path can add a concise,
role-neutral root-level `developer_instructions` value when that user-config
field is absent. It asks agents to continue necessary independent work, prefer
meaningful notifications over repeated polling, preserve UNKNOWN when completion
is unproved, and follow their role and selected handoff. An existing empty or
custom user value is preserved.

The result reports `controller_wait_guidance_compatibility`, and the ownership
receipt stores a separate `controller_wait_guidance` field record. On upgrade,
the field is migrated only when its complete TOML fragment exactly matches a
fragment in the trusted prior receipt. The next receipt stores the current
fragment and exact previous managed fragments, so recovery and uninstall retain
ownership evidence without comparing old text with today's guidance. A changed
value, malformed history, or unconfirmed ownership is preserved or rejected
before the optional field write. During migration, the Host transition journal
records the prior receipt and write phase before atomically replacing the field.
Recovery recognizes an exact completed replacement; an uncertain outcome is
reported as `APPLY_OUTCOME_UNKNOWN_PRESERVED` and is not silently retried in
that recovery pass. A later explicit install may plan a new migration if the
old exact fragment remains. Repeating a completed upgrade does not rewrite the
config field. Uninstall removes only an exact current or receipt-recorded prior
fragment; user edits remain. The whole config file stays outside `owned_bytes`
and Host generation rollback. The writer rereads bytes before atomic replace,
which still cannot prevent an editor racing that final check. Source or fixture
tests do not prove a fresh Host session loaded the setting or that a model
follows its guidance.

### Fresh Child instruction provenance

At the same pinned Codex `0.162.0-alpha.17.2` source revision, V2 child setup copies the
parent turn's developer instructions when no child override is supplied, and
the selected role may contribute its own developer instructions. The upstream
app-server regression covers inheritance with no override:
[child setup](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/agent/child_config.rs#L131),
[role instructions](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/agent/role.rs#L182), and
[V2 inheritance test](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/app-server/tests/suite/v2/multi_agent_v2_developer_instructions.rs#L472).
This establishes the instruction propagation path; it does not prove that a
running Host loaded a profile or that an agent follows it. Thaliris keeps the
selected handoff in the spawn message and renders role-owned child instructions
separately from the resident Controller program.

For removal, use the existing `codex-maintenance-plan codex-uninstall` and
`codex-uninstall --maintenance-contract FILE` path. Uninstall removes only a
still-matching owned leaf and restores a migrated `enabled` boolean when the
original TOML fragment is intact; user edits and later structure changes are
preserved and reported. The install and uninstall contracts retain the normal
trusted runtime, candidate, executor, installed-runtime and explicit-human-
intent requirements described above.

Disk evidence does not prove effective Host behavior. Restart Codex and use a
new Host session, then observe that this default hint is absent. Exercise a real
Fresh Child using V2 `fork_turns="none"` or V1 `fork_context=false` and verify
its selected handoff while the existing admission, role, isolation and security
behavior remains intact. Higher-priority project configuration or CLI `-c`
values may override the user-level setting; report that effective state as
unknown until observed. Tests and installed files alone do not establish this
acceptance.

Disk definitions change as one recoverable generation. Before the first managed
write, `thaliris-host-transition.json` durably records exact before/after bytes
and the original maintenance contract identity. The receipt is written last;
the journal then commits only after all effective disk bytes match the planned
generation. Native trust registration/removal is an idempotent post-commit step,
so the previous trusted generation remains recoverable before disk commit.
While a journal exists, normal runner/bootstrap admission is blocked and loaded
catalog/activation remains UNKNOWN. The native preflight admits a direct replay
by the original approved executor with the **same original maintenance contract
file** after interruption. It checks that immutable executor before importing
its policy, forwards the original native actor payload, and preserves child,
readonly, fenced and abandoned-actor denials. Literal recovery policy in the
loaded hook also handles entrypoints removed during uninstall; unknown bytes
and unverifiable receipts remain denied. A journal is never a maintenance grant
and an absent actor field never proves Root. PREPARED
transitions mechanically restore the previous generation and replan; COMMITTED
transitions finish native trust and archive exact generations. No partial
generation is accepted as new ownership. Edited bytes, changed runtime identity,
unsafe paths or a different contract stop recovery and preserve evidence.
Native replay requires the original approved executor's replay-check entrypoint
and a loaded hook containing this literal policy. An earlier executor or already
loaded hook without that capability cannot be replaced implicitly through an
unfinished journal; its recovery boundary needs a separate Controller decision.
The operating-system lock releases on process exit, and a later invocation can
continue without deleting a stale lock or blessing arbitrary hashes. Native
trust failure reports incomplete installation explicitly; it does not roll back
user configuration. Trust modifies only the Host-returned exact handler keys.

Candidate renderer equality, HEAD, matching markers, a reproducible old renderer
or a runtime manifest alone establish no prior authorization or byte ownership.
Legacy installations lacking a receipt need specific human approval of the exact
reviewed `legacy_owned_bytes` hashes (the global span uses `AGENTS.md#global`).
Select only content affirmatively owned by Thaliris; do not copy the whole plan's
snapshot as an automatic approval. Unknown control bytes are preserved and the
affected operation stops before writes. Historical fixtures remain independent
witnesses, not a place to add the next candidate's bytes to an old release.

For an explicitly requested global instruction migration, the same
`codex-install --maintenance-contract FILE` accepts an optional
`instruction_migrations` array. Each entry selects an existing absolute
`path` to either the selected Codex home's `AGENTS.md` or the current user's
home `AGENTS.md`, the complete `before_sha256` and reviewed candidate
`after_sha256`, and `remove_spans`. Each span has exact byte `offset`, `length`,
`sha256`, and `kind`. The only supported kinds are `durable-section` (the
complete `## Durable Thaliris synchronization` section in Codex home) and
`global-block` (the complete marked redundant Thaliris global block in user
home). Exact human selection approves only those obsolete fragments; it does
not establish ownership of the surrounding file. Existing Codex-home marked
block ownership must still pass the normal receipt or legacy approval checks.

The approved candidate renders the canonical Codex-home entry with that home's
pinned runner, removes the selected obsolete spans, and preserves every other
byte. The result must match the explicitly selected complete after hash.
Omitting this array preserves all existing unmarked tail bytes. The planner's
ordinary ownership snapshot never opts into migration. All selected files and
candidate hashes pass preflight before writes; they participate in the same
recoverable generation, original-contract replay and drift refusal as other
Host files. The receipt owns only the canonical marked entry, and the archived
generation retains exact migrated before/after bytes. A fully redundant user-home
file becomes an empty file; no second Host integration is installed there.

For normal cleanup, plan `codex-uninstall` with the approved maintenance executor,
save its intent object, and run `codex-uninstall --maintenance-contract FILE`.
The operation preserves user configuration, other hook trust keys, user profiles,
project source/documentation and recovery evidence. Prior manifest and ownership
provenance are archived. A self-invoked Windows runner stays inert with a narrow
ownership receipt; a normal reinstall handles it without manual deletion.
Then prepare a new install contract with `installed_runtime_sha256: ABSENT` and
run the ordinary installation command. No old checkout, project pre-init,
historical local hash update or temporary development runtime is required.

An already loaded older Hook cannot acquire this new protocol from changed disk
source. If it rejects supported maintenance, a human can invoke the approved
standalone maintenance CLI in a terminal using the exact intent and legacy byte
approval. This retains runtime/ownership validation; it does not authorize an
automated child to bypass the old Hook or manually delete guards. Restart Codex
as required and re-observe the loaded integration afterward.

### Host-wide model-catalog preservation and recovery

The Host-global `model_catalog_json` field is receipt-owned alongside its backing
catalog. A catalog-required receipt uses the v2 format and declares its catalog
capability, so an older reader fails closed instead of ignoring the field. The
current reader accepts a valid legacy v1 receipt and an authorized install or
upgrade migrates it. A v2 receipt causes an older reader's install or uninstall to
stop before mutation; for a downgrade, first uninstall with the current reader,
then install the older reader. The committed archive preserves exact catalog
ownership so a later current-reader upgrade can reclaim it if the field is absent
and the bytes still match. Catalog compatibility and online-source failures are checked
before the Host generation is written. A user-edited catalog can be reported as
`USER_CHANGED_PRESERVED` while other authorized Host changes proceed, but
`catalog_goal_met` stays false and manual follow-up is required.

`codex-maintenance-plan codex-install` proposes the `--root` location as
`catalog_recovery_project_root` by default. `--catalog-recovery-project-root`
selects another absolute project path, and `--catalog-recovery-source-root` can
select an additional source path. These are proposed contract fields; only the
human-authorized contract stores the recovery policy in the receipt. On the next
actual `SessionStart`, the verified pinned runtime checks those selected locations
before project dispatch. If the selected
activation marker or source is gone, it restores only the exact managed
`model_catalog_json` field to its recorded absent state when both field ownership
and catalog digest still match. The physical catalog remains on disk. A legacy
receipt without recovery policy, changed user bytes, unknown ownership, malformed
payload, unfinished transition, or runtime failure does not trigger cleanup;
recovery remains unknown or failed and preserves the evidence. A detected field
edit reports `USER_CHANGED_PRESERVED`; changed backing bytes report
`CATALOG_CHANGED_PRESERVED`. If the field is already absent and the receipt has no
completed-restoration proof, recovery reports `RECOVERY_PROVENANCE_UNKNOWN`; absence
alone cannot authorize later reclaim. No project checkout is downloaded or recreated.

Uninstall removes the owned field but keeps the catalog file and archives the
committed generation. A later upgrade may reclaim that file only from an exact
committed archive or once from a receipt proving a completed project-loss
restoration, with the field absent and the catalog digest unchanged. Recovery
records its `restored` proof only when it removes the exact owned field; an already
absent field without prior proof reports `RECOVERY_PROVENANCE_UNKNOWN` and cannot
authorize reclaim. Successful reinstatement clears the restoration marker. Missing configuration is not evidence
that the backing file may be deleted. The field writer rechecks before atomic
replacement, but a non-cooperating writer can still race after that comparison;
simultaneous unobserved edits are not guaranteed safe. See the
[model-catalog maintenance report](model-catalog-maintenance-report.md) for the
recorded states and compatibility rules. The accepted boundary is observed-user
change preservation plus retaining the backing file; the remaining concurrent
writer interval is documented and is not treated as a pending decision.

After installation, run the installed `thaliris-run.cmd --root <repo>
codex-bootstrap`. Unknown role documents/README/generated documentation are
preserved with `preserved_manual_followup`; they do not alone block admission.
Unknown AGENTS authority, activation, hook or other control contracts still block
admission and need a separate exact project decision. Bootstrap/task admission,
native role availability, native loaded instructions and managed scheduling
readiness remain separate observations. Disk profile equality and 7/7 trusted
enabled Host handlers do not prove native catalog or current-session activation.

## 中文说明

Host 安装、升级、卸载使用独立的维护意图文件，绑定真实用户要求、准确操作、
Codex home、已批准的不可变执行器和候选运行时身份，以及当前安装身份。
不要求项目先初始化或启动任务，也不替项目批准未知的 AGENTS 控制内容。
已知子角色、只读角色和被 fence 的身份仍被拒绝；缺少身份的 actor 仍为 UNKNOWN。
这是共享操作系统上的治理声明，不是人类认证或 Controller 身份证明。

先按 [README 正常安装](../README.md) 使用包内 runtime installer：创建不含
ensurepip 的专用环境，通过独立 bootstrap 的 pip 安装已选择的包，pip、setuptools
及构建工具留在 runtime 之外；无需手工删除包或修改 `.pth`，隔离检查仍无例外。
省略 `--runtime` 时，setup 会发现当前 Codex Host 的 package family，通过
`GetFinalPathNameByHandleW` 解析已有 LocalCache 的物理路径，并在该 base 下创建
新的唯一候选目录。外部启动的 bootstrap 只查询准确的 `OpenAI.Codex` package，
缺失或不唯一时会 fail closed。正常流程无需填写 Store LocalCache 内部路径；
确需自定义位置时可传 `--runtime PATH`，显式路径仍须通过最终物理身份检查。
显式路径发生重定向时，在创建 venv 或安装包前报告物理路径，并且只清理由本次
尝试创建的空 leaf；预先存在或非空目录保持原样。位置 anchor 与 pip launcher 的
绝对 interpreter binding 必须一致，禁止复制、移动或重命名已安装 venv；重算
manifest 不能批准 relocation，旧 interpreter 仍存在且复制后的 console 能启动时
也必须拒绝。通过重定向检查后出现失败时保留候选，另选最终目录重新创建。
setup 和维护选择使用普通最终路径 `thaliris.exe runtime-check` 验证实际 interpreter、
prefix 与 package origin，并在生成维护 contract 前通过。子进程设置
`PYTHONDONTWRITEBYTECODE=1`，执行 plan/维护的 shell 也须保留此设置。
准备、contract 的 executor/candidate 与最终安装绑定同一目录；旧授权 manifest
仍可用于诊断与 ownership，新选择的 executor/candidate 必须有 setup 位置 anchor
并支持 `runtime-check`。旧 generation 保留原有安全与准确文件校验，不赋予新的
位置或 runnable assurance，也不撤销其独立 receipt 所证明的 ownership。
再用 `codex-maintenance-plan` 检查
身份并生成维护意图。源码必须指定完整不可变 commit，或已校验 artifact SHA-256。
plan 的现有文件 hash 只是审阅材料，不自动批准 ownership。安装前先完成全部
运行时、隔离、路径、ABI、旧安装 drift、ownership 与控制冲突检查，之后才写入。
新安装记录绑定原始授权和准确 bytes，未来升级不依赖旧版本预先知道新输出。
候选 renderer、HEAD、marker、旧 renderer 可复现和 manifest 都不能证明原始授权。

升级处理 candidate profiles 与旧授权 receipt-owned profiles 的并集。N+1 删除的
角色仅在旧 bytes 精确匹配 receipt 时删除；已编辑的 retired profile 在写入前阻止
升级，卸载则保留。无关 profiles 保留。首次写入前持久记录准确前后 generations
及原始维护意图身份；receipt 最后写入，全部磁盘内容校验后才 commit，然后处理
原生 trust。journal 存在期间正常 runner/bootstrap admission 被阻止。
中断后用已批准的独立 executor 重放同一个原始维护 contract 文件：PREPARED
先机械回滚再重新规划，COMMITTED 继续 trust 并归档 generations。无需旧 checkout、
手工删锁或随意批准 hash；进程退出会释放 OS lock。输入 drift、未知 bytes 或不同
contract 保留证据并停止。trust 未完成会明确报告，用户配置不作为回滚目标。

旧安装没有授权 ownership receipt 时，需要用户针对确切的 Thaliris bytes 作出
具体批准；不明文件逐字节保留。正常恢复使用受支持的卸载，再正常安装，保留用户
配置、其他 hooks/trust、用户 profiles、项目文件和恢复证据。Windows 自调用 runner
可以保留为 inert，并由下一次正常安装接管；无需手工删 guard、改保护状态或依赖旧 checkout。
已加载的旧 Hook 不会因磁盘源码更新而获得新协议。若它阻止正常维护，实际用户可在
终端调用已批准的独立 CLI，仍须通过准确维护意图和 legacy bytes 批准及全部验证；
这不赋予自动 actor 绕过旧 Hook 的权限。之后按要求重启并重新观察加载结果。

### 原生 multi-agent mode hint 兼容

此字段级兼容修改将已通过源码核实的 Codex CLI 四个精确版本
`0.162.0-alpha.17.2`、`0.162.0-alpha.2`、`0.162.0` 和 `0.162.1` 作为快速路径，
而非仅凭整个版本系列判定兼容。其他成功报告版本的 CLI 会经过隔离能力检查：在临时
`CODEX_HOME` 和工作区中配置目标字段，向本机 loopback Responses sink 执行一次有限任务，
验证 developer prompt 效果，并确认字段拒绝整数。它不复制当前用户配置或认证信息；
Windows 通过 `SHGetKnownFolderPath(FOLDERID_ProgramData)` 检查系统级
`OpenAI/Codex/config.toml` 与 `requirements.toml`，Linux 检查
`/etc/codex/config.toml`、`requirements.toml` 和 `managed_config.toml`。
路径存在或检查失败时不执行 `exec` 并返回 `VERSION_SUPPORT_UNKNOWN`；macOS managed
preferences 无法证明缺席，因此也保持该状态。确认系统层缺失后，探测传入
`--disable hooks --disable plugins`；这两个 flag 本身不能禁用 managed hooks，所以必须先检查系统层。
捕获到矛盾效果时报告 `CAPABILITY_INCOMPATIBLE`；证据不完整或含糊时报告
`VERSION_SUPPORT_UNKNOWN`；两种状态都不授权写入。检查会向本机 loopback sink 发送有限的合成任务。
alpha `0.162.0-alpha.17.2` 与 stable
`0.162.0`/`0.162.1` 源码均显示 schema 将字段定义为字符串，
原生 mode resolver 识别 `Some("")`，指令 renderer 对空 custom 值返回无提示。alpha revision
的原生回归覆盖该行为：
[schema](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/config.schema.json#L2927)、
[mode resolver](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/session/multi_agents.rs#L77)、
[instruction renderer](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/context/multi_agent_mode_instructions.rs#L14) 和
[原生回归测试](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/app-server/tests/suite/multi_agent_mode.rs#L387)。stable 源码路径也已记录：
[0.162.0 schema](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/core/config.schema.json)、
[mode resolver](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/core/src/session/multi_agents.rs)、
[指令 renderer](https://github.com/openai/codex/blob/rust-v0.162.0/codex-rs/core/src/context/multi_agent_mode_instructions.rs)、
[0.162.1 schema](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/core/config.schema.json)、
[mode resolver](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/core/src/session/multi_agents.rs) 和
[指令 renderer](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/core/src/context/multi_agent_mode_instructions.rs)。
`0.162.0-alpha.2` 对应上游 tag `rust-v0.162.0-alpha.2`，peeled commit
`74e804deeb1241d5fe699b31fb319f7d46454c42`。仅当用户级
`features.multi_agent_v2.multi_agent_mode_hint_text` 不存在时写入空字符串；
在此 CLI 版本中，该空值会取消原生默认的 explicit-request-only mode hint。
能力检查矛盾或证据不确定、已有空值或自定义值、以及不支持安全编辑的 TOML 结构均原样保留。
若已有 `features.multi_agent_v2.enabled`，其值继续保留。

安全插入支持普通 `[features.multi_agent_v2]`、`[features]` 表和根 dotted
布尔值形式。Inline、quoted、特殊或其他合法结构（包括
`[ features . multi_agent_v2 ]` 这类空格表头）均保守报告
`STRUCTURE_UNSUPPORTED_PRESERVED` 并保留。迁移表后来加入用户结构时，卸载只删除受管
hint，保留当前 `enabled` 值及周边内容。

首次安装和升级均使用既有不可变候选维护流程：通过
`codex-maintenance-plan codex-install` 生成正常 intent，再用完全相同且已批准的
contract 和 candidate 执行 `codex-install --maintenance-contract FILE`，并绑定上文所述
准确的当前安装 runtime 身份。不新增独立
config editor，也不扩大 config 文件 ownership。结果中的
`native_mode_hint_compatibility` 报告状态；完成后的受管值为 `MANAGED`，幂等重跑可
显示 `changed: false`。验收时检查用户 `config.toml` 目标字段，以及
`thaliris-ownership.json` 中匹配的 `native_mode_hint` 记录：记录绑定绝对配置路径、
`prior.present: false` 和准确受管片段。整个 config 文件不会加入 `owned_bytes`，
也不会成为 generation rollback 的 ownership。操作完成后
`thaliris-host-transition.json` 必须不存在；若仍存在，不开始新维护操作，而由已批准的
executor 使用原 operation 和同一 contract 重放。安装中断时，journal 的 `finish`
包含字段记录、计划状态和写入阶段/结果。若中断后无法确定字段写入结果，会保留字段并
报告 `APPLY_OUTCOME_UNKNOWN_PRESERVED`，不会再次插入。
字段写入在原子替换前会重读 bytes；这不能防止外部编辑器在最终检查期间并发写入。

上述四个源码核实过的 0.162 CLI 版本，或通过隔离能力检查的其他版本，其既有安装/升级流程可在用户配置缺少该字段时写入简短、角色中立的根级
`developer_instructions`。它要求先继续必要的独立工作、优先使用有意义的通知而非重复轮询、
在完成证据不足时保留 UNKNOWN，并遵循角色和选定 handoff。已有空值或自定义用户值会保留。

结果报告 `controller_wait_guidance_compatibility`，ownership receipt 另存
`controller_wait_guidance` 字段记录。升级时，只有完整 TOML 片段与可信旧回执中的某个片段
精确匹配才会迁移。新回执记录当前片段和精确的历史受管片段，使恢复与卸载可以沿用历史
ownership 证据，而不拿旧文案与今天的文本比较。不同字段值、损坏历史或无法确认的
ownership 会保留，且不会写入该可选字段。迁移前，Host transition journal 会先记录旧回执
和写入阶段，然后原子替换字段。恢复会识别精确完成的新片段；无法确认的结果报告为
`APPLY_OUTCOME_UNKNOWN_PRESERVED`，本次恢复不会静默重试。若旧精确片段仍在，之后一次
明确安装可以重新计划迁移。重复已完成的升级不会重写 config 字段。卸载只移除精确匹配的
当前或回执记录的历史片段；用户编辑保留。整个 config 文件仍不属于 `owned_bytes` 或
Host generation rollback。写入器在原子替换前重读 bytes，但仍无法阻止外部编辑器恰好在最终
检查时写入。源码或 fixture 测试不能证明新的 Host session 已加载该设置，也不能证明模型
按等待提示行动。

卸载仍使用既有 `codex-maintenance-plan codex-uninstall` 与
`codex-uninstall --maintenance-contract FILE`。只有仍精确匹配的受管字段才会删除；原始
TOML 片段完整时会恢复之前迁移的 `enabled` 布尔值。用户修改和后来发生的结构变化会被
保留并报告。安装与卸载 contract 仍须满足上文的可信 runtime、candidate、executor、
当前安装身份及明确人类意图要求。

### Host 全局模型目录的保留与恢复

Host 全局 `model_catalog_json` 字段与其 backing catalog 一起由 receipt 管理。
包含必需 catalog 的 receipt 使用带显式 catalog capability 的 v2 格式，使旧 reader
无法忽略该字段而误将它当作非受管配置；新 reader 兼容有效 v1 receipt，并在明确授权的
安装/升级中迁移。v2 receipt 会使旧 reader 的安装或卸载在写入前拒绝；需要降级时，先用当前
reader 卸载，再安装旧 reader。已提交 archive 保留精确 catalog ownership，之后当前 reader 只在字段
缺失且 bytes 摘要仍匹配时才能重新认领。目录兼容性或在线来源失败在 Host generation 写入前判定并保留旧状态。
用户已编辑的目录可以报告为 `USER_CHANGED_PRESERVED`，并在继续其他已授权 Host 操作时保留；
但 `catalog_goal_met` 仍为 false，结果需要人工跟进。

`codex-maintenance-plan codex-install` 默认把 `--root` 提议为
`catalog_recovery_project_root`；`--catalog-recovery-project-root` 可选择其他绝对 project path，
`--catalog-recovery-source-root` 可额外指定 source path。这些只是 contract 提议字段，只有人类授权的
contract 才会把恢复 policy 写入 receipt。下一次真实 Host `SessionStart` 会由经过验证的 pinned runtime
在 project dispatch 前检查这些位置。
若指定的 activation marker 或 source 已不存在，只在字段 ownership 和 catalog digest 均精确匹配时，
才把受管 `model_catalog_json` 字段恢复为此前缺失状态。物理 catalog 文件保留在磁盘上。没有恢复
policy 的旧 receipt、被修改的用户 bytes、未知 ownership、malformed payload、未完成 transition
或 runtime failure 都不会触发清理；状态保留为 UNKNOWN 或 failed，并保全证据。检测到字段修改时报告
`USER_CHANGED_PRESERVED`，检测到 backing bytes 修改时报告 `CATALOG_CHANGED_PRESERVED`。流程不会下载或重建 project checkout。

卸载会移除受管字段，但保留 catalog 文件，并归档已提交 generation。之后的升级只有在字段缺失、
catalog digest 未变化且证据来自精确的 committed archive，或只使用一次的已完成 project-loss
restoration receipt 时才能重新认领该文件；只有实际移除过精确受管字段的 receipt 才能提供这项证明。字段原本已缺失而没有证明时报告 `RECOVERY_PROVENANCE_UNKNOWN`，不授权重新认领。成功后会清除 restoration marker。字段写入前会重新检查
bytes，但非协作 writer 仍可能在最后比较与 atomic replacement 之间并发修改，因此无法保证保全该时间窗内
未观察到的编辑。配置字段缺失并不授权删除 backing file。见
[模型目录维护报告](model-catalog-maintenance-report.md)了解兼容规则和记录状态。已接受的事务边界是保留
已观察到的用户修改并保留 backing file；并发 writer 剩余时间窗已公开说明，不是待决议事项。

磁盘证据不能证明 Host 实际生效。重启 Codex 并使用新的 Host session，观察默认提示
是否消失；随后用真实 Fresh Child 验收 V2 `fork_turns="none"` 或 V1
`fork_context=false` 隔离，并确认仍只收到选定 handoff，同时既有任务准入、角色、
隔离和安全行为保持正常。优先级更高的 project 配置或 CLI `-c` 可能覆盖用户级设置；
实际观察前应把生效状态报告为 UNKNOWN。测试和安装文件本身不构成此项验收。

### Fresh Child 指令来源

同一固定 Codex `0.162.0-alpha.17.2` revision 中，V2 child setup 在未提供 child override 时复制父 turn 的
developer instructions，选定 role 也可提供自己的 developer instructions。上游 app-server 回归覆盖
没有 override 时的继承路径：
[child setup](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/agent/child_config.rs#L131)、
[role instructions](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/core/src/agent/role.rs#L182) 和
[V2 inheritance test](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/app-server/tests/suite/v2/multi_agent_v2_developer_instructions.rs#L472)。
这证明指令传播路径，不证明运行中的 Host 已加载 profile 或 Agent 遵循指令。Thaliris 将选定 handoff
放在 spawn message 中，并将角色自己的 Fresh Child 指令与 resident Controller 程序分开生成。

未知 role 文档以 `preserved_manual_followup` 保留，不单独阻止项目 admission；
真正 AGENTS、activation、hook 等控制冲突仍阻止 admission。磁盘安装、Hook 注册和
信任、原生角色可用性、指令加载、task admission 与 managed readiness 必须分别验证。

显式要求迁移 global 指令时，仍使用既有 `codex-install --maintenance-contract FILE`。
可选 `instruction_migrations` 逐项绑定 Codex home 或当前用户 home 中已有的
`AGENTS.md` 绝对路径、完整 `before_sha256` 和已审阅候选 `after_sha256`，以及
`remove_spans` 中的准确 byte `offset`、`length`、`sha256`、`kind`。
仅支持删除 Codex-home 的完整 `durable-section`（Durable Thaliris synchronization
section）或 user-home 的完整 marked `global-block`。这些选择只批准具体旧
Thaliris 片段，周围所有 bytes 保留；Codex-home marked 入口仍须通过既有 ownership。
候选生成唯一正确 pinned-runner 入口，最终完整 hash 必须一致。不提供迁移数组
就原样保留 tail；普通 plan snapshot 不自动批准迁移。两文件先全部 preflight，
再进入同一既有 generation/replay/drift 检查；冗余 user-home 文件可变为空文件，
不会在 user-home 额外安装 Host，也不把用户内容记为受管 ownership。
