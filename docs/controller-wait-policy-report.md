# Controller 等待策略收尾报告

## 2026-10-12 恢复说明

本节记录本次恢复；下文是此前候选的历史报告，其测试及 CI 结论不代表本次候选。当前指导保持分层事件等待：先处理独立工作；只等待仍未完成且结果必要的直接依赖；先确认当前 Host 的实际上限、实质事件提前返回、用户中断和 child 通知，未经确认保持 `UNKNOWN`。这些能力已确认且没有中途决策时，默认使用工具支持的 60 分钟窗口（`timeout_ms=3600000`），原生实质事件提前唤醒就直接使用结果。只有确需阶段检查或提前返回不可靠时才缩短窗口：极短任务约 60 秒，普通任务 10–60 分钟，较长任务阶段检查约 30 分钟。这些是按情境选择的建议，不是硬性上限；60 分钟是最大等待窗口，不是执行期限，也不因历史平均时长而提前截断。

Controller 继续掌握用户目标、范围、硬不变量和验收依据；完整交接后，受派角色拥有所分配工作的调查或实现方法，并在自己的工作集内持续推进。父层仅观察直接依赖，不重复巡查子代理或替它观察测试、构建、CI 和进程。子代理只回报完成、关键阻碍、会改变决策的新发现或必须由上层作出的决策；其他过程细节留在负责该工作的上下文。普通消息、timeout 和异常都不能代替完成证据；timeout 后先重新评估依赖和独立工作。wake-only 结果只做一次可用的精确原生状态检查，已证明完成无需再确认。

本次恢复仅调整指导文本和对应文档。没有实现 timeout 接管、自动延长、定时 patrol 或 Host 内部等待机制。`wait_agent` 与工作进程行为是否由实际安装的 Host 加载并按此响应，仍需新的运行观察；磁盘和提示词测试不能证明该状态。原报告后续的验证和 CI 只对应此前候选，不覆盖本次恢复。

## 本次候选验证与边界

将 `PYTHONPATH` 指向当前 Adapter 与 Core 的 `src`，`THALIRIS_CORE_SOURCE` 指向当前 Core，并设置 `THALIRIS_RUN_CODEX_RUNTIME_TESTS=1` 后运行 `py -3.11 -m pytest`：1196 passed、9 skipped，退出码 0，耗时 1125.89 秒。Controller 等待指导的生成/README 一致性断言包含在该测试集中。`tools/sync_instruction_sources.py --check --core-routing-root <Core>` 输出 `instruction artifacts: current`；缓存和未缓存差异的 `git diff --check` 均通过。模型目录 runtime capture 的范围与限制见[模型目录维护报告](model-catalog-maintenance-report.md)。

这些检查验证当前工作树与隔离 runtime fixture，不证明真实安装的 Codex Host 已加载新等待指导，也不证明所有 Host 版本的完成事件唤醒行为。本次未安装或维护 live Host；相关 activation 仍为 `UNKNOWN`。

以下各节记录此前长等待窗口候选的独立收尾证据，仅适用于该历史候选。它们的测试、工具观察和 CI 不能替代对本次恢复候选的验证，也不证明真实已安装 Host 已加载任一版新指导。

## 历史候选修改与优先级

