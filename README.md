# Thaliris Codex adapter

Codex 的 Host 适配器，依赖共享 [Thaliris Core](https://github.com/Iris0fTheValley/Thaliris)，不是独立 Core，也不复制 Core。

`thaliris-codex` 发布 `thaliris_codex` 命名空间及 `thaliris` / `context` 命令。原生引导、角色配置、生命周期、Hook 信任、运行时身份、诊断和恢复由本适配器负责。共享记录、检索、证据、记忆与 authority API 来自 `thaliris`。

在独立 Python 3.11+ 环境内，先安装 Core，再安装适配器：

```sh
python -m pip install 'git+https://github.com/Iris0fTheValley/Thaliris.git@575652df9d1ebc45c6aa51609db67945e40e6c44'
python -m pip install --no-deps 'git+https://github.com/Iris0fTheValley/Thaliris-codex'
thaliris version
```

本地开发使用已审阅的 Core checkout：

```sh
python -m pip install -e '../Thaliris[test]'
python -m pip install --no-deps -e '.[test]'
```

The offline-recovery source-runner test needs `THALIRIS_CORE_SOURCE` set to
that checkout's root (the directory containing `src/thaliris/core.py`). The
runner deliberately loads this explicit checkout and does not treat the
installed Core package as reviewed source. In PowerShell, set it before running
the tests:

```powershell
$env:THALIRIS_CORE_SOURCE = (Resolve-Path '../Thaliris').Path
pytest
```

In POSIX shells, use `export THALIRIS_CORE_SOURCE=../Thaliris` before `pytest`.
CI sets this variable to its `shared-core` checkout.

安装不等于 Host 启用或信任。参见 [集成说明](adapter/codex/README.md)、[authority](docs/thaliris-task-authority.md) 与 [恢复](docs/thaliris-runtime-recovery.md)。正式 Host 安装应将两个 wheel 安装进禁用 system site packages 的专用环境；editable .pth 路径不会通过运行时 pin 验证。整个环境的文件（含共享 Core）被纳入 manifest。

[共享文档](https://github.com/Iris0fTheValley/Thaliris/tree/main/docs)、[ABCD 协议与历史证据](https://github.com/Iris0fTheValley/Thaliris/tree/main/benchmarks/abcd) 在主仓库；[DSH 兄弟适配器](https://github.com/Iris0fTheValley/Thaliris-dsh) 使用同一个 Core。

共享语义保持模型负责判断：INDEX 是由模型维护的薄语义导航地图，Core 只执行路径、CAS、大小与链接检查。Controller 选择要保留的知识，角色结果不会自动成为持久记忆。

历史迁移测试读取 `tests/fixtures/history/provenance.json` 指向的不可变 Git blob 原始字节，校验 blob ID 和 SHA-256，不把当前生成结果当成历史权属证据。

旧 admission-fix 提案的原始补丁与 profile 字节来源快照保存在[历史归档](docs/historical/admission-fix/README.md)；其中的 profile 内容变更拒绝行为不是当前启用契约。

语义角色、职责、路由和只读限制与执行模型分离。专用 Codex 安装可用
`codex-install --execution-constraint luna-only` 将所有普通 worker profile
设为 `gpt-6-luna/xhigh`，保留同一角色 ID 和指令。任务 authority contract
必须明确包含 `"execution_constraint": "luna-only"`；Core 将这个可选非空字符串作为不可变 intent 保存，适配器只接受 `luna-only` 并验证其执行绑定。外部 anchor 固定已校验的
profile/config 哈希，子角色及可变配置不能扩展或解除约束。安装后需新 Host session；
admission 比较 SessionStart 时记录的 role profile 和公开 config 文件哈希。这些磁盘观察
不能证明 Host 实际加载的 role map 或 CLI `-c` 覆盖。SubagentStart 核对受约束子角色的
Host model；缺失或不匹配时不绑定 handoff，后续子角色工具被拒绝。该 hook 无法阻止子角色
model 被调用。约束禁止 Astra profile 和每次 spawn 的模型覆盖；无约束时默认绑定不变。

此功能需要 `thaliris>=0.4.3`。开发测试必须安装本次修复的实际 Core checkout；旧 monolithic wheel 不满足 split package 边界。
