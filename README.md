# Thaliris Codex adapter

语言：简体中文 | [English](README.en.md)

一个轻量、Git 原生的 AI 编程上下文与编排层。

Thaliris 通过选择必要事实、约束和证据，保护高能力模型在聚焦上下文中的有效推理。上下文质量不等于数量，运行时提示词本身也是工作上下文的一部分。无关信息、竞争目标和历史轨迹越多，真正需要推理的信息越容易被稀释或干扰。

**注意力才是最贵资源。** 这里的注意力指高能力模型在干净、聚焦的上下文中用于解决困难问题的有效认知预算，而不是简单的 Token 价格，也不是 Attention 算法。

Thaliris 管理的是信息进入推理路径的条件，而不是重新实现通用 Agent Framework。证据、freshness、memory、任务状态和 adapter 机制服务于正确的信息传递与任务执行，不是为了增加流程。通过认知隔离与合理的模型能力分配，项目争取提高复杂任务的质量和整体效率，但不以丢失必要推理或证据为代价。

> **状态：** Beta。设计目标不等于已证明的收益；历史 ABCD 结果只适用于原实验设置，最近的提示词、编排与等待规则优化尚无新的受控质量或成本对照结果。

## 为什么要做这个项目

长时间的编码任务往往会不断积累上下文。

单个代理最终可能同时携带：

* 仓库探索；
* 失败的搜索路径；
* 实现细节；
* 测试输出；
* 调试轨迹；
* 架构推理；
* 审查标准；
* 旧决策；
* 无关的历史上下文。

更多上下文并不自动意味着更好的上下文。

对于强推理模型，更大的风险往往不是 token 的绝对数量，而是同一条推理轨迹中相互竞争的目标数量。

如果要求一个代理同时：

* 调查，
* 设计，
* 实现，
* 验证，
* 审查自己的设计，
* 记住此前的失败，
* 并满足一份庞大的流程检查清单，

那么它所解决的问题，已经不同于让代理根据必要证据专注回答一个推理问题。

`Thaliris` 建立在一个简单理念之上：

> **保留有用信息，但不强迫每个角色携带每一条信息。**

因此，本项目把上下文边界视为工程架构的一部分。

---

## 名字由来

Thaliris 由 Thalamus（丘脑） 与 Iris（虹膜） 组合而来。

丘脑负责筛选与路由进入认知系统的信息，虹膜调节进入视野的光量。Thaliris 借用这一意象来处理 Agent 上下文：控制什么进入推理路径，保留有依据的信息，并隔离彼此无关的工作集。

---

## 理念如何形成工作行为

### 长期决策与短期工作上下文

长期 Controller 保留用户目标、范围、硬不变量、验收条件和已选择的决策依据，决定下一步需要什么工作。短期执行角色承担调查或实施的工作集：搜索路径、调试轨迹和原始日志留在负责该工作的上下文中，返回的是结论、来源位置、验证结果、矛盾和会改变决策的未知项。Controller 不必重新携带全部过程，执行角色也不必背负整个项目历史。

Fresh Child 是新的原生角色会话，通过选择性 Handoff 接收完成当前工作所需的事实、约束、来源与验收条件。隔离历史不是删除证据：必要的原始文件仍可按位置重新读取，已完成调查的清单和事实应复用。工作集不等于交接集；被记录或保留的信息，不会因此自动传递给每个角色。

Controller 保留全局用户需求与验收条件；Child 只接收所选局部目标、局部验收与来源指针。
当已发现的事实改变局部结论、局部验收或关键 UNKNOWN 时，Child 应记录该事实，保留来源、
handoff 链路与不透明 requirement refs；这不增加搜索义务、全局重要性判断、模型调用或验收 gate。
关键证据跨后续 Handoff 保持可见，直到 Controller 明确重评当前候选所关联的用户需求：
satisfied、unknown、repair，或说明为何已不影响当前候选。读取或确认收到不算处置，
PASS、READY、Completed、DONE 不能替代需求判断。旧观察与判断保留为历史，不自动成为当前真相。
不可变的 candidate 是 handoff 逻辑标签，不是仓库快照；来源与可选的 `observed_state` 区分局部观察，缺失实际状态身份时保留 UNKNOWN。
Nested Scanner 保留 parent provenance，但不推断全局 requirement relevance，未关联观察由 Controller 选择适用需求。
后续 judgment 用 `judgment_refs` 与理由或完整 observation basis 显式处理此前 repair/unknown 依据；只有新正面证据不会让旧依据退场。
Adapter 在普通 Controller 结果交付时重新呈现 bounded evidence，时序早于下一次 broad completion 判断；不增加轮询、固定阶段、Agent 或 close gate。

Curator 只维护精确选定的持久知识与 INDEX，可编辑、合并、拆分、替换或删除已有条目。
Core 提供带 CAS 的文档维护与来源记录，模型决定语义协调。Curator 不扫描知识库、不委派、
不决定产品验收，也不负责实时证据连续性。记忆保留简洁的未来决策价值；原始细节留在
canonical Artifact、Git 或 rollout 记录中。

| 角色 | 承担的工作 | 为什么区分 |
| --- | --- | --- |
| Investigator | 在选定范围内调查事实，给出准确来源、覆盖范围、矛盾与未知项 | 将探索历史留在调查上下文中，不替 Controller 决定架构 |
| Implementer | 实现已接受的稳定方向，完成必要验证、局部修复和被分配的收尾 | 让确定性工作复用明确契约，不重复开启架构决策 |
| Focused Implementer | 对耦合的不变量持续推理、实现、观察运行时反馈并修订，直到核心语义收敛 | 为仍可能改变解决方案的问题保留聚焦的认知预算；随后由新的普通 Implementer 承担被分配的确定性收尾 |
| Reviewer | 在候选方案收敛后，独立、只读地挑战原验收条件、不变量与跨边界行为 | 不携带实现者的完整调试轨迹，用证据检验候选方案，而不是替实现者继续写代码 |

