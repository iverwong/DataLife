---
trigger: always_on
---
# 项目规则：A股资讯自动采集与 Notion 同步系统

## 项目概述

本项目从巨潮资讯网、AkShare 等数据源异步采集上市公司公告与主营构成等数据，经去重与预处理后写入 Notion 数据库，形成统一的"资讯流"页面。

## 运行环境
！！！**重要**！！！

- **Python 虚拟环境**: 本项目使用 venv 虚拟环境管理依赖
- **环境激活**: 所有 Python 命令执行前必须先激活虚拟环境
  - PowerShell: `./venv/Scripts/Activate.ps1`
  - 激活后终端提示符会显示 `(venv)` 前缀
- **禁止**: 在未激活虚拟环境的情况下运行任何 Python 脚本或测试

## 技术栈

- **语言**: Python 3.8+
- **异步框架**: asyncio
- **HTTP 客户端**: httpx（异步）
- **数据库**: aiosqlite（本地 SQLite）
- **PDF 处理**: pymupdf
- **Notion SDK**: notion-client（AsyncClient）
- **去重哈希**: xxhash
- **缓存**: alru_cache
- **数据源**: 巨潮资讯网 API、AkShare
- **测试**: pytest + pytest-asyncio + freezegun（时间控制）

## 编码规范

### Python 风格

- 遵循 PEP 8，行宽 120 字符
- 所有公共函数、类必须有 docstring（Google 风格）
- 使用 type hints 标注所有函数签名和返回值
- 变量命名使用 snake_case，类名使用 PascalCase，常量使用 UPPER_SNAKE_CASE
- 禁止使用 `import *`，每个 import 必须明确

### 异步编程

- 所有 I/O 操作（网络请求、数据库、文件读写）必须使用 async/await
- 并发任务使用 `asyncio.gather()`，禁止在异步代码中使用同步阻塞调用
- 对外部 API 调用必须包含超时设置（httpx timeout）
- 遵循现有的指数退避重试模式（参考 `upload_file.py` 中的轮询机制）

### 错误处理

- 所有外部 API 调用必须使用 try/except 捕获异常，并记录有意义的日志
- 使用 `logging` 模块，禁止使用 `print()` 进行调试输出
- 异常日志应包含：操作上下文、请求参数（脱敏）、错误堆栈
- Notion API 调用失败时应区分可重试（429/5xx）与不可重试（400/401/404）错误
- HTTP 请求失败后应立即返回，避免继续处理无效数据
- 缺失必要环境变量时应记录警告日志，便于排查配置问题

### 数据库操作

- 所有 SQLite 操作通过 `core/db/__init__.py` 中的统一接口执行
- 写操作必须使用事务，确保原子性
- 新增表或字段时，必须在 `init_db()` 中添加对应的 CREATE TABLE IF NOT EXISTS
- 去重逻辑统一使用 xxhash，通过 `hash` 表进行批量查重

## 架构约定

### 模块职责边界

- `core/data/` — 只负责外部数据采集与预处理，不涉及 Notion 操作
- `core/notion/` — 只负责 Notion API 交互，不涉及数据采集逻辑
- `core/db/` — 只负责本地持久化，提供跨模块共享的存储能力
- `core/models/` — 共享数据类型定义，使用 frozen dataclass 模式
- `core/handlers/` — 编排层，协调 data、db、notion 模块完成业务流程
- 新增功能应遵循此分层，禁止跨层直接耦合

### Handler 分层架构

Handler 模块采用分层架构，以 `core/handlers/announcements/` 为例：

```
core/handlers/announcements/
├── __init__.py      # 主编排函数 process_announcements_for_stock_list()
├── fetcher.py       # 数据获取与分组
├── deduplicator.py  # 基于 xxhash 的去重逻辑
├── uploader.py      # 文件分类与上传策略
└── page_creator.py  # Notion 页面创建
```

数据流方向：`fetcher → deduplicator → uploader → page_creator`

每个子模块职责单一，便于单元测试与维护。新增复杂 handler 时应参考此模式。

### 类型系统

项目使用 frozen dataclass 定义共享数据类型，存放于 `core/models/`：

