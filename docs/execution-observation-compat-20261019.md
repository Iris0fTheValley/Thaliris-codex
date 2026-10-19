# 执行观察适配：Focused 候选与真实边界（2026-10-19）

本轮在 `96b4c72472d2529ea2f0ce277e7c23ebc3e22521` 上补齐了**普通 Executor 可发现且实际可调用的包入口**。真实 Native Implementer 对照中，候选在 34 秒操作进行期间没有出现 usage 更新，基线在第 10 秒出现一次；但候选整轮 input、uncached input 和 output 均增加。本轮证明运行中观察可合并，**没有证明整轮 token 或延迟节省，更没有消除 Host 强制 outer yield**。

## 权威链及修改

- Global/project shared 边界源仍为 `codex_adapter._global_agents_block()` / `render_managed()`；未改全局或项目共享边界，未改 Core/DSH。
- Controller 原始 Markdown 为 `src/thaliris_codex/controller_instructions.md`，由 `controller_instructions.render()/resident()` 和 bootstrap 返回完整带摘要的 resident guidance。新执行观察短段来自 `execution_observation.INSTRUCTIONS`，在现有 waiting 占位符一次渲染。
- 所有 Native role 语义源仍为 `roles.py`。同一短段一次组装到各 child role；Executor、Reviewer、Scanner 的原有职责及 readonly/权限边界不变。`codex_adapter._agent_profile()` 生成 TOML `developer_instructions`；`tools/sync_instruction_sources.py` 更新跟踪的 11 个 profile 与角色/Controller 文档。
- 真正安装时，`host_maintenance.py` 才会将 profile 写入选定 home 的 `agents/`；project init 不负责安装 Native profile。本轮只建临时 package/runtime/profile/config overlay，未写生产 CODEX_HOME，也未执行生产 Host maintenance。已安装字节不证明当前 Desktop 已加载。
- 新公共命令 `<installed pinned runner> execution-wait --tool-source` 返回包内 JS、摘要和使用步骤；裸命令返回短说明，`run/github/inspect/cancel` 分派到原有 foreground Python observer。源码不再只能从 repo 顶层 `tools/` 取用。
- JS canonical 是 `execution_observation.TOOL_SOURCE`，由既有 sync 路径生成 `tools/owned_tool_wait.js`。放在 `.py` 内使其受既有 immutable runtime manifest、source-wheel 和 reviewed-source 边界覆盖，无需新增未审阅的运行时来源。

新 helper 只对 expected-long、finite、noninteractive 且由本次调用新建的 session 选择合并等待。短、交互/TTY、缺失 `write_stdin` 时仅原生启动一次；旧安装不能检索命令时也在启动前原生降级。启动后未知/error/归属不符只返回 UNKNOWN 和原 session，绝不重新启动；无 attach-by-ID、猜 PID、自动 resume 或沙箱提升。所有结果仍为 `semantic_done: false`。

历史兼容修复来自实际发现：短段变化会使已发布的 11 个默认 profile 全被识别为 `user`。现用发布 commit 的 immutable `roles.py` Git blob 与精简 `_agent_profile` renderer 重新生成 default/luna-only 共 22 个精确摘要，按文件名注册；对应 role-pack 也保留历史摘要。证据位于 `tests/fixtures/execution-observation-predecessor/`，测试验证 Git blob、SHA256、用户修改拒绝和错文件名拒绝。没有把当前候选生成物自封为历史所有权。

## 实测及证据分层

可审阅的脱敏事实在 [runtime evidence](../tests/fixtures/execution-observation-runtime-20261019.json)。原始证据仅限本次新建实验的 stdout、app-server 通知和 receipts；未扫描其他 session。跟踪产物排除了 native session ID、机器绝对路径、账户事件与认证数据。

### 普通 Native Implementer：相同输入的基线/候选

两组均使用当前正常 CLI 认证、fresh 无父历史的 `thaliris-implementer`、父默认 `gpt-6.1-sol` / `medium`，相同 Python fixture（progress → 34 秒静默 → done/exit 0）。没有在任务正文提示 helper 名称或等待方案。`config/read` 原始返回分别确认 baseline 和 candidate profile 路径；baseline profile 直接取自发布 commit。仅调用参数覆盖 agent config，并关闭该次 invocation 的 hooks/plugins，不改生产配置。