- 权威源 `src/thaliris_codex/controller_instructions.md` 和安装器的 `src/thaliris_codex/wait_guidance_config.py::GUIDANCE` 均先要求确认当前 Host 的实际上限、事件提前返回、中断与通知能力。未经确认保持 UNKNOWN。
- 先继续应当优先处理的独立工作，再判断是否等待；只等待尚未结束且结果必要的直接 child，且没有其他更高优先级工作。每个授权父层只观察自己的直接依赖，包括执行员或 Reviewer 等待 Scanner。
- 已确认实质事件可提前返回与用户中断、且没有中途依赖决策时，默认使用实际支持的 `timeout_ms=3600000`。60 分钟是最大等待窗口，不是子代理执行时长要求；历史短平均时长不强迫提前唤醒。
- 只有实际需要阶段检查或提前返回不可靠时，才采用极短任务 60 秒、普通任务 10–60 分钟、较长任务约 30 分钟阶段窗口的推荐值。事件可靠且没有阶段决策仍优先 60 分钟。
- 实际工具限制、明确适用的更高层时限、用户中断、恢复与紧急决策优先。短工具上限不通过修改 Host 延长。
- 原生终止证据、普通子代理消息、超时、异常和 UNKNOWN 分别处理。消息或超时不证明结束，异常不伪造终止；wake-only 返回后只做一次可用的精确原生状态检查。已经证明完成不重复确认。超时后先重新判断必要直接依赖和可继续的独立工作，避免无限无意义等待。
- 不使用 sleep 替代原生等待，不新增进度轮询器、每子代理定时循环或未变化状态的反复推理。并行时等待能改变当前决策的事件。子代理持续执行，只报告完成、关键阻碍、重大发现或必要上层决策，不因时间经过发心跳。
- 既不普遍固定 60 秒，也不普遍固定 60 分钟。执行员继续负责本地测试、构建、CI 和外部进程，使用对应工具的真实等待能力，不套用 wait_agent 参数；独立收尾负责最终验收。

旧的“工具最大值永不作为默认值”及普遍固定短等待暗示已经从相关 Controller 和执行角色指导及文档移除。`roles.py` 的共享等待指导传递到全部原生 child profiles 和 role packs；`docs/thaliris-controller.md` 按现有同步机制生成；中文与英文 README、`adapter/codex/README.md` 同步相同条件与例外。Hook 仍保留调用者等待参数，未新增调度或自动延长机制。

## 历史候选验证证据

执行员在明确使用当前 Adapter/Core 源码导入路径的环境完成 83 项针对性检查：30 项等待配置测试、33 项提示词契约测试、20 项相关生命周期测试；随后新增生成及文档一致性检查通过，合计 84 项。同步检查与 `git diff --check` 通过。收尾复用这些有效结果，另独立核对候选差异、相关等待文字与 ownership 路径，并运行以下两项检查，通过；它们是已有覆盖的复核，不另计为新增独立场景：

```text
python -m pytest -q tests/test_prompt_contract.py::test_controller_wait_policy_reaches_generated_and_documented_surfaces tests/test_wait_guidance_config.py::test_guidance_matches_the_accepted_waiting_priorities
```

运行时应将 `PYTHONPATH` 指向当前 Adapter `src` 及当前 Core `src`，并将 `THALIRIS_CORE_SOURCE` 指向当前 Core 工作树；不能误用其他工作区的旧包。上述检查的 Windows 输出为两项通过、退出码 0；系统依赖发出既有 RequestsDependencyWarning，没有测试失败。

用户补充要求后的最终合并候选由执行员完成 142 项针对性整合检查；最后新增历史 GUIDANCE hash 断言后，12 项新等待契约检查再次全部通过。它们与前一里程碑 84 项分别记录，不能机械相加当作不同场景。同步 `--check` 与差异检查通过。收尾独立读取全部相关源差异和新测试，并将历史 `roles.py`、role packs fixture 的字节与 `41157f5` 实际 Git 对象核对，确认来源并非当前输出自证。所有原生 child 角色共享等待条件一致，Controller 生成结果与权威渲染精确一致。没有机械重跑全部测试。

关键覆盖包括：

- V1 完成 fixture 使用 `timeout_ms=3600000`，精确已绑定原生完成证据直接结束执行观察，不要求另一次 list/stop。
- 普通子代理进度消息、运行状态加超时、空状态加超时不能成为终止证明；这些是合成响应测试，没有真实等待 60 分钟制造超时。
- 权威 Controller 渲染与生成文件精确一致，所有相关文档具有新默认窗口及 UNKNOWN 边界，旧的相反默认文字不再出现。
- 测试使用真实旧版 GUIDANCE 文案的 ownership receipt，覆盖直接卸载、升级后卸载及用户改动保留；原有可选配置失败保护保持覆盖。receipt 校验和配置写入流程未改动。
- 最终候选为变更前 `41157f5` 的 default/luna-only 共 22 项角色输出及 role packs 添加精确历史 ownership hash。保留 renderer、Git blob 与 hash witness；错文件名和用户修改仍为 user-owned，避免生成角色指导变化造成升级或卸载误拒绝。

