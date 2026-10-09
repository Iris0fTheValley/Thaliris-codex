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