| 证据 | 基线 | 候选 |
| --- | --- | --- |
| 原始执行命令 | 直接运行 fixture | 自然调用 pinned runner `execution-wait --tool-source`，然后运行 fixture |
| helper 检索命令数 | 0 | 2，第二次与运行在同一观察链 |
| fixture duration | 34.104 秒 | 34.096 秒 |
| fixture 运行区间内 usage 通知 | 1（第 10.003 秒） | 0 |
| child 整轮 usage 通知 | 3 | 3 |
| child input / cached / uncached | 52893 / 41728 / 11165 | 56526 / 36608 / 19918 |
| child output / reasoning | 214 / 0 | 482 / 38 |
| parent input / cached / uncached | 50554 / 33152 / 17402 | 50669 / 40320 / 10349 |
| parent output / reasoning | 365 / 0 | 403 / 0 |
| 输出及 Native 终态 | progress、done、exit 0 | 相同 |

这些是 app-server 的真实 `thread/tokenUsage/updated` 数值，uncached 为 input−cached。通知数不是 provider 请求数；没有 raw provider request 或 raw JS call trace，真实模型请求数保持 UNKNOWN。没有从内部轮询次数推 token。profile 配置已读取、helper launcher 实际调用、运行期间事件、子 FINAL 自述分别列为不同证据；子自述“使用 helper”不能单独证明 JS 原始调用。候选的中途返回改善与观察合并一致，但短夹具的检索成本抵消了整轮收益；不将缓存差异、整轮 usage 或单样本时长解释为节省。

最初 Verifier 试跑在 workspace-write 下遭 `helper_sandbox_lock_failed`，fixture 启动前即 UNKNOWN。后续按 owning task 已有的 danger-full-access、approval never 做隔离试验；这不证明 workspace-write 平台可用。首次 Verifier 还误猜 `controller-instructions --section execution-wait`，因此最终短段明确为公共命令 `execution-wait --tool-source`。最终普通 Implementer 不再误猜该 section。

### 实际 Host 工具及 outer 边界

- 从隔离 candidate 的完整 manifest + pinned runner 取到实际包内 helper，source SHA256 为 `3e6ccac5c3ad51f2ab45f6f2cceaa16734601147bab8c7d6983e345213320e9e`。实际 `functions.exec` 调用它运行 34 秒夹具，36.7 秒完成一次模型可见返回、两次内部观察，输出完整、exit 0。既有文档中 separate-calls 的 2 返回基线仍保留，不伪装成本轮 token 对照。
- 显式 outer yield 1000ms 得到 cell 32；只对该 cell 请求 `functions.wait` 3600000ms，7.3 秒后提前返回 terminal。证明参数被接受及完成可早返；有效最大时长、满小时持有、用户中断能力仍 UNKNOWN。
- cell 52 的 `terminate:true` 返回 `Script terminated` 后，同一 60 秒有限夹具的 Python observer 仍接收精确 durable cancel：先 `CANCEL_REQUESTED / termination UNKNOWN`，随后 receipt 为 `CANCELLED`、9.109 秒、`CONFIRMED_JOB_EMPTY`、完整输出。证明终止 JS cell 不等于终止外部命令；只有后续精确取消及终态证据证明该 owned tree 已终止。
- Native 对照两组均收到明确 `subAgentActivity completed` / `turn completed`，父 wait 在完成通知同一时刻早返并消费 FINAL，无重复状态确认。这支持该隔离连接的 completion early return；没有证明完整请求上限或真实用户中断。普通消息仍不当完成。
- 当前实际服务端拒绝 `thread/items/list`，ephemeral thread 也拒绝 `thread/read includeTurns:true`。这些补充读取失败不抹去已经收到的原始 Native terminal，也不能伪造 raw JS 或完整历史。

### CI 与安全降级

