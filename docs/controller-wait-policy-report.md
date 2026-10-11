# Controller 等待策略收尾报告

本次独立收尾依据用户原始等待要求、候选源码、执行员测试证据和当前任务原生工具观察完成验收。结论：在源码、生成指令及测试覆盖范围内通过；不等于真实已安装 Host 已加载新指导，也不证明所有 Codex 版本都具备同样唤醒行为。

## 修改与优先级

- 权威源 `src/thaliris_codex/controller_instructions.md` 和安装器的 `src/thaliris_codex/wait_guidance_config.py::GUIDANCE` 均先要求确认当前 Host 的实际上限、事件提前返回、中断与通知能力。未经确认保持 UNKNOWN。
- 已确认实质事件可提前返回、且没有中途依赖决策时，默认使用实际支持的 `timeout_ms=3600000`。60 分钟是最大等待窗口，不是子代理执行时长要求；历史短平均时长不强迫提前唤醒。
- 只有实际需要阶段检查或提前返回不可靠时，才采用极短任务 60 秒、普通任务 10–60 分钟、较长任务约 30 分钟阶段窗口的推荐值。事件可靠且没有阶段决策仍优先 60 分钟。
- 实际工具限制、明确适用的更高层时限、用户中断、恢复与紧急决策优先。短工具上限不通过修改 Host 延长。
- 原生终止证据、普通子代理消息、超时分别处理。消息或超时不证明结束；wake-only 返回后只做一次可用的精确原生状态检查。已经证明完成不重复确认。
- 不使用 sleep 替代原生等待，不新增进度轮询器、每子代理定时循环或未变化状态的反复推理。并行时等待能改变当前决策的事件。执行员继续负责本地测试与 CI，独立收尾负责最终验收。

旧的“工具最大值永不作为默认值”及普遍固定短等待暗示已经从相关 Controller 指导和文档移除。`docs/thaliris-controller.md` 按现有同步机制生成；中文与英文 README、`adapter/codex/README.md` 同步相同条件与例外。Hook 仍保留调用者等待参数，未新增调度或自动延长机制。

## 验证证据

执行员在明确使用当前 Adapter/Core 源码导入路径的环境完成 83 项针对性检查：30 项等待配置测试、33 项提示词契约测试、20 项相关生命周期测试；随后新增生成及文档一致性检查通过，合计 84 项。同步检查与 `git diff --check` 通过。收尾复用这些有效结果，另独立核对候选差异、相关等待文字与 ownership 路径，并运行以下两项检查，通过；它们是已有覆盖的复核，不另计为新增独立场景：

```text
python -m pytest -q \
  tests/test_prompt_contract.py::test_controller_wait_policy_reaches_generated_and_documented_surfaces \
  tests/test_wait_guidance_config.py::test_guidance_matches_the_accepted_waiting_priorities
```

运行时应将 `PYTHONPATH` 指向当前 Adapter `src` 及当前 Core `src`，并将 `THALIRIS_CORE_SOURCE` 指向当前 Core 工作树；不能误用其他工作区的旧包。上述检查的 Windows 输出为两项通过、退出码 0；系统依赖发出既有 RequestsDependencyWarning，没有测试失败。

关键覆盖包括：

- V1 完成 fixture 使用 `timeout_ms=3600000`，精确已绑定原生完成证据直接结束执行观察，不要求另一次 list/stop。
- 普通子代理进度消息、运行状态加超时、空状态加超时不能成为终止证明；这些是合成响应测试，没有真实等待 60 分钟制造超时。
- 权威 Controller 渲染与生成文件精确一致，所有相关文档具有新默认窗口及 UNKNOWN 边界，旧的相反默认文字不再出现。
- 测试使用真实旧版 GUIDANCE 文案的 ownership receipt，覆盖直接卸载、升级后卸载及用户改动保留；原有可选配置失败保护保持覆盖。生产 ownership 和写入流程未改动。

## 当前工具观察与真实 Host 边界

本任务当前工具元数据声明 `collaboration.wait_agent` 支持最大 `3600000` 毫秒、子代理通知和用户输入提前返回。Controller 实际调用该窗口：一次从 18:20:01 UTC 等待到 18:23:12 UTC，约 191 秒后收到普通实现消息且 `timed_out=false`。这证明当前工具能够在长窗口期间因消息提前返回，不能用该消息证明子代理完成。后续实质发现及 FINAL 通知被接收；Controller 用原生精确状态观察到该实现员的一键 completed 结果后直接复用，没有再次确认相同完成。

这组观察不单独证明每一种原生完成事件都必然在阻塞中的每个 Host 提前唤醒，也没有实际进行用户中断实验。完成证据处理由上述 fixture 覆盖；当前工具可用能力与真实已安装 Codex Host 加载是两类事实。未修改真实 Host、全局 AGENTS、Core 或 DSH。其他 Host 版本、实际已安装指导加载、用户中断端到端行为仍为 UNKNOWN。[官方子代理文档](https://learn.chatgpt.com/docs/agent-configuration/subagents)提供一般编排说明，不被当作特定 Host 60 分钟上限的证据。

## 安装兼容性与剩余限制

新 GUIDANCE 对安装器新写入受管说明生效。现有逻辑在升级时保留有效旧 ownership fragment 及其文本，因而旧已安装等待说明不会仅因升级自动改写成新策略；本次不声称实现这种迁移。历史 receipt 仍按自身规范 fragment 证明 ownership，不与当前模板强制匹配，卸载可恢复原有字节。用户改动不被回收或覆盖。该行为保留此前兼容契约，未增加新的安装状态、维护权限或恢复框架。

本次是指导变更及针对性测试更新，未修改等待执行器、生命周期终止规则或 Host 内部实现。没有新增生产安装、升级、卸载写入路径；测试证明旧文案变化不制造 ownership 自锁，但真实 Host 的新指导交付和响应仍需另行授权、运行确认。

## 交付与 CI

待本候选提交后，由执行观察 owner 补充实际提交、远端一致性及 CI 结果。CI 或单元测试成功是本次源码验收证据，不替代上述真实 Host 证据边界。
