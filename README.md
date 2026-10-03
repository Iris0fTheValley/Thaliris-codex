# Thaliris Codex adapter

Codex 的 Host 适配器，依赖共享 [Thaliris Core](https://github.com/Iris0fTheValley/Thaliris)，不是独立 Core，也不复制 Core。

`thaliris-codex` 发布 `thaliris_codex` 命名空间及 `thaliris` / `context` 命令。原生引导、角色配置、生命周期、Hook 信任、运行时身份、诊断和恢复由本适配器负责。共享记录、检索、证据、记忆与 authority API 来自 `thaliris`。

在独立 Python 3.11+ 环境内，先安装 Core，再安装适配器：

```sh
python -m pip install 'git+https://github.com/Iris0fTheValley/Thaliris'
python -m pip install --no-deps 'git+https://github.com/Iris0fTheValley/Thaliris-Codex'
thaliris version
```

本地开发使用已审阅的 Core checkout：

```sh
python -m pip install -e '../Thaliris[test]'
python -m pip install --no-deps -e '.[test]'
pytest
```

安装不等于 Host 启用或信任。参见 [集成说明](adapter/codex/README.md)、[authority](docs/thaliris-task-authority.md) 与 [恢复](docs/thaliris-runtime-recovery.md)。正式 Host 安装应将两个 wheel 安装进禁用 system site packages 的专用环境；editable .pth 路径不会通过运行时 pin 验证。整个环境的文件（含共享 Core）被纳入 manifest。

[共享文档](https://github.com/Iris0fTheValley/Thaliris/tree/main/docs)、[ABCD 协议与历史证据](https://github.com/Iris0fTheValley/Thaliris/tree/main/benchmarks/abcd) 在主仓库；[DSH 兄弟适配器](https://github.com/Iris0fTheValley/Thaliris-DSH) 使用同一个 Core。

共享语义保持模型负责判断：INDEX 是由模型维护的薄语义导航地图，Core 只执行路径、CAS、大小与链接检查。Controller 选择要保留的知识，角色结果不会自动成为持久记忆。

历史迁移测试读取 `tests/fixtures/history/provenance.json` 指向的不可变 Git blob 原始字节，校验 blob ID 和 SHA-256，不把当前生成结果当成历史权属证据。

旧 admission-fix 提案的原始补丁与 profile 字节来源快照保存在[历史归档](docs/historical/admission-fix/README.md)；其中的 profile 内容变更拒绝行为不是当前启用契约。
