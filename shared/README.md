# shared：共享平台

承载 FR-116 所列公共能力：配置、日志、数据库连接、ORM 模型、标准事件契约、
脱敏与查询工具、构建/部署/边界检查脚本。**不得导入任何 `m1_`…`m5_` 包**。

目录：`shared/config.py`、`shared/db/`、`shared/models/`、`shared/events/`、
`shared/utils/`、`shared/data/`、`shared/deploy/`。测试运行：`uv run pytest shared/tests -q`。
