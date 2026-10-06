# Thaliris Codex adapter

语言：简体中文 | [English](README.en.md)

Codex 的 Host 适配器，依赖共享 [Thaliris Core](https://github.com/Iris0fTheValley/Thaliris)，不是独立 Core，也不复制 Core。

`thaliris-codex` 发布 `thaliris_codex` 命名空间及 `thaliris` / `context` 命令。原生引导、角色配置、生命周期、Hook 信任、运行时身份、诊断和恢复由本适配器负责。共享记录、检索、证据、记忆与 authority API 来自 `thaliris`。

pyproject.toml 声明 Python >=3.11，并依赖 thaliris>=0.4.3,<0.5。

Windows Python 3.11+ 的正常安装先创建临时 bootstrap 环境，再使用包内的
runtime installer。请独立选择已审阅的 adapter 完整 commit 和新的最终物理 runtime
目录；打包版 Codex 直接使用其 LocalCache runtime base：

```powershell
py -3.11 -m venv .thaliris-bootstrap
$bootstrap = (Resolve-Path .thaliris-bootstrap\Scripts\python.exe).Path
$adapterSource = 'git+https://github.com/Iris0fTheValley/Thaliris-codex.git@<reviewed-full-40-character-commit>'
& $bootstrap -m pip install --no-deps $adapterSource
$env:PYTHONDONTWRITEBYTECODE = '1'
$finalRuntime = "$env:USERPROFILE\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Thaliris\runtimes\codex-<reviewed-revision>"
$runtime = (& $bootstrap -m thaliris_codex.runtime_setup --runtime $finalRuntime --core-source 'git+https://github.com/Iris0fTheValley/Thaliris.git@575652df9d1ebc45c6aa51609db67945e40e6c44' --adapter-source $adapterSource | ConvertFrom-Json)
if (-not $runtime.ok) { throw $runtime.error }
$exe = $runtime.executable
& $exe version
```

请将 adapter commit 占位符替换为独立审阅的已发布不可变版本。Host 维护使用 `codex-maintenance-plan` 和明确的 `--maintenance-contract FILE`，不依赖项目 init/task admission。原始授权安装记录证明 bytes ownership；候选内容相同不证明 ownership。未知项目 role 文档保留且不单独阻止 admission，真正控制指令冲突仍阻止。受支持的卸载和正常重装保留用户配置及恢复证据。公共流程和 legacy 批准边界见 [Host 维护](docs/thaliris-host-maintenance.md)。


setup 在创建 venv、安装包之前，通过 OS handle 观察最终物理目录；输入发生重定向时
停止并报告应选择的路径。位置 anchor 与 Windows launcher 内嵌的 interpreter 必须
绑定同一目录。setup 使用普通最终路径 `thaliris.exe runtime-check`，禁用 bytecode
写入并验证实际 interpreter；维护选择在生成 contract 前重复该无副作用检查。
准备、contract 和最终 Host 安装使用同一目录。禁止复制、移动或重命名已安装 venv；
旧 interpreter 仍存在时，重算 manifest 也不能批准 relocation。保留失败候选，
另选正确最终目录重新创建。

本地开发使用已审阅的 Core checkout：

```sh
python -m pip install -e '../Thaliris[test]'
python -m pip install --no-deps -e '.[test]'
```

离线恢复 source-runner 测试需要设置 THALIRIS_CORE_SOURCE，指向包含
src/thaliris/core.py 的 Core checkout 根目录。runner 会明确加载该源码 checkout，
不会把已安装的 Core package 当作已审阅源码。PowerShell 中，在运行测试前设置：

```powershell
$env:THALIRIS_CORE_SOURCE = (Resolve-Path '../Thaliris').Path
pytest
```

POSIX shell 中，先设置 THALIRIS_CORE_SOURCE=../Thaliris，再运行 pytest。
CI 将该变量指向 shared-core checkout。

安装不等于 Host 启用或信任。参见 [集成说明](adapter/codex/README.md)、[authority](docs/thaliris-task-authority.md) 与 [恢复](docs/thaliris-runtime-recovery.md)。installer 创建不含 ensurepip 的专用环境，再通过 bootstrap 的 pip 安装两个已选择的包；pip、setuptools 和构建依赖留在 runtime 之外，无需手工修复 `.pth`。system site packages 禁用，可执行或扩展导入路径的 `.pth` 仍无例外地拒绝。也支持 `absolute-wheel-path#sha256=<reviewed-digest>` 形式的已校验本地 wheel。整个环境的文件（含共享 Core）被纳入 manifest；固定目录保持不可变，升级使用新的 runtime 目录。

[共享文档](https://github.com/Iris0fTheValley/Thaliris/tree/main/docs)、[ABCD 基准结果](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md) 在主仓库；[DSH 兄弟适配器](https://github.com/Iris0fTheValley/Thaliris-dsh) 使用同一个 Core。

共享语义保持模型负责判断：INDEX 是由模型维护的薄语义导航地图，Core 只执行路径、CAS、大小与链接检查。Controller 选择要保留的知识，角色结果不会自动成为持久记忆。

历史迁移测试读取 `tests/fixtures/history/provenance.json` 指向的不可变 Git blob 原始字节，校验 blob ID 和 SHA-256，不把当前生成结果当成历史权属证据。

旧 admission-fix 提案的原始补丁与 profile 字节来源快照保存在[历史归档](docs/historical/admission-fix/README.md)；其中的 profile 内容变更拒绝行为不是当前启用契约。


## 执行约束

语义角色、职责、路由和只读限制与执行模型分离。专用 Codex 安装可通过 codex-install --execution-constraint luna-only 将所有普通 worker profile 设为 gpt-6-luna/xhigh，同时保留原角色 ID 和指令。任务 authority contract 必须显式包含：

```json
{"execution_constraint": "luna-only"}
```

Core 将该可选非空字符串作为不可变 intent 保存；适配器只接受 luna-only，并验证每个执行绑定。外部 anchor 固定已校验的 profile/config hashes，子角色与可变配置不能扩展或解除约束。安装后需要新的 Host session。Admission 比较 SessionStart 时记录的 role profile 和公开 config 文件快照；磁盘快照不能证明 Host 实际加载的 role map 或 CLI -c 覆盖。SubagentStart 核对受约束子角色的 Host model；缺失或不匹配时 handoff 不绑定，之后该子角色的工具会被拒绝，但 hook 无法阻止模型调用。约束禁止 Astra profile 和每次 spawn 的模型覆盖；未启用约束时默认绑定不变。详细迁移说明见 [执行约束移植说明](https://github.com/Iris0fTheValley/Thaliris-codex/blob/main/docs/split-execution-constraint-port.md)。

该功能需要 thaliris>=0.4.3。开发测试必须安装本次修复所用的 Core checkout；旧 monolithic wheel 不满足 split package 边界。

## 运行时提示词层

全局指令负责启动、授权与安全以及恢复。项目路由指令负责 Controller 的方向、范围、验收、角色选择和 Workstream 收尾。原生生成的角色提示词负责执行风格、委派方式和角色终点。每项不变量在常规运行时只有一个权威来源；设计理由和机械实现见[Codex 协议](adapter/codex/README.md)与[Core 提示词设计](https://github.com/Iris0fTheValley/Thaliris/blob/main/docs/thaliris-prompt-design.md)。

Controller 提供决策完备且经过选择的交接；实现方法由执行角色决定。普通 Implementer 负责稳定方向下的工作和确定性收敛。面对相互耦合的不变量时，Focused Implementer 负责完整的推理、实现、运行时反馈和修订循环；当聚焦证据支持核心语义，且剩余任务不会改变决策依据时，它返回 FINAL 并释放该工作上下文。
新的普通 Implementer 负责剩余回归、构建与同步、确定性缺陷、安装和 Git 收尾。通用执行说明不会延长 Focused Implementer 的语义终点。Reviewer 是新建的独立只读角色；READY 需要支持关键验收的证据，不能仅因没有发现阻塞项就判为 READY。Core 和 lifecycle 的观察结果不决定验收。

`thaliris_codex.roles` 是原生 profile 生成的规范来源。精确历史哈希用于安全升级；用户编辑过的字节和项目内 profile shadow 继续按 fail-closed 方式处理。[角色 profile 文档](docs/thaliris-role-packs.md)由源文件生成。源码变更不能证明运行中的 Host 已激活这些内容；父级任务处于 ACTIVE 时也不会在此安装。下方 ABCD 结果仍是历史证据；本次提示词规范化没有基准测试结论。

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

**E — 全 Sol 反事实。** 保持 D 的任务、拓扑、角色顺序和 lifecycle 不变，仅把 Luna Investigator/Implementer 节点替换成 Sol。输入/上下文重放量近似不变；仅按 A/B 输出效率比（79.8k / 30.3k ≈ 2.64×）调整输出。这预测全 Sol 的 D 型运行成本约为 **$3.67**，相对于**观测到的 $2.475**，若保持 D 级质量，异构执行约可节省 **32.6%**。不做输出效率调整时，简单的同 token 估算约为 **$3.94**。这仍是反事实，尚未运行。

**F — 语义收敛切换。** 保留 D 的架构和高能力语义节点，但在 Sol Focused Implementer 建立核心实现和硬不变量后结束其执行。广泛测试、构建/lint 收尾、确定性的兼容问题和小修复交给新的 Luna Implementer；新的 Sol Reviewer 仍负责语义验收。基于 trace 的估算移除约 **1.87M Sol 输入 / 15.3k Sol 输出**，增加约 **0.7–1.3M Luna 输入 / 8–16k 输出**，预测成本为 **~$2.06–2.07**，比 D 低约 **16–17%**，目标是同样的 8.3 水平。实际测试前，质量仍明确未知。

### 结语

当前基准支持一个比“多 Agent 更好”更窄的结论：

> **弱模型编排本身没有改善总质量。把更强智能有选择地放在语义实现、评审和收尾环节，确实带来了提升。**

目前已经修正为了缩短昂贵上下文的生命周期。高能力模型应继续用于执行期间确实需要其推理的工作；语义方案收敛后，可以把确定性的收尾交给成本更低的新工作节点，避免反复重放庞大的 Sol 上下文。
但我没钱继续跑基准测试了

## Benchmark 边界

`benchmarks/abcd/` 可以包含复杂 collector、formal authority 与离线评分。
Production `thaliris` package 不依赖 D11、formal registry、capture authority 或
benchmark receipt issuer。Benchmark 观察 production；它不定义 production 架构。

完整契约见 [DESIGN.md](DESIGN.md) 与
[docs/thaliris-routing-protocol.md](docs/thaliris-routing-protocol.md)。

## README 维护

共享说明和完整 ABCD 结果以 [Thaliris Core 中文 README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.md)与[英文 README](https://github.com/Iris0fTheValley/Thaliris/blob/main/README.en.md)为准。本仓库只记录 Codex 特有的功能、依赖和限制；共同内容变更应同步 Core 两种语言版本，并保持本仓库中英文 README 对齐。