- `AnnouncementWithHash` — 公告与其去重哈希值的配对
- `FileUploadRequest` — 文件上传请求参数
- `FileUploadWithContent` — 带文件内容的上传请求
- `FileUploadResult` — 上传结果（成功/失败状态）
- `HashContent` / `HashContentWithHash` — 哈希记录数据结构

类型定义原则：
- 优先使用 frozen dataclass 而非 TypedDict，获得更好的类型检查与 IDE 支持
- 跨模块共享的类型放入 `core/models/`，模块内部类型可在模块内定义
- 使用 type alias 简化复杂类型签名（如 `UpdateRecordKey = Literal["business", "announcements"]`）

### 数据流方向

```

外部 API → core/data（采集/预处理）→ core/db（去重/记录）→ core/notion（写入 Notion）→ core/db（更新/记录）

```

handler 模块负责编排以上流程，main.py 负责初始化与调度入口。

### 新增数据源接入模式

1. 在 `core/data/` 下新建采集模块，封装接口调用与数据清洗
2. 在 `core/handlers/` 下新建对应的 handler 模块（简单流程用单文件，复杂流程用子包）
3. 复用 `core/db/` 的更新时间管理与去重哈希
4. 复用 `core/notion/flow_database.py` 创建数据流页面
5. 在 `main.py` 中注册调度入口

## Notion API 使用规范

### 属性映射

- 页面属性键必须与 Notion 数据库 schema 完全一致（参考 `flow_database.py` 中的 TYPE_MAPPING）
- 日期统一使用 NotionDate 类型别名（ISO-8601 字符串）
- 日期转换使用 `convert_datetime_to_notion_date()` 和 `convert_notion_date_to_datetime()` 函数
- 关联股票通过 relation 属性绑定到股票池数据源

### 文件上传策略

- 小文件 或 不含目标关键词的文件 → 外链模式（直接使用巨潮 URL）
- 大文件 且 含目标关键词 → 先 PDF 分割（pymupdf），再本地上传
- 上传后必须轮询确认状态，采用指数退避

### 内容构建

- 使用 `content_builder.py` 提供的方法构建 Notion Block
- 支持的块类型：标题、段落、表格、分隔线、Callout
- 新增块类型时在 content_builder 中扩展，禁止在 handler 中直接拼装 JSON

## 环境变量

以下环境变量必须配置，否则程序无法启动：

| 变量名          | 说明                     |
| --------------- | ------------------------ |
| `NOTION_TOKEN`  | Notion Integration Token |
| `STOCK_POOL`    | 股票池数据源 ID          |
| `FLOW_DATABASE` | 资讯流数据库 ID          |

修改或新增环境变量时，同步更新本规则文件与 README。

## 测试规范

- 测试文件放在 `tests/` 目录，命名 `test_<模块名>.py`，与 `core/` 目录中的模块一一对应
- 异步测试使用 `@pytest.mark.asyncio` 标记
- 外部 API 调用使用静态资源 mock，静态资源通过访问真实资源下载后存储，并保存在 `tests/resource` 中
- 关键路径（去重、更新时间策略、PDF 分割边界）必须有单元测试覆盖
- 时间相关测试使用 `freezegun.freeze_time()` 冻结时间，避免直接 mock datetime 模块
- Handler 模块测试路径应匹配新结构：`core.handlers.business`、`core.handlers.announcements` 等

## 性能约定

- 批量操作优先使用 `asyncio.gather()` 并发
- 按更新时间分组合并同日期股票查询，减少接口调用
- 巨潮股票代码映射使用 `alru_cache` 缓存
- Notion API 调用需考虑速率限制（429），预留限流机制接入点

## 代码修改原则

- 修改前先理解现有模块的职责边界，不破坏分层架构
- 优先复用已有工具函数（content_builder、db 接口、upload_file）
- 新增功能应附带对应的测试用例
- 涉及 Notion 属性变更时，同步检查 TYPE_MAPPING 的一致性
- Handler 模块修改应遵循分层模式，保持各子模块职责单一
- 新增共享类型时放入 `core/models/`，使用 frozen dataclass 定义