## 历史候选工具观察与真实 Host 边界

本任务当前工具元数据声明 `collaboration.wait_agent` 支持最大 `3600000` 毫秒、子代理通知和用户输入提前返回。Controller 实际调用该窗口：一次从 18:20:01 UTC 等待到 18:23:12 UTC，约 191 秒后收到普通实现消息且 `timed_out=false`。这证明当前工具能够在长窗口期间因消息提前返回，不能用该消息证明子代理完成。后续实质发现及 FINAL 通知被接收；Controller 用原生精确状态观察到该实现员的一键 completed 结果后直接复用，没有再次确认相同完成。

随后用户补充要求实际中断 Controller 的 `3600000` 毫秒原生等待：工具返回 `Wait interrupted by new input`，`timed_out=false`。这为本任务当前工具的用户输入提前中断提供直接运行观察，不能扩展成其他 Host 版本或真实已安装指导加载的证明。以上观察仍不单独证明每一种原生完成事件都必然在阻塞中的每个 Host 提前唤醒。完成证据处理由上述 fixture 覆盖；当前工具可用能力与真实已安装 Codex Host 加载是两类事实。未修改真实 Host、全局 AGENTS、Core 或 DSH。其他 Host 版本、实际已安装指导加载及其端到端响应仍为 UNKNOWN。[官方子代理文档](https://learn.chatgpt.com/docs/agent-configuration/subagents)提供一般编排说明，不被当作特定 Host 60 分钟上限的证据。

## 历史候选安装兼容性与剩余限制

新 GUIDANCE 对安装器新写入受管说明生效。现有逻辑在升级时保留有效旧 ownership fragment 及其文本，因而旧已安装等待说明不会仅因升级自动改写成新策略；本次不声称实现这种迁移。历史 receipt 仍按自身规范 fragment 证明 ownership，不与当前模板强制匹配，卸载可恢复原有字节。用户改动不被回收或覆盖。该行为保留此前兼容契约，未增加新的安装状态、维护权限或恢复框架。

本次是指导变更、针对性测试及历史生成角色 ownership hash 补充，未修改等待执行器、生命周期终止规则或 Host 内部实现。没有新增生产安装、升级、卸载写入路径；测试证明旧文案变化不制造 ownership 自锁，但真实 Host 的新指导交付和响应仍需另行授权、运行确认。

## 历史候选交付与 CI

第一里程碑源码提交 `41157f59ca26657e4b8ef99a09d55cbf6229fded`（`Prefer event-driven long Controller wait windows`）已推送 `main`；收尾以 `git ls-remote origin refs/heads/main` 观察到完全相同的远端 SHA。对应 [CI 38163975689](https://github.com/Iris0fTheValley/Thaliris-codex/actions/runs/38163975689) 由收尾执行员单独使用 `gh run watch --exit-status --interval 600` 观察，退出码 0；终态查询确认精确 headSha 一致，Ubuntu/Windows Python 3.11、3.12、3.13 六项全部 completed/success。这只证明该里程碑，不包含随后用户补充要求对应的新候选。

补充要求的最终合并源码提交 `79b17c242a99f6989520d0302883d890992e4ec2`（`Unify event-driven waiting across delegated roles`）已推送 `main`；收尾读取远端再次确认完全相同的 SHA。对应 [CI 38165751726](https://github.com/Iris0fTheValley/Thaliris-codex/actions/runs/38165751726) 由收尾单独使用同一原生 CLI watch 命令观察至终态，退出码 0；终态查询确认精确 headSha 一致，Ubuntu/Windows Python 3.11、3.12、3.13 六项全部 completed/success。没有因第一里程碑 CI 已通过而跳过最终候选结果。

CI 或单元测试成功是本次源码验收证据，不替代上述真实 Host 证据边界。最终报告单独提交，由 Controller 记录交付。