角色是按工作形态选择的能力，不是每个任务必须走完的阶段。不会强制所有任务使用多个 Agent、固定审查轮次或统一步骤；明确的单 Agent 执行选择也应保留。是否调查、独立审查或并行，取决于当前证据、决策耦合和实际写入冲突，而不是文件数、调用数或耗时阈值。具体角色绑定与执行模式由各 Host adapter 实现。

### 证据、任务记录与可复用知识

结论应带有证据来源及其适用范围。文件 hash、Git blob 和 test/runtime observation 可以说明观察了哪个版本；freshness 只核对声明过的来源是否变化，不能证明所有依赖都未改变，也不能替模型判断结论是否仍然适用。证据不足的结论保留为 `UNVERIFIED`；缺少执行或身份观察时保留 `UNKNOWN`，不将推测升级为确认。已有记录只是可检索材料，不是下游必须接受的事实。

短期任务记录保存当前 Task ID 的事实、待处理工作和证据，不复制对话 transcript。Core 的 `task-promote` 只持久化 Controller 选择的 `.agent-memory/` Markdown 记录；每条记录要求 `id`、`path` 和 `text`，`title` 默认是 ID，`source_refs` 默认是空列表。它只创建新的非 INDEX Markdown 文件，Core 拒绝覆盖已有 durable target。推广事务以当前 Task ID 和 task revision CAS 提交。可选的 legacy `status` 是不透明字段，不表示确认或生命周期。每条记录的 text 最多 16,384 个字符、source_refs 最多 64 项。推广记录不能写入 `.milestones/`；可选的 INDEX 更新可面向 `.milestones/INDEX.md`。`INDEX.md` 是由模型撰写的语义导航；更新提交完整文件内容，Core 校验预期 digest、路径和链接，不替模型生成索引。Controller 决定哪些信息值得长期保留；持久化与向下一角色传递是两个独立选择。Host 的可选记忆集成另有自己的存储与授权契约。

每个独立任务都有以 UUID 标识的 Task ID 和自己的本地状态文件。继续已有任务时明确选择 Task ID 与相关证据；开始新任务时创建新的 Task ID，不从旧工作区状态推断当前任务。旧 `ACTIVE`、`UNKNOWN` 或损坏记录不会自动占住唯一任务槽位，但真实的共享文件重叠写入仍需协调。原生会话关联、恢复和权限检查属于 adapter；Task ID 本身不授予权限，也不构成 Host 身份认证。

Controller 将用户原始目标、验收标准和可用证据结合起来，决定产品是否完成，以及应路由修复、请求有用的额外验证，还是记录机械关闭。Executor 实施并验证分配的工作，返回候选状态、逐项证据和未验证部分的 `UNKNOWN`。Reviewer 可在独立只读挑战确实有价值时参与；它不是必经阶段，也不需要单独的 closing handoff 或新 Agent。测试 `PASS`、Reviewer `READY`、原生 `Completed` 和机械 `DONE` 分别描述检查、评审、执行和任务记录，任何一项都不单独决定产品完成。人选 delegated、controller-direct 或 single-agent 时，Controller 都保留最终产品决策责任。每个必要依赖由一个观察 owner 负责；已经得到可靠结果就使用它，不重复等待完成或因状态未变化而反复唤醒模型。验证与等待服务于尚未解决的实际问题。

## 一个跨模块编码场景

假设用户要求为一个跨 API、队列与存储层的导出功能增加取消能力，同时保持旧请求兼容。以下是机制示例，不是产品测试或性能实验结果，也不是强制工作流。

1. Controller 明确取消语义、兼容边界与验收场景。Investigator 调查请求入口、队列状态转换和存储写入位置，返回带来源的调用关系、既有测试和未确认的竞态；搜索失败与原始日志留在调查工作集。
2. Controller 选择相关事实、硬不变量和未知项形成 Handoff。若取消、完成与写入互相耦合，Fresh Focused Implementer 围绕这些不变量实现并验证；方向稳定的独立修改可以交给普通 Implementer。
3. 实现者返回具体候选、来源版本、测试覆盖和未覆盖情形。核心语义收敛后，剩余确定性同步、回归或 Git 收尾可交给新的普通 Implementer，而不延长原聚焦上下文。
4. 如果独立挑战会影响验收，Fresh Reviewer 检查诸如「取消与完成同时发生」及旧 API 兼容等边界。未验证的运行时行为继续标记未知；审查发现带着依据返回，而不是自动视为结论。
5. Controller 整合实现报告、测试与可用的运行时证据，按原始目标和标准决定是否完成；未满足的条件或改变决策的未知项继续路由修复或有用的额外验证。若独立挑战能影响判断，可选择 Reviewer。Controller 再根据实际验收结论记录机械关闭。只有跨任务仍有价值的取消不变量或已验证 failure mode 才进入项目记忆；其余记录留在对应 Task ID 中。

源码、Git、测试、编译器和实际运行时行为仍然是正确性的依据。Thaliris 复用 Codex、DSH 的原生会话、Agent 与执行能力：它补充上下文选择、交接、记录与证据边界，不另造一套 Agent Runtime。

## Codex 的运行时契约与产品能力

