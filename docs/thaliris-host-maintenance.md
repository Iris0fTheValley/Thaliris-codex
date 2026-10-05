# Host maintenance and project admission

Host maintenance has its own explicit intent. It does not borrow a project's
task authority, initialize a project, approve its unknown AGENTS control block,
change a task boundary, or unfence an actor. An arbitrary workspace is sufficient.
Known children, readonly actors and fenced sessions remain denied. An actor with
missing native identity remains UNKNOWN; the intent is shared-OS governance,
not mechanical authentication of a human or positive Controller proof.

Install both reviewed wheels in a new dedicated Python 3.11+ environment, with
system site packages disabled and no executable/path-extending `.pth` files.
Use full immutable Git commit refs or verified artifact SHA-256 pins. Do not
upgrade packages in the already pinned runtime directory. The current installed
runtime, the maintenance executor and the approved candidate are separate
identities. Installation renders with the approved candidate executor; an old
trusted executor can launch that independently selected candidate. The caller
must execute the selected installed package, not development source via PYTHONPATH.

`codex-maintenance-plan` is read-only. It reports the exact candidate runtime
identity and an intent object from the supplied actual human instruction. Its
ownership snapshot is inspection evidence only: it never approves existing files.
For example, in PowerShell, after installing the immutable candidate wheels:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$exe = (Get-Command thaliris).Source
$plan = (& $exe codex-maintenance-plan codex-install --executable $exe --source-pin 'git+https://github.com/Iris0fTheValley/Thaliris-codex.git@<reviewed-full-40-character-commit>' --human-instruction 'Install the reviewed Thaliris Host integration requested by the user.' | ConvertFrom-Json)
$plan.maintenance_contract | ConvertTo-Json -Depth 16 | Set-Content -Encoding utf8 .\host-install-intent.json
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

Candidate renderer equality, HEAD, matching markers, a reproducible old renderer
or a runtime manifest alone establish no prior authorization or byte ownership.
Legacy installations lacking a receipt need specific human approval of the exact
reviewed `legacy_owned_bytes` hashes (the global span uses `AGENTS.md#global`).
Select only content affirmatively owned by Thaliris; do not copy the whole plan's
snapshot as an automatic approval. Unknown control bytes are preserved and the
affected operation stops before writes. Historical fixtures remain independent
witnesses, not a place to add the next candidate's bytes to an old release.

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

先把两个已审阅 wheel 安装到新的独立环境，再用 `codex-maintenance-plan` 检查
身份并生成维护意图。源码必须指定完整不可变 commit，或已校验 artifact SHA-256。
plan 的现有文件 hash 只是审阅材料，不自动批准 ownership。安装前先完成全部
运行时、隔离、路径、ABI、旧安装 drift、ownership 与控制冲突检查，之后才写入。
新安装记录绑定原始授权和准确 bytes，未来升级不依赖旧版本预先知道新输出。
候选 renderer、HEAD、marker、旧 renderer 可复现和 manifest 都不能证明原始授权。

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
