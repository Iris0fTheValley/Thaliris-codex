# 架构简化最终验收报告

## 结论

设计方向符合原目标：普通授权工作不再因缺少非关键身份、session 或仓库字段而被机械拦截；实现复用了现有 Core、Codex adapter、原生 Agent 和 DSH 策略面，没有增加运行框架、角色、任务状态、调度器或认证协议。维护语法候选已通过独立复核、Adapter 全套回归和修复后 Windows package/Hook 专项，因此按本报告列出的 source/fixture 边界验收通过；其语法拒绝范围明确限于已识别 shell 与可见 maintenance invocation。

非关键字段缺失只会让相应观察保持 `UNKNOWN`，它本身不创建任务 authority 或 managed-control 资格；显式的人类意图、所选任务和精确控制证据仍各自承担原来的职责。

这不是对已运行 Codex Host 的启用或行为验收。生成的 role files、Hook 和 package 输出都只证明候选源码；Host 当前是否已载入这些内容仍为 `UNKNOWN`。

## 改动和边界

Codex adapter 缩小了普通工作的权限门槛：移除了 delegated Controller 的窄工具白名单，以及 200 行/4096 output-token 的读取上限。缺少 session/turn/profile 等非关键字段或存在不相关的旧 task、fence、hook drift 时，普通读取、Git、诊断和隔离的原生工作可以继续。仅在操作实际依赖 managed lifecycle、Authority、readonly、隔离或受保护控制文件时，才要求对应的精确证据。

原生 `spawn_agent`、通信、`wait_agent`、`list_agents` 等普通执行不创建或消费 managed reservation，也不因普通 completion 文本改变 managed child 的状态。managed handoff 继续要求准确的 role/task/identity 绑定；`UNKNOWN` 不升级成 authority 或 completion。适配器也不借仓库路径推定另一仓库 task 的所有权。

为保住“Host install/uninstall 只能是一个 checked standalone command”这条窄硬边界，Adapter 增加了拒绝用途的 shell 语法扫描：严格 parser 决定哪些调用能取得 maintenance route；scanner 只检查不支持的组合语法中是否嵌入可见的 canonical/pinned maintenance 调用，不授权动态命令、别名或任意 wrapper。它不是通用 shell authorization。扫描器按已知显式 `tool_input.shell` 选择 Bash 或 PowerShell 引号规则，缺少已知 shell 选择时才回退到平台默认；独立复核和最终测试覆盖了双引号、反斜线、PowerShell backtick、注释、重定向目标及含空格的已知 shell 可执行路径。未识别 shell 与动态命令名仍不在覆盖范围内。

宽泛的 Controller 白名单和读量门槛已删除，但本次没有对总体代码行数、token 或调用成本做比较，因此不宣称总复杂度或实际成本净下降。

普通执行 profile 省略 `model` 和 `model_reasoning_effort`，由 Codex 按显式 spawn、全局 agent defaults、父级选择和 custom-agent 文件配置解析；profile 若明确固定某值，文件中的值优先。Astra 静态 profile 仍需当前任务的人类 opt-in；`luna-only` 仍固定 Luna/xhigh，并拒绝不可观察或冲突的绑定。语义职责和只读限制留在角色定义中，不随模型或 effort 改变。该关系与[官方 Subagents 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning)一致。

显式 closing handoff 将最终产品验收交给合适的既有执行者，要求其按原始目标给出逐项证据及 `UNKNOWN`。Controller 仍可做任务内普通工作、整合证据和机械关闭，但不得以自己的整合、Reviewer `READY`、测试通过或子任务结束替代独立验收。人类选定 `single-agent` 或 `controller-direct` 时不强制创建子任务；没有独立验收证据就保留 `UNVERIFIED`，交给人类决定关闭。