Codex 的 Host 适配器，依赖共享 [Thaliris Core](https://github.com/Iris0fTheValley/Thaliris)，不是独立 Core，也不复制 Core。

`thaliris-codex` 发布 `thaliris_codex` 命名空间及 `thaliris` / `context` 命令。原生引导、角色配置、生命周期、Hook 信任、运行时身份、诊断和恢复由本适配器负责。共享记录、检索、证据、记忆与 authority API 来自 `thaliris`。

Codex 提供原生 Controller 会话、角色会话、工具和协作能力；adapter 将共享角色语义接入原生 profiles、选择性 Handoff、显式任务关联与 Hook 观察。Fresh Child 使用 V2 `fork_turns="none"` 或 V1 `fork_context=false`，只接收父级选定材料；原生执行终态与产品验收分开记录。

普通读取、修改、测试和 Git 工作与建立 Authority、切换执行模式、处置依赖等受管控制具有不同边界。缺失观察保持 `UNKNOWN`，不自动拒绝无关普通工作，也不授予高权限受管控制资格；已知只读限制、身份矛盾和用户内容保护继续有效。Host 安装与维护需要独立授权，源码或磁盘变化本身不证明当前进程已加载更新。

全局指令同时承载共享工作原则：复用选定证据，按工作依赖协调写入，用最小但有意义的检查验证行为，并让一个 owner 观察必要依赖。正常 Controller 指导由 Bootstrap 交付；异常恢复和 Host 维护按需检索。详细运行时协议见[集成说明](adapter/codex/README.md)，任务边界见[Authority 契约](docs/thaliris-task-authority.md)。

普通生成的角色 profile 故意省略 model 和 effort，因为 Codex 会在 spawn 参数之后应用 role model 配置。Controller 默认让 Investigator、Implementer、Curator、Verifier 使用 gpt-6-luna/max，让 Reviewer、Focused Implementer、Reasoning Specialist 使用 gpt-6.1-sol/high。每个 Thaliris 辅助任务（包括准备期）都要选注册的 Thaliris `agent_type`；通用原生角色名不属于 Thaliris 默认路由。PreToolUse 会在适用的隔离、readonly、fence、task-control、角色和 execution-constraint 检查后，为 exact 普通角色 profile 的省略或 `null` 字段补入默认值；只提供 effort 时补默认 model，只提供 model 时保留 Native 已配置或默认 effort。ACTIVE task 仍先经过现有 freshness、owner、delegation 和 authority 检查，再路由并 reserve；NO_TASK 或 inactive state 只更新 native spawn 参数，不创建 reservation 或 lifecycle binding。显式非空选择保留，空值或非字符串拒绝。路由前只读核验所选普通 target 在个人与项目 scope 的可观察绑定，以 TOML name 和 legacy config_file 引用识别身份；固定字段必须与显式或补齐字段一致，允许 model-free 用户编辑。冲突或不可验证时不改写用户文件，managed dispatch 不 reserve；有效优先级未证实或 target model/effort 不可验证时明确返回 UNKNOWN。磁盘核验不证明运行中的 Host 已加载哪个定义。Astra 仍需当前任务的人类 opt-in；静态 Astra 兼容 profile 保持固定绑定，luna-only 继续冻结并禁止 per-spawn 覆盖。受信任的隔离 Native run 在 `codex-cli 0.162.0-alpha.17.2` 验证了 `updatedInput`、四个 managed 角色/模型实际上下文、通用 Native passthrough，以及同名 profile 冲突的预留前拒绝；临时子会话也记录了 managed 只读 sandbox 和 lifecycle binding。该临时 candidate 不证明正式生产或桌面 Host 已激活；已安装 profile 仍可能是历史版本。见[原生选择优先级](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning)。

Codex 模型目录属于 Host 全局配置（`model_catalog_json`），与项目内角色 profile 分离。维护是显式、低频的同步：目录兼容依据所选来源的模型名单和内容校验，而非 CLI 版本白名单；Online 导出还会验证隔离 cache 的新鲜度、CLI 使用的完整 major.minor.patch 版本和模型身份；CLI 版本作为来源证据保留，预发布标签不属于 cache 版本。已知模板要求精确完整行及预期相邻行，新模型要求目标句恰好作为完整行出现。缺失、移动、改写、拆分、嵌入或重复均保留旧目录并报告不兼容。受管 receipt 显式声明目录能力，新 reader 兼容旧 receipt，并在成功的授权升级中迁移；旧 reader 遇到新格式会在写入前拒绝。降级时先用当前 reader 卸载，精确归档使之后的升级可在字段缺失且字节匹配时重新认领。用户修改可在继续其他已授权 Host 操作时保留，但目录目标会保持未达成。安装 contract 可明确指定项目丢失恢复位置；真实 Host `SessionStart` 仅在 marker、receipt 和目录摘要仍满足精确校验时移除受管配置字段，物理目录文件继续保留。已完成恢复 receipt 只支持一次重新认领，只有恢复过程实际移除了精确受管字段，receipt 才会记录一次重新认领所需的恢复证据。字段在恢复前已缺失且没有既有证据时，报告 `RECOVERY_PROVENANCE_UNKNOWN`，不会让用户删除或不确定的崩溃状态授权重新认领。成功重装后会清除该证据。磁盘配置、当前进程加载状态和此前启动的会话是不同状态；编辑或安装不证明当前 Host 已激活更新。详见[模型目录维护报告](docs/model-catalog-maintenance-report.md)。本次接受的事务边界是保留最终字节比较已观察到的用户修改并保留 catalog backing file；非协作 writer 仍可能在比较与 atomic replacement 之间并发修改。该剩余时间窗已公开说明，不是待决议事项。

## 安装与本地开发

### 常规：在 Codex 中请求维护

正常用户直接说“安装 Thaliris”“更新 Thaliris”“修复当前安装”或“检查当前状态”。root agent 负责读取本地状态、选择可信的精确 release、验证候选，并在本次用户维护意图下调用已验证 updater。用户不需要学习 manifest、digest、Core/Adapter 配对、wheel 或 maintenance contract。

支持本功能的 Hook 为一次明确 action 签发短期、单次消费 capability，绑定当前 session、最新观察到的 prompt epoch、Host/home、release input、updater 和原始 resume contract。child/delegated、readonly、fenced/abandoned 及不匹配、过期、重放调用被拒绝；instruction 字符串或命令拼写不能自行授权。该机制是模型选择加 Hook 机械约束，host_actor_assurance 仍为 UNKNOWN，不认证共享 OS 上的人类或万能 Controller。

已安装 updater 的本地只读入口无需 release 输入、联网或创建候选：

~~~powershell
thaliris-release status
~~~

指定可信 manifest/digest 时可额外比较 release。普通更新先完整重验已保存 candidate，只有 miss 才获取 wheels 和创建新 immutable runtime。所有 Host mutation 继续使用 exact contract、ownership 与 transition/recovery；用户修改默认保留。loaded Host/restart 无真实 native evidence 时仍为 UNKNOWN。

截至此源码状态，尚未发布本轮 release，也未验证其公开 attestation 或 native activation。自动可信 latest discovery 仍未实现，agent 必须使用独立可信的精确 release input；同源 checksum 不建立信任。旧版 Hook 的初次迁移仍走现有显式授权 exact-contract 路径。无需 Python 的安装器也未实现。

独立 thaliris-bootstrap.py 用于首次安装、updater 缺失或独立 recovery，依赖系统 Python 3.11+ 与预先可信的 bootstrap/release input；不承担普通 candidate-hit 路径，也不复制 runtime verifier。首次无受管安装时的显式 CLI 使用 --standalone-maintenance；它不能替代 integrated capability 或授权覆盖损坏的 ownership。完整 agent 协议、maintainer CLI 与恢复边界见[发行版生命周期](docs/release-lifecycle.md)。

### 高级：源码开发

源码开发与普通安装或更新分开。pyproject.toml 要求 Python >=3.11，并依赖 thaliris>=0.4.6,<0.5。默认 Core 配对只记录在 [release/core.lock.json](release/core.lock.json)；从该文件读取所选 commit，不要在 README 中复制另一份 revision：

~~~powershell
$coreCommit = (Get-Content release/core.lock.json -Raw | ConvertFrom-Json).commit
$coreCommit
~~~

准备好本地 Core 和 Adapter checkout 后，安装 Core 的 test extra 与 Adapter checkout，再指定 Core 源码目录并运行 Adapter 测试：

~~~sh
python -m pip install -e '../Thaliris[test]'
python -m pip install --no-deps -e '.[test]'
~~~

离线恢复 source-runner 测试要求 THALIRIS_CORE_SOURCE 指向包含 src/thaliris/core.py 的 Core checkout；runner 会明确加载该源码，而不把已安装 Core package 当作经过审阅的源码。PowerShell 中：

~~~powershell
$env:THALIRIS_CORE_SOURCE = (Resolve-Path '../Thaliris').Path
python -m pytest
~~~

POSIX shell 中，设置 THALIRIS_CORE_SOURCE=../Thaliris 后运行 python -m pytest。CI 的默认 Core 配对也从 release/core.lock.json 读取；手动触发的 workflow 可以选择其他 core_ref。源码和 Host 集成细节见 [Codex 集成说明](adapter/codex/README.md)及 [Host 维护说明](docs/thaliris-host-maintenance.md)。

源码测试和磁盘安装都不能证明当前 Host 已加载或信任这些文件。项目指令的 authority 和恢复契约见 [authority](docs/thaliris-task-authority.md) 与[运行时恢复](docs/thaliris-runtime-recovery.md)。

## 项目任务的启动与恢复

Host 安装后，除非用户明确选择不使用 Thaliris，实质性项目文件修改均由 owning Controller 使用已安装 pinned runner 对目标仓库运行一次 `codex-bootstrap`，包括 README-only、配置修改和新项目创建。聊天与只读工作不需要项目 Bootstrap。

显式指定的现有项目目录无需 Git 元数据即可 bootstrap 并准入受管任务；`codex-bootstrap` 不运行 `git init`。仅当创建仓库属于用户任务范围时才独立创建 Git 元数据。native cwd、managed project root 和 Git worktree root 是不同概念；既有 Git 根选择保持兼容。无 Git 时，HEAD 和 Git surface 观察局部不可用，Git evidence freshness 保持 `UNKNOWN`，任务 authority 与 lifecycle 仍可使用。这是单独的一次调用：

```powershell
& '<installed pinned runner>' --root '<repo>' codex-bootstrap
```

Bootstrap JSON 先序列化紧凑的工作区状态诊断，再序列化回执元数据与指导正文；即使输出截断，前面的诊断仍可读，但缺少 END 标记时不能确认 digest。完整 END 标记包含 SHA-256 与 UTF-8 字节数。仅当完整工具结果和 END 标记都可见时，才能在同一当前上下文为另一个仓库传入 `--controller-guidance-sha256 <digest>`，省略重复正文。该值是显式的内容回执提示，不是进程写出 stdout 的交付证明，也不写入持久会话状态；新 Session 与 Fresh Child 不沿用。若响应被截断或指导内容已更新，省略该参数即可重新取得完整内容；也可运行 `controller-instructions --resident` 恢复完整正常指导。

`READY`（旧版 `DEFINITION_READY_ACTOR_UNKNOWN` 也可继续处理）表示项目定义可用；它不认证 Host actor，也不证明角色配置已由当前进程加载。若项目定义缺失，先按 bootstrap 结果处理，而不要绕过 adapter 直接创建另一个任务账本。

任务准入使用单独的 UTF-8 JSON contract 文件，包含非空 `human_instruction`、`boundary`、`invariants`、`acceptance` 字符串，以及可选 `execution_mode`（`delegated`、`controller-direct` 或 `single-agent`）。未指定时默认 `delegated`：Controller 负责长期决策，短期 Investigator/Implementer 负责主要调查和实施。`controller-direct` 允许 Controller 自行读取、修改、测试、提交和结束工作，并可按需使用辅助角色；`single-agent` 表示不使用子代理的普通单 Agent 工作。明确用户选择优先于效率默认，但不能扩大任务范围，也不能突破角色只读限制或用户文件保护。

```json
{"human_instruction":"<actual user instruction>","boundary":"<selected scope>","invariants":"<hard constraints>","acceptance":"<acceptance conditions>","execution_mode":"delegated"}
```

创建该文件后，再用另一次独立调用开始任务：

```powershell
& '<installed pinned runner>' --root '<repo>' task-start '<goal>' --authority-contract '<absolute-contract-file>'
```

`delegated` 下，Controller 在任务边界内进行普通读取、Git 和诊断是合法的。默认建议将大量调查和实现委派给适当的新角色，按用途和工作集选择；文件、行数、token 和查询次数不是权限门槛。适合时使用有界检索，并保持隔离、只读及受保护管理边界。

显式 contract admission 不依赖 bootstrap receipt 或一次性 Hook bearer。若显式提供 legacy proof，adapter 仍严格验证它。contract 记录 Controller 选择的人类任务意图；Host Root actor assurance 仍为 `UNKNOWN`，这不是通用身份认证。已知 child、readonly、fenced、retired 或冲突状态不能建立或扩展 authority。普通 repo work 可依据精确原生 Agent-to-Task map 或 active handoff 中的已知 role；缺失 session、turn、profile 等非关键字段保持 `UNKNOWN`，不据此拒绝普通 work，也不授予 managed-control 资格。已提供的身份矛盾仍阻止依赖该证据的操作；即使 Authority 或可选字段不完整，已知 readonly role 仍拒绝 Bash/MCP mutation。

每个 Task ID 独立保存任务状态、Authority、lifecycle reservations、子代理绑定和恢复证据。`task-start` 创建并选中新的 Task ID；同一仓库中的旧任务仍为 `ACTIVE` 或 `UNKNOWN`，不会被继承或阻止新任务。恢复已有任务必须显式选择其 Task ID。当前 Codex session 也必须通过 `task-associate` 明确关联；该操作以 task ID、session ID 和 Authority revision/hash 建立导航，不证明 Host actor 身份，Host assurance 仍为 `UNKNOWN`。Hook 只使用当前 session/agent-task 的显式映射或精确 Task ID selector；仅仓库路径不足以确定当前任务。

默认执行模式是 `delegated`：长期 Controller 负责方向、范围、验收标准和后续路由，将开放式、广泛或连续调查交给 Investigator，并将稳定方向的实现交给 Implementer。Controller 在任务边界内的普通读取、Git 和诊断合法；按用途与工作集选择委派，不设数值权限门槛。用户明确选择 `controller-direct` 或 `single-agent` 时，执行选择优先于效率默认。任务范围、角色只读限制和用户内容保护继续有效。任务中的模式切换通过 `task-mode` 对已选 Task ID、Authority digest 和 revision 执行 CAS，只更新 `execution_mode`；未处置的工作依赖必须先通过明确的取消或放弃路径处理。

有效的 task-scoped ACTIVE anchor 可在 turn、网络或 Hook 中断后继续，不需重复证明 Root session 身份。缺少 contract、无 anchor 的历史 ACTIVE task、Authority 冲突或不可验证的 security bytes 仍会阻止依赖该 Authority 的受管控制操作；它们不应连带禁止与之无关的普通工作、读取和诊断。真实身份冲突、fenced/abandoned 子代理和只读角色限制仍然生效。先用有界 `task-status` 查看路由状态；完整 `task-show` 只用于明确诊断。原生 child 状态、Core/lifecycle 记录和 产品验收是分开的事实。

Authority 恢复必须通过显式 Task ID，或已经关联到该任务的 session 选择目标，并保留该任务的来源证据和受保护用户 bytes；它不能批准已变化的 security baseline，也不能移除已知旧 child 的 fence。`task-recover-state` 必须提供 `--task-id` 或已有映射的 `--session-id`。legacy state 只能通过显式诊断/恢复路径访问，不会自动 adopt；未选择的旧 bytes 保持不变。`UNKNOWN` 仍保持 UNKNOWN；Controller 可按有界路径结束或放弃旧任务并隔离迟到结果，无需伪造 child Completed。已知可能仍在写入共享文件时，仍需按实际冲突处理。Host 文件修改、安装记录或一次 bootstrap 都不证明当前 Codex 进程已加载更新。详细操作见 [task authority](docs/thaliris-task-authority.md) 和 [runtime recovery](docs/thaliris-runtime-recovery.md)。

任务进行中若用户明确切换执行方式，可通过 `thaliris --task-id <id> task-mode ...` 更新选定 Task ID 的执行模式；`--task-id` 是命令前的全局选择器，只选择任务，不授予权限。该操作要求当前 Authority digest 和任务 revision 的 CAS，并单独提供用户新指令；它只修改 `execution_mode`，不会重写目标、边界、不变量或验收。活动依赖可通过 `task-dispose-dependency` 在同一 Task ID 下明确放弃：命令要求当前 handoff ID、任务 revision、生命周期摘要和理由；它记录 `ABANDONED_DEPENDENCY` 与风险，不会伪造子代理终态，并隔离该 handoff 的迟到结果。若可能仍有共享文件写入，Controller 必须先处理该实际冲突。处置后可在同一任务内通过双 CAS 切换模式。当前 session 关联使用 `task-associate`，显式给出 Task ID、session ID 和预期 Authority digest；它只建立导航，不证明 Host actor 身份。`task-start` 也可接收当前 `--session-id` 以建立任务导航。

[共享文档](https://github.com/Iris0fTheValley/Thaliris/tree/main/docs)、[ABCD 基准结果](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md) 在主仓库；[DSH 兄弟适配器](https://github.com/Iris0fTheValley/Thaliris-dsh) 使用同一个 Core。

共享语义保持模型负责判断：INDEX 是由模型维护的薄语义导航地图，Core 只执行路径、CAS、大小与链接检查。Controller 选择要保留的知识，角色结果不会自动成为持久记忆。

历史迁移测试读取 `tests/fixtures/history/provenance.json` 指向的不可变 Git blob 原始字节，校验 blob ID 和 SHA-256，不把当前生成结果当成历史权属证据。

旧 admission-fix 提案的原始补丁与 profile 字节来源快照保存在[历史归档](docs/historical/admission-fix/README.md)；其中的 profile 内容变更拒绝行为不是当前启用契约。


## 执行约束

语义角色、职责、路由和只读限制与执行模型分离。专用 Codex 安装可通过 codex-install --execution-constraint luna-only 将所有普通 worker profile 设为 gpt-6-luna/xhigh，同时保留原角色 ID 和指令。任务 authority contract 必须显式包含：

```json
{"execution_constraint": "luna-only"}
```

Core 将该可选非空字符串作为不可变 intent 保存；适配器只接受 luna-only，并验证每个执行绑定。外部 anchor 固定已校验的 profile/config hashes，子角色与可变配置不能扩展或解除约束。安装后需要新的 Host session。Admission 比较 SessionStart 时记录的 role profile 和公开 config 文件快照；磁盘快照不能证明 Host 实际加载的 role map 或 CLI -c 覆盖。SubagentStart 核对受约束子角色的 Host model；缺失或不匹配时 handoff 不绑定，之后该子角色的工具会被拒绝，但 hook 无法阻止模型调用。约束禁止 Astra profile 和每次 spawn 的模型覆盖；该模式使用固定的 Luna/xhigh role profile。未启用约束时，七个默认路由的语义角色由 managed `PreToolUse` 补齐省略的 model/effort；只提供一个字段时按原生默认语义处理另一个，显式值不改写。执行约束或经验证的必要例外仍可选择其他受支持值。详细迁移说明见 [执行约束移植说明](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/docs/split-execution-constraint-port.md)。

该功能需要 thaliris>=0.4.6。开发测试必须安装本次修复所用的 Core checkout；旧 monolithic wheel 不满足 split package 边界。

## CI 与平台兼容范围

CI 矩阵覆盖 Ubuntu 和 Windows 上的 Python 3.11、3.12、3.13；默认 Core 配对从 [release/core.lock.json](release/core.lock.json) 读取，仅手动 workflow 可显式改选 core_ref。POSIX runtime identity 检查仅接受 `lib64 -> lib` 的精确虚拟环境别名，并验证目标漂移会被拒绝。Hook transport 只把一个文档起始 UTF-8 BOM 当作传输标记；重复/错位 BOM 与无效 UTF-8/JSON 仍拒绝。Hook 诊断只输出有界 JSON boundary label，不输出 payload，也不推断更深根因。CI 和源测试不证明某个当前安装的 Codex 进程已经加载这些内容。

## 运行时提示词层

全局指令保留共享授权/隔离边界与一次性启动入口；必要的 bootstrap 响应将正常 Controller 指导直接交付到任务上下文，包括启动/准入、路由、交接、证据复用、等待、Workstream 终点、验收/独立 review 选择、持久知识准入与因果诊断。完整结果用 BEGIN/END 标记；同一当前上下文只在完整工具结果和 END 标记可见后，才可对另一仓库显式传入该 digest 来省略重复指导，不记录持久会话状态。响应截断时可省略 digest 重获完整文本，或用 `controller-instructions --resident` 恢复。项目指令保留共享边界和 canonical 指针；完整 Controller routine 不注入每个 fresh child。[Controller 操作程序](docs/thaliris-controller.md) 是权威源；异常恢复、Host 维护按需检索。安装的 pinned runner 的 `controller-instructions` 返回程序索引，`controller-instructions --resident` 返回完整正常指导，`controller-instructions --section <name>` 获取精确章节。评价完整正常任务上下文、检索成本与交付质量，而非单个最短 prompt。原生角色提示词负责当前角色的执行风格、委派和终点；新鲜 handoff 不向子角色批量注入无关 Controller 程序。所有角色仍可在自身权限内按需检索规则。设计理由与机械实现见 [Codex 协议](adapter/codex/README.md)与 [Core 提示词设计](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-prompt-design.md)。

先继续应优先处理的独立工作，再判断必要依赖是否需要等待。规则适用于所有授权委派层，包括 Implementer、Focused Implementer 或 Reviewer 等待 Investigator Scanner。每层只观察自己的直接依赖；执行角色负责观察自己发起的测试、构建、process 与 CI，并用对应工具的真实等待能力。父代理只等待尚未结束且结果必要的直接 child，同时没有其他应优先处理的工作。完整交接后 child 自主推进，不需要父级反复 patrol；执行中的 child 只报告完成、关键阻碍、会改变决策的新发现或必要的上层决策。child 返回 FINAL 或 decision-changing unknown 后，该 slice 结束，不继续等待。

事件驱动等待优先。先确认当前 Host 的工具上限、实质事件提前返回、用户中断与 child 通知能力；未经确认的能力保持 UNKNOWN。若事件提前返回和用户中断已确认，且无需中途决策，通常使用工具支持的 60 分钟窗口（`timeout_ms=3600000`）；这是最大等待窗口，实质事件可提前唤醒并直接使用结果。只有确需阶段检查或早返不可靠时才考虑较短窗口：极短任务约 60 秒、普通任务按规模 10–60 分钟、较长任务阶段检查约 30 分钟。这些是按情境选择的建议，不是硬性上限。遵守实际工具上限和明确适用的更高层时限，不修改或绕过 Host 来延长它。

原生终止事件、普通 child 消息、timeout、异常和 UNKNOWN 是不同证据；消息和 timeout 不证明完成，异常不伪造终止证据。不要用 sleep、patrol、进度轮询器或每个 child 的定时循环反复观察未变化状态。超时后先重新判断必要直接依赖与可继续的独立工作；wake-only 的 V2 `wait_agent` 只需一次可用的精确原生状态检查（如 `list_agents`），已经证明完成无需二次确认。Hook 保留调用者等待参数，不自动延长或接管 timeout。不同 Task ID 可独立并行；同一 Task ID 中已绑定 child 可并行，但一次只保留一个待关联预约。Controller 按工作依赖决定并行，同一工作树内的重叠写入需协调，独立 worktree 可承载独立修改。

Hook 失败在 stderr 输出有界 JSON，区分 receive、严格 decode、JSON syntax/shape、dispatch、maintenance-contract 与 runtime-identity 的真实边界。诊断不含 payload 或异常内容，不证明更深根因，也不改变拒绝/身份检查。Hook 文档只接受一个起始 UTF-8 BOM 的边界保持不变。Reviewer `READY` 描述选定范围内的只读挑战；Controller 将其与原目标、标准和其他证据结合，决定产品是否完成。

Controller 提供决策完备且经过选择的交接；实现方法由执行角色决定。普通 Implementer 负责稳定方向下的工作和确定性收敛。面对相互耦合的不变量时，Focused Implementer 负责完整的推理、实现、运行时反馈和修订循环；当聚焦证据支持核心语义，且剩余任务不会改变决策依据时，它返回 FINAL 并释放该工作上下文。
新的普通 Implementer 负责剩余回归、构建与同步、确定性缺陷、安装和 Git 收尾。通用执行说明不会延长 Focused Implementer 的语义终点。Reviewer 是新建的独立只读角色；READY 需要支持关键验收的证据，不能仅因没有发现阻塞项就判为 READY。Core 和 lifecycle 的观察结果不决定验收。
V1 wait_agent 的 status map 使用已生成 agent 的精确 ID，V2 list_agents 使用 canonical task name；不要求切换 V2 或重复确认已证明的完成。受支持的 Completed 证据为精确的单键 `{"completed": <string or null>}`；null 表示执行终止但不提供结果文字，也不决定语义验收。其他值类型和不支持的形状保持 UNKNOWN。原生执行终止、产品完成决策和任务取消/放弃是分开的事实；Controller 结合原始目标、验收标准和所有可用证据，决定修复、补充验证或记录机械关闭。迟到结果不能重新进入已终止的任务；已知共享文件写入风险仍需处理。SubagentStop 是可选观察，缺失或延迟不推翻其他已支持证据。矛盾或身份冲突只限制依赖该证据的操作；它们不会把无关普通工作一并拒绝。Host 原生身份字段在 SubagentStart 与 PreToolUse 之间的真实稳定性仍为 UNKNOWN；合成测试不证明 Host 协议。

`thaliris_codex.roles` 是原生 profile 生成的规范来源。精确历史哈希用于安全升级；用户编辑过的字节和项目内 profile shadow 继续按 fail-closed 方式处理。[角色 profile 文档](docs/thaliris-role-packs.md)由源文件生成。源码变更不能证明运行中的 Host 已激活这些内容；父级任务处于 ACTIVE 时也不会在此安装。下方 ABCD 结果仍是历史证据；本次提示词规范化没有基准测试结论。

历史原生 Agent 树可按需离线审计；该只读工具不接入 Hooks 或运行时状态。[审计用法和注释格式](docs/agent-tree-audit.md)。

## ABCD 基准测试结果

我们运行了一项受控的单任务基准测试，以区分**模型能力**、**编排**和**异构智能分配**。A/B/C 使用相同任务、BASE 修订、Codex 版本、隔离的工作区/CODEX_HOME 和环境；D 是此前封存的生产架构运行，没有重新运行。

四个已完成的实验组检验两个主要假设：

**编排收益 — B → C：** 对 Luna-only 系统而言，角色拆分和隔离的多 Agent 执行是否比单个 Luna Agent 更好？

**智能分配收益 — C → D：** 已有编排后，在语义实现、评审和收尾环节有选择地使用更强模型，是否会实质改善结果？

### 结果

| 实验组 | 配置 | 覆盖度 | 正确性 | 兼容性 | 实现 | 验证 | 均值 | 完成情况 | 墙钟时间 | 成本代理值 |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| **A** | Sol medium，单 Agent | 6 | 4 | 6 | 6 | 7 | **5.8** | 部分 | **21m36s** | **$0.883** |
| **B** | Luna xhigh，单 Agent | 6 | 5 | 6 | 6 | 4 | **5.4** | 部分 | **54m09s** | **$0.232–0.235** |
| **C** | Thaliris，Luna-only | 4 | 6 | 7 | 6 | 4 | **5.4** | Managed DONE / 产品部分完成 | **41m11s** | **$0.272** |
| **D** | Thaliris，异构路由 | **9** | **8** | **8** | **8.5** | **8** | **8.3** | 基本完成；仍有一个 P2 | **64m47s** | **$2.475** |
| **E?** | D 拓扑，**全 Sol 工作节点** | **9?** | **8?** | **8?** | **8.5?** | **8?** | **8.3?** | 类似 D？ | **64m47s?** | **~$3.67 预测** |
| **F?** | D + **语义收敛切换** | **9?** | **8?** | **8?** | **8.5?** | **8?** | **8.3?** | 类似 D？ | **64m47s?** | **~$2.06–2.07 预测** |

A/B/C 的独立评分、运行时间和成本测量来自新一轮基准评估。D 最初封存的评估将五个维度都评为 GOOD；上表 8.3/10 是后来用 A/B/C 评分标准对同一个冻结候选做的只读重评。D 的原始运行仍保持封存且未修改。它的生产路由为 Luna Investigator → Sol Focused Implementer → Sol Reviewer → Luna repair → Sol Reviewer → Luna repair。

### Token 结构

cached input 是 input 的子集，不是额外 token。

| 实验组 | 输入 | 缓存 | 新鲜输入 | 输出 | 推理输出 | 模型分布 |
|---|---:|---:|---:|---:|---:|---|
| **A** | **3.104M** | 2.962M | 0.142M | 30.3k | 7.1k | 100% Sol medium |
| **B** | **16.70M** | 16.39M | 0.309M | 79.8k | 46.8k | 100% Luna xhigh |
| **C** | **15.73M** | 15.03M | 0.695M | 105.0k | 66.3k | 100% Luna xhigh |
| **D** | **15.22M** | 14.51M | 0.706M | 108.2k | 44.2k | Sol：9.96M 输入 / 64.3k 输出；Luna：5.26M / 43.9k |
| **E? 全 Sol** | **~15.22M?** | ~14.51M? | ~0.706M? | **~80.9k 预测** | ? | 相同 D 拓扑，Luna 节点替换为 Sol |
| **F? 语义切换** | **~14.05–14.65M 预测** | ? | ? | **~100.9–108.9k 预测** | ? | Sol ~8.09M 输入；Luna ~5.96–6.56M |

D 的实际用量为 15.219M 输入，其中 14.513M 为缓存。Luna 消耗 5.260M 输入 / 43.9k 输出；Sol 消耗 9.959M 输入 / 64.3k 输出。

### 各实验组的表现

| 实验组 | 优点 | 主要弱点 |
|---|---|---|
| **A — Sol 单 Agent** | 运行最快；实现能力强，并自行生成了广泛的验证。 | 单条执行轨迹形成了连贯但不完整的语义模型。测试大多验证了自身假设，遗漏跨表面的所有权、重放和关闭缺陷。 |
| **B — Luna 单 Agent** | 成本极低。投入更多计算和时间后，Luna 的总分几乎与 A 相同。 | 输入量约为 A 的 5.4 倍，墙钟时间约为 2.5 倍；全局语义收敛和验证较弱。大量计算仍未消除生命周期/authority 缺口。 |
| **C — Luna 编排** | 角色分工清楚，managed lifecycle 完整；比 B 快约 13 分钟，正确性/兼容性略好。 | **总质量没有比 B 提升。** 覆盖度从 6 降到 4。Treatment review 错误地判定可以关闭，managed task 已到 DONE，但产品验收仍未完成。 |
| **D — Thaliris 异构模型** | 这是唯一实现了显著更高完成度的配置。独立评审 → 修复 → 再评审确实改变了候选并关闭了缺陷。 | 在已观测实验组中耗时和成本最高。Sol 累积了大量缓存上下文重放；之后仍有一个 P2 presentation-lifecycle 缺陷，真实 GPU/audio/UI 行为也未验证。 |

A/B/C 各自的主要独立缺陷记录在评估材料中：它们分别实现了不同的部分正确方案，并非都以完全相同的方式失败。

### 假设 1 — 编排收益

**方法：** 在实际执行能力固定为 Luna xhigh 时比较 **B 与 C**。B 是单个 Luna Agent；C 使用 Thaliris 角色、隔离的子 Agent 上下文和 managed lifecycle，但所有已观测工作节点都是 Luna xhigh。

**观测结果：**

5.4 → 5.4

没有观察到产品质量提升。C 快了约 **13 分钟**，总 token 略少，但因为未缓存输入更多，估算成本**高约 16–18%**。质量分布发生变化，却没有总体改善：覆盖度 −2，正确性 +1，兼容性 +1。<br>

**结论：** 在这个样本中，单靠编排没有实质增强较弱模型。它展示了工作流/lifecycle 和吞吐量方面的好处，但没有提高总质量。

### 假设 2 — 智能分配收益

**方法：** 比较 **C 与 D**。两者都使用 Thaliris 编排；D 有选择地将 Sol 分配给 Controller、核心语义实现和独立评审，同时保留 Luna 处理调查和有界修复。

**观测结果：**

5.4 → 8.3

评分变化最大的维度为：

覆盖度：4 → 9（+5）<br>
验证：4 → 8（+4）<br>
实现：6 → 8.5（+2.5）<br>
正确性：6 → 8（+2）<br>
兼容性：7 → 8（+1）<br>

D 的成本约为 C 的 **9.1 倍**，时间约为 **1.57 倍**，但它是唯一显著越过产品完成门槛的实验组。D 没有并行执行；主要可观测机制是反复的 **Reviewer → 有界修复 → 再评审**，而不是 Agent 数量或并行计算。

**结论：** 结果支持的是**选择性智能分配**，而不是“Agent 越多越好”。

### 接下来要验证的两个成本假设

以下 E/F 都是对已观察 D 路由的成本假设，不是当前任务的强制角色顺序；F 中 Reviewer 的语义验收职责只属于该反事实估算。当前产品完成由 Controller 根据原目标、验收标准和可用证据决定，Reviewer 仍是可选的独立挑战。

**E — 全 Sol 反事实。** 保持 D 的任务、拓扑、角色顺序和 lifecycle 不变，仅把 Luna Investigator/Implementer 节点替换成 Sol。输入/上下文重放量近似不变；仅按 A/B 输出效率比（79.8k / 30.3k ≈ 2.64×）调整输出。这预测全 Sol 的 D 型运行成本约为 **$3.67**，相对于**观测到的 $2.475**，若保持 D 级质量，异构执行约可节省 **32.6%**。不做输出效率调整时，简单的同 token 估算约为 **$3.94**。这仍是反事实，尚未运行。

**F — 语义收敛切换（反事实，未运行）。** 保留 D 的架构和高能力语义节点，但在 Sol Focused Implementer 建立核心实现和硬不变量后结束其执行。广泛测试、构建/lint 收尾、确定性的兼容问题和小修复交给新的 Luna Implementer；该假设路线把新的 Sol Reviewer 用作独立语义挑战，但这不意味着当前任务必须安排 Reviewer 或单独的 closing 角色。基于 trace 的估算移除约 **1.87M Sol 输入 / 15.3k Sol 输出**，增加约 **0.7–1.3M Luna 输入 / 8–16k 输出**，预测成本为 **~$2.06–2.07**，比 D 低约 **16–17%**，目标是同样的 8.3 水平。实际测试前，质量仍明确未知。

### 结语

当前基准支持一个比“多 Agent 更好”更窄的结论：

> **弱模型编排本身没有改善总质量；在历史 D 样本中，把更强智能有选择地放在语义实现和独立挑战环节，确实带来了提升。这是基准观察，不规定新任务必须设置 Reviewer 或单独的 closing 角色。**

目前已经修正为了缩短昂贵上下文的生命周期。高能力模型应继续用于执行期间确实需要其推理的工作；语义方案收敛后，可以把确定性的收尾交给成本更低的新工作节点，避免反复重放庞大的 Sol 上下文。
但我没钱继续跑基准测试了

## Benchmark 边界

`benchmarks/abcd/` 可以包含复杂 collector、formal authority 与离线评分。
Production `thaliris` package 不依赖 D11、formal registry、capture authority 或
benchmark receipt issuer。Benchmark 观察 production；它不定义 production 架构。

完整契约见 [DESIGN.md](DESIGN.md) 与
[docs/thaliris-routing-protocol.md](docs/thaliris-routing-protocol.md)。

## README 维护

共享语义和完整 ABCD 结果以 [Thaliris Core 中文 README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md)与[英文 README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.en.md)为准。三个仓库均保留完整共享项目叙事；共享内容变更应同步各仓库的两种语言版本，运行时能力和限制则以各自 adapter 契约为准。
