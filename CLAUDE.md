# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

本项目是一个 **A股资讯自动采集与 Notion 同步系统**，主要功能：

- 从巨潮资讯网批量抓取上市公司公告（PDF）
- 从 AkShare（东方财富）抓取股票主营构成数据
- 自动处理 PDF 文件（大文件分割、重叠页保证连贯性）
- 将数据同步到 Notion 资讯流数据库
- 支持增量更新与基于 xxhash 的内容去重

## ⚠️ 重要：虚拟环境使用规范

**本项目必须使用 venv 虚拟环境运行！**

所有 Python 命令都必须在虚拟环境中执行：

```bash
# 使用虚拟环境运行Python
./venv/Scripts/python

# 使用虚拟环境运行pytest
./venv/Scripts/python -m pytest

# 使用虚拟环境运行basedpyright
./venv/Scripts/python -m basedpyright

# 使用虚拟环境运行ruff
./venv/Scripts/python -m ruff
```

## 快速开始

### 环境变量

项目使用 `.env` 文件管理配置（已在 `.gitignore` 中忽略）：

```bash
NOTION_TOKEN="你的 Notion Integration Token"
FLOW_DATABASE="资讯流数据库 ID"
STOCK_POOL="股票池数据库 ID"
```

开发环境使用 `.dev.env`（优先级更高）。

### 运行项目

```bash
python main.py
```

## 项目架构

### 分层职责

| 层          | 包路径           | 职责                              |
| ----------- | ---------------- | --------------------------------- |
| 数据采集    | `core/data/`     | 外部 API 调用与原始数据获取       |
| 领域模型    | `core/models/`   | 跨模块共享的数据类型定义          |
| 本地持久化  | `core/db/`       | SQLite 去重哈希与更新时间管理     |
| Notion 集成 | `core/notion/`   | Notion API 交互（CRUD、文件上传） |
| 业务编排    | `core/handlers/` | 协调各层完成业务流程              |

### 公告处理流程

```
fetch_announcements_for_stocks() → deduplicate_announcements()
    → upload_announcement_files() → create_announcement_pages()
    → save_hash() + set_update_time()
```

### 主营构成处理流程

```
get_update_time() → get_business() → check_hash()
    → create_dataflow_page() → save_hash() + set_update_time()
```

## 关键技术点

### 并发控制

| 控制点     | 机制              | 限制    |
| ---------- | ----------------- | ------- |
| Notion API | aiolimiter 令牌桶 | 3 req/s |
| 巨潮 API   | asyncio.Semaphore | 5 并发  |
| PDF 下载   | asyncio.Semaphore | 3 并发  |

### 去重机制

- 使用 `xxhash`（xxh3_64）计算内容哈希
- 哈希输入包含 `data_type` 和 `content` 的 JSON 序列化
- 通过 `hash` 表实现幂等性

### 文件上传策略

| 条件              | 策略         | 说明                              |
| ----------------- | ------------ | --------------------------------- |
| ≤200KB 且无关键词 | 外链上传     | 直接提供 URL 给 Notion            |
| >200KB 或含关键词 | 本地分割上传 | PDF 按 20 页分割，相邻块重叠 2 页 |

### PDF 分割参数

- `CHUNK_SIZE = 20`：单片最大页数
- `REP_SIZE = 2`：相邻分片重叠页数
- 分割使用 PyMuPDF（`pymupdf`），内存中操作不写临时文件

### 重试机制

`@with_retry()` 装饰器提供指数退避重试：默认最多重试 3 次，退避间隔 1s → 2s → 4s

### Notion 内容构建

`NotionContentBuilder` 提供链式 API：

```python
content = (
    NotionContentBuilder()
    .add_heading("标题", level=3)
    .add_table_from_dataframe(df)
    .build()
)
```

## 代码规范

- **类型注释**：所有函数必须有完整的 type hints。代码编写完成后执行 `basedpyright` 进行静态类型检查
- **文档字符串**：使用 Google 风格 docstring
- **编码规范**：PEP 8（行宽 120 字符）
- **异步编程**：所有 I/O 操作使用 async/await
- **日志**：使用 logfire 模块，禁用 print()
- **数据类**：优先使用 `frozen dataclass` 而非 TypedDict
- **外部 API 调用**：必须包含超时设置

## Claude Code 配置

### 权限设置

项目配置了以下工具权限（详见 `.claude/settings.local.json`）：

- 允许：`mcp__MiniMax__web_search`、`mcp__MiniMax__understand_image`、git 操作、pytest、ruff、basedpyright
- 拒绝：`WebSearch`（使用 MCP web_search 代替）

### TDD 工作流

项目定义了 TDD 技能用于执行计划：

- **/tdd-red**：契约定义与测试编写（Red 阶段）
- **/tdd-green**：实现代码编写（Green 阶段）

使用方式：
```
/tdd-red .claude/plans/<执行计划文件>
```

执行计划文件存放在 `.claude/plans/` 目录，每个计划包含详细的步骤说明。

### 重构工作流

项目定义了 refactor 技能用于代码重构：

- 使用前先阅读 `.claude/skills/refactor/SKILL.md` 了解安全检查清单
- 重构前确保有测试覆盖

## 测试运行

```bash
# 运行所有测试
pytest tests/ -v

# 运行单元测试
pytest tests/ -m unit -v

# 运行单个测试文件
pytest tests/test_xxx.py -v

# 生成覆盖率报告
pytest tests/ --cov=core --cov-report=html
```

### 测试标记

| 标记                        | 说明                  |
| --------------------------- | --------------------- |
| `@pytest.mark.unit`         | 单元测试（使用 mock） |
| `@pytest.mark.asyncio`      | 异步测试              |
| `@pytest.mark.real_network` | 需要真实网络请求      |

## 常用命令

```bash
# 运行项目
python main.py

# 代码规范检查
ruff check core/

# 静态类型检查
basedpyright core/
```

## 故障排查

### 常见问题

| 问题            | 排查方向                           |
| --------------- | ---------------------------------- |
| 模块找不到      | 确认虚拟环境已激活                 |
| 环境变量缺失    | 检查 `.env` 或 `.dev.env` 是否配置 |
| Notion API 错误 | 检查 Token 权限与数据库 ID         |
| 文件上传失败    | 查看 `logs/app.log` 错误日志       |

### 日志位置

- 控制台：DEBUG 级别日志
- 文件：`logs/app.log`（全量）、`logs/error.log`（仅错误）