Core 保持 host-neutral authority/task primitives，没有新增共享 API；Core 的文档只说明跨 Host 共用的语义，见 Core repo 的 [`docs/thaliris-task-authority.md`](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-task-authority.md) 和 [`docs/thaliris-routing-protocol.md`](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-routing-protocol.md)。DSH 修改的是仓库内 canonical Controller policy 和初始 role template，以及从模板生成、用于新安装的 bundle 文本；它没有迁移或覆盖已存储的用户 role records，且不改 DSH runtime、model policy、pinning 或 nested-Scanner 行为。canonical sources 是 [`policy.mjs`](https://github.com/Iris0fTheValley/Thaliris-dsh/blob/main/policy.mjs) 与 [`role-templates.mjs`](https://github.com/Iris0fTheValley/Thaliris-dsh/blob/main/role-templates.mjs)。Codex 的 canonical prompt/role sources 是 [`controller_instructions.md`](../src/thaliris_codex/controller_instructions.md) 与 [`roles.py`](../src/thaliris_codex/roles.py)；派生输出由现有 [`sync_instruction_sources.py`](../tools/sync_instruction_sources.py) 同步。没有修改安装中的 Host、全局 AGENTS 块或冻结 benchmark。

## 十项验收标准

| 标准 | 结论 | 证据与适用范围 |
|---|---|---|
| 1. 普通授权任务缺少非关键身份/session/repo 信息仍可运行 | 符合 | 普通工作保留 `UNKNOWN` 并继续；无效的显式 contract 仍拒绝准入。见 [`_pre_tool_output`](../src/thaliris_codex/lifecycle.py#L4213)、[`test_unknown_controller_explicit_task_authority_is_reachable`](../tests/test_task_authority.py#L44)、[`test_unknown_ordinary_native_spawn_survives_damaged_control_evidence`](../tests/test_task_authority.py#L506)。 |
| 2. 未授权的危险操作仍拒绝 | 符合已覆盖边界 | 前一候选曾允许 `codex-install` 与 `git status` 的组合；独立 review 后修正了重定向目标表达式、转义空格、目标中的内层命令替换、双引号目标真实调用、Bash/PowerShell 引号规则及显式 shell 路由。最终独立 review 和当前 Adapter 全套回归通过；Windows ParseInput-only AST 与 isolated-install/Hook 专项也通过。拒绝边界限于已识别 shell 下可见的 canonical/pinned maintenance 调用；没有证据表明 CLI 授权绕过或 live Host 已修改。 |
| 3. Controller 可做任务内 read/Git/诊断/整合，但不自行最终验收 | 符合 | 普通 Controller 工具不再受窄白名单限制；最终验收要求独立 closing evidence，mechanical close 与产品 acceptance 分开。见 [`_pre_tool_output`](../src/thaliris_codex/lifecycle.py#L4213)、[`controller_instructions.md`](../src/thaliris_codex/controller_instructions.md) 与 [`test_explicit_closing_handoff_and_dynamic_model_selection_reach_resident_context`](../tests/test_prompt_contract.py#L425)。 |
| 4. Repository A 中的任务可在 B 工作，不伪造 B 的归属 | 符合（fixture） | Hook 依据实际目标仓库定位控制面，不以旧 task 或 foreign cwd 占用独立修复；测试覆盖 stale task/foreign cwd。没有把此 fixture 结论扩展成 live Host 多仓证明。见 [`host_preflight.py`](../src/thaliris_codex/host_preflight.py)、[`test_stale_active_task_and_foreign_cwd_do_not_require_recovery_for_native_repair`](../tests/test_task_authority.py#L548)。 |
| 5. 非 managed 原生工作可运行，且不能伪装为 managed 或升权 | 符合 | 通用 native spawn/communication/wait/list 不获得 managed reservation；普通完成响应不会释放 managed reservation。精确绑定和 completion 仍要求身份一致的原生证据。见 [`test_unknown_actor_active_native_spawn_is_ordinary_and_cannot_consume_managed_handoff`](../tests/test_task_authority.py#L476)、[`test_native_ordinary_completion_shapes_do_not_release_managed_reservation`](../tests/test_task_authority.py#L523)。 |
| 6. 旧 task 或 runtime/Hook drift 不锁住独立修复 | 符合（source/fixture） | stale task、foreign cwd 与 unrelated damaged fence 的普通 native repair fixture 通过；匹配 fence 仍拒绝。scanner 是 deny-only；普通 literal、已识别 shell 变体与 readonly refusal 有定向用例。全套 Adapter 回归通过；这不扩展为对任意 shell 或 live Host 的证明。见 [`test_stale_active_task_and_foreign_cwd_do_not_require_recovery_for_native_repair`](../tests/test_task_authority.py#L548)、[`test_recovery_fences_old_children_without_death_claim`](../tests/test_task_authority.py#L122)。 |
| 7. 角色职责不随 model/effort 改变 | 符合（源码） | 普通 profiles 不写入固定 model/effort；固定 Astra 兼容 profile 和 `luna-only` 仍受各自约束。语义 role registry、权限和角色 prompt 独立于执行绑定。见 [`agent_profiles`](../src/thaliris_codex/roles.py#L575)、[`_agent_profile`](../src/thaliris_codex/codex_adapter.py#L513)、[`test_all_semantic_roles_share_constrained_execution_only`](../tests/test_execution_constraint.py#L53)。实际 Host 解析值未观察。 |
| 8. waiting、bootstrap 与安装升级不回归 | 符合（source/fixture） | 当前 Adapter 全套回归通过。首次 planning read 的可选 I/O 错误不再导致有效安装失败；伪造 ownership 与写入前 journal 失败仍 fail closed。隔离安装/Hook fixture、等待配置专项检查及 Adapter wheel 工件构建通过。见 [`wait_guidance_config.py`](../src/thaliris_codex/wait_guidance_config.py)、[`codex_adapter.py`](../src/thaliris_codex/codex_adapter.py#L1623)、[`test_wait_guidance_config.py`](../tests/test_wait_guidance_config.py#L313)。 |
| 9. 保留用户配置/task data/历史所有权/生成文件 | 符合（fixture） | 文件名绑定的 immutable 历史 profile bytes 与 SHA/blob 证据只迁移精确的旧默认输出；错误文件名、编辑过的用户内容和未知字节不被接管。Task recovery 也要求显式选中 Task ID。见 [`_ROLE_MODEL_PREDECESSOR_PROFILE_HASHES`](../src/thaliris_codex/codex_adapter.py#L484)、[`test_fixed_predecessor_profile_upgrade_preserves_user_edits`](../tests/test_roles.py#L122)、[Core `AuthorityStore`](https://github.com/Iris0fTheValley/Thaliris/blob/main/src/thaliris/authority.py#L85)。 |
| 10. 真实减少不必要的硬检查，不转成新机制 | 方向符合，复杂度净变化未实测 | 删除字段缺失导致的普通工作拒绝、delegated allowlist 和读取数量/长度门槛；为 Host maintenance 的 standalone 约束增加了窄的 deny-only shell syntax scanner。没有新增 role、状态字段、scheduler、token/bearer 或授权 protocol；Core/DSH 只同步共享语义。没有总代码行数、token 或调用成本对比，也不声称覆盖任意 shell/MCP 行为。 |

## 验证与限制

验证按源、fixture、渲染输出、local package-artifact smoke 和 live Host 分层解释。DSH 的本地 bundle/archive 与 Core pin wheel smoke 只证明这些 DSH/Core 工件；本次另以隔离临时输出构建 Adapter wheel，并比对关键包文件字节。该构建没有安装到 Host。已知源/fixture 检查覆盖 normal、refusal、`UNKNOWN`、跨仓库选择、stale recovery、失败/中断与 completion 顺序。它们证明各测试输入下的 adapter 逻辑和文件所有权行为，不证明真实 Host actor 身份、当前会话 profile 或安装内容已加载。

本次已观察到的定向与 integration 结果：

- authority/drift 定向集合：157 passed、3 skipped；跳过项是 Windows symlink 权限场景，junction 场景通过。
- 角色 prompt/native 来源检查通过；现有 73 个检查及新增 3 个强化情形通过。
- managed completion 的两个定向情形及 18 个 native/model/nested 情形通过。
- install/ownership 的新增 29 个情形通过；此前 maintenance 组合的 148 个情形通过。可选首次 planning read 的修复由含/不含旧 ownership record 的升级/卸载及 forged-record 拒绝覆盖。
- 实际 Windows packed Hook smoke 通过：packed Hook 命令串为 7489 字符，最长命令行为 7149 字符，均低于 `cmd.exe` 的 8191 字符命令行限制。源脚本另测为 6101 字节；字节数不与命令行字符限制比较。
- instruction sync 的 `--check --core-routing-root` 检查显示当前来源与派生输出一致；Core 无 API diff，DSH 候选没有 runtime/model-policy/pinning diff。
- Core routing 集合 3 passed，完整 Core 检查 185 passed、9 skipped。DSH prompt/bundle/native、18 bridge 情形及 local packed-activation smoke 通过；smoke 使用 3 个 local archives 和 isolated Core pin wheel。
- 更早候选的 Adapter 全套为 1092 passed、9 skipped、10 failed；这是修复前结果，不计为当前候选通过。maintenance syntax 独立 review 之后复现并修正了重定向目标、命令替换、shell 方言和显式 shell 路由边界。最终独立 review 标记该局部候选 READY，并报告 14 个 targeted checks 通过，其中包括 11 个 PowerShell ParseInput-only AST 样例，以及对 6 个固定 shell 路由分类观察的复核。当前生产源码候选在 Windows / Python 3.11 上运行 Adapter 全套 `py -3.11 -m pytest -q`：1127 项中 1118 passed、9 skipped、0 failed，进程 exit code 为 0。随后仅将既有 Windows PowerShell maintenance fixture 显式写为 `tool_input.shell = "powershell"`，使其他平台也采用相同实际语义；该 fixture-only 修订后 `--collect-only -q` 仍为 1127 项，AST、shell 路由、隔离安装/maintenance 与 packed Hook 专项的六组 nodeids共 17 项再次通过，生产源码未变，故没有机械重跑全套。另以 `py -3.11 -m pip wheel --no-deps --wheel-dir <temporary-outdir> .` 构建 `thaliris_codex-0.4.4-py3-none-any.whl`（207019 bytes，SHA-256 `7101c8bc4576929ac5cbce8aa40ba487f3647065f0c821a296d94d461ecdee15`）；解包后 `lifecycle.py`、`roles.py`、`wait_guidance_config.py` 与 `controller_instructions.md` 均与 canonical source bytes 完全相同。没有把该 wheel 安装到 Host。最终 `sync_instruction_sources.py --check --core-routing-root` 显示 `instruction artifacts: current`，并确认 Adapter 与 Core import 均来自本次 checkout 的 `src`。未执行任何 Host maintenance 命令，没有证据表明 live Host 已修改。

上述独立评审结果和 Adapter 测试由对应 observer 实际执行并记录；Core/DSH 检查沿用各 repo owner 的终局证据，本验收 slice 未重复运行。当前 Codex 进程实际加载的新 profile/Hook、真实 Host 下的 actor/session/身份和模型解析、Host 安装状态、生产级多仓并行写入时序仍未证明。Windows symlink 三项保持 skipped，而非推断通过。也没有据此声称对所有第三方 MCP 或任意 shell 行为进行了完整授权覆盖。

可在各仓库根目录用以下通用命令复核已覆盖的 source-level 检查；Adapter 的集成环境需先将 `THALIRIS_CORE_SOURCE` 指向 Core checkout：

```powershell
# Thaliris-codex
$coreRoot = (Resolve-Path '<path-to-Core-checkout>').Path
$adapterSrc = (Resolve-Path 'src').Path
$env:THALIRIS_CORE_SOURCE = $coreRoot
$env:PYTHONPATH = "$adapterSrc;$coreRoot/src"
py -3.11 -m pytest tests/test_task_authority.py tests/test_drift_recovery.py tests/test_execution_constraint.py tests/test_roles.py tests/test_wait_guidance_config.py -q
py -3.11 -m pytest tests/test_single_handoff.py tests/test_prompt_contract.py -q
py -3.11 -m pytest tests/test_runtime_identity.py::test_embedded_maintenance_agrees_with_powershell_command_ast tests/test_runtime_identity.py::test_compound_maintenance_quote_escapes_follow_shell_dialect tests/test_runtime_identity.py::test_compound_maintenance_uses_explicit_executor_shell tests/test_runtime_identity.py::test_powershell_runner_receipt_and_host_maintenance_are_direct_only tests/test_runtime_identity.py::test_host_command_rejects_tampered_script_before_dispatch tests/test_drift_recovery.py::test_windows_packed_hook_preserves_exact_ownership_and_healthy_dispatch -q
py -3.11 -m pytest -q
py -3.11 tools/sync_instruction_sources.py --check --core-routing-root $coreRoot
$wheelOut = Join-Path $env:TEMP ("thaliris-codex-wheel-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $wheelOut | Out-Null
$env:THALIRIS_WHEEL_SMOKE_OUT = $wheelOut
py -3.11 -m pip wheel --no-deps --wheel-dir $wheelOut .
@'
import os, pathlib, zipfile
wheel_dir = pathlib.Path(os.environ["THALIRIS_WHEEL_SMOKE_OUT"])
wheel, = wheel_dir.glob("thaliris_codex-*.whl")
expected = {
    "thaliris_codex/lifecycle.py": pathlib.Path("src/thaliris_codex/lifecycle.py"),
    "thaliris_codex/roles.py": pathlib.Path("src/thaliris_codex/roles.py"),
    "thaliris_codex/wait_guidance_config.py": pathlib.Path("src/thaliris_codex/wait_guidance_config.py"),
    "thaliris_codex/controller_instructions.md": pathlib.Path("src/thaliris_codex/controller_instructions.md"),
}
with zipfile.ZipFile(wheel) as archive:
    assert all(archive.read(name) == source.read_bytes() for name, source in expected.items())
print("wheel payload matches canonical source bytes")
'@ | py -3.11 -

# Thaliris Core
$env:PYTHONPATH = (Resolve-Path 'src').Path
py -3.11 -m pytest tests/test_core_authority.py -q

# Thaliris DSH
npm run test:prompts
npm run test:native
```

## Git 收尾

| 仓庫 | 本次開始時 HEAD | 源码候选 commit / push / CI |
|---|---|---|
| Thaliris-codex | `5f80214bb8d4ef219851405b017f660c5f8b554e` | `491335b69fa6d26fbb8d0951838cebee1c2ecc83`；push 后 `ls-remote` 与本地 `main` HEAD 一致。Adapter CI [38158248844](https://github.com/Iris0fTheValley/Thaliris-codex/actions/runs/38158248844) 完成 SUCCESS，6 个 Windows/Ubuntu Python 3.11/3.12/3.13 job 全通过；CI 使用 unchanged Core pin `56e48ac299dd2c5c4b16c992db732a55b7790893`，当前 Core commit 的验证见下行。本报告自身提交不在此列。 |
| Thaliris Core | `c8fae1e5953f8b296e12dc16b1e71329e0317e72` | `aecc0b3cbc545f6f66af1e09c08439b27da24aa5`；push 后 `ls-remote` 与本地 `main` HEAD 一致。Core CI [38158192915](https://github.com/Iris0fTheValley/Thaliris/actions/runs/38158192915) 完成 SUCCESS，7 个 job 全过（benchmark source check 与 Windows/Ubuntu Python 3.11/3.12/3.13）。 |
| Thaliris-dsh | `2c63c6b8de54917bcb7c42ec79029ec28053c700` | `5684fbf114ba51fb07368f5f4b510798de3c9455`；push 后 `ls-remote` 与本地 `main` HEAD 一致。`gh run list` 未返回 CI run，不报告 CI 通过。 |

未创建 pull request，也未修改或安装到 live Host。工作树中的已有本地材料与未跟踪内容应由 Controller 在提交前逐项保留或排除；此报告本身不据工作树外观推断 ownership。