实际 pinned CLI 对 [run 39224249571](https://github.com/Iris0fTheValley/Thaliris-codex/actions/runs/39224249571)、commit `4bdaceed617f114b66b34beddf59b46f19fecd23`、attempt 1 做只读观察：`RUN_COMPLETED / conclusion failure`、一条 observation、结束 checkout association VERIFIED、`semantic_done false`。CLI exit 0 表示观察完成，绝非 CI 成功。临时精确 commit worktree 已移除。

重复状态吸收、交错 attempt/stale callback 拒绝、早期 job failure/等待介入、传输错误 UNKNOWN 由原有 provider-shaped focused tests 覆盖。既有真实长 CI 成功观察（67 snapshots、9 内部观察、5 outer 返回）保留；本轮没有新旧真实 CI 模型请求/成本对照，也未创建远程 CI 任务来制造失败。

## 确定性验证、UNKNOWN 与交付

Focused endpoint 已收敛；以下是最终源码的本地确定性检查结果：

- Python 3.11.9 在 Windows 上，按 `release/core.lock.json` 指向的 Core 源码 `973f0f73b79142783be1eff6e6a639743de310a0` 运行完整 Adapter 套件：`1785 passed, 14 skipped, 1 xfailed`（1556.81 秒）。其中包含执行观察、等待选择、原生等待能力、CLI/Host-transition、权限、readonly、identity、profile 历史所有权、CI/provider fixture、package 边界和 release/build fixtures。其后仅修改 Adapter sdist 排除规则并添加一项 package-boundary 回归；相关 package/release 测试 `9 passed`。
- Node `tests/test_owned_tool_wait.js` 通过；canonical instruction sync 与 `--check` 均报告 `instruction artifacts: current`；`git diff --check` 通过。
- Core 与 Adapter 的 0.4.6 wheel 均由 Hatchling 1.32.4 成功构建。Adapter sdist 的首次审阅发现默认文件选择会纳入工作树里的未跟踪本地状态目录；`pyproject.toml` 现显式排除 `.agent-memory/`、`.context/` 与 `.milestones/` 的根路径和子项，`tests/test_package_boundary.py` 覆盖这些排除项。最终 Adapter wheel 与 sdist 均成功构建，sdist 共 406 项且不含这些本地状态路径。全新临时 venv 安装 Core/Adapter wheel 后，console `execution-wait --tool-source` 返回与 Python 包内 canonical source 完全一致的 JS；SHA-256 为 `3e6ccac5c3ad51f2ab45f6f2cceaa16734601147bab8c7d6983e345213320e9e`。读取没有创建指定的空 project root 或隔离 `CODEX_HOME`。检查只比较了归档路径，未打开本地状态文件内容。
- Ruff 默认规则在触及的文件中报告 34 条诊断，均位于本次未改动的行；本次新增或修改行上为 0 条。仓库 CI workflow 没有 Ruff step，因此没有为清理既存格式/导入问题扩展本次范围。
- 源同步没有改动派生物之外的 canonical 内容。本地提交审核只选择本候选的源、生成 profile、文档、测试和脱敏 evidence；`.agent-memory/`、`.context/`、`.milestones/` 与临时隔离 runtime 均未进入候选。

本机当前可用 pinned runner 的 `--help` 未列出 `execution-wait`；隔离安装的候选 wheel 则已证明包入口与 source retrieval 可用。该差异说明候选包能力，不证明 production runner 或 Desktop 已更新。当前 Host 安装、role catalog 和 profile activation 仍为 `UNKNOWN`。

仍为 UNKNOWN：生产 Desktop 当前 profile/role catalog activation、Desktop 跨回合自动继续、真实用户中断、完整最大 outer/native wait、raw JS/精确 provider 请求数，以及真实 CI 新旧 token 成本。无新 Host/runtime/daemon/scheduler 架构，无生产安装或自动恢复承诺。Core 保持 host-neutral，Controller 仍决定语义验收；本轮观察不自动满足全局需求。

当前 child 未收到可用于 `task-observe` 的精确 historical native handoff/provenance；Controller 也确认该 ACTIVE Work 无绑定。没有猜测 task/requirement 标识或导入历史记录；由 Controller 按其现有绑定和 R1/R2/R3 处理本报告事实与 source refs。该管理关联边界不改变本地候选、源码验证或已授权 Git/CI 交付。

Host 接口核对使用 OpenAI Docs 技能及[官方 app-server 文档](https://learn.chatgpt.com/docs/app-server)：官方 `command/exec` 与 experimental `process/*` 的 sandbox 边界不同。本实现继续沿现有 Host shell 工具执行，没有采用后者作为旁路。官方文档不能替代上述实际 Host schema/运行证据。
