# CLAUDE.md

This file provides guidance to Claude Code (http://claude.ai/code) when working with code in this repository.

## 项目简介

本项目是一个 **A股资讯自动采集与 Notion 同步系统**，主要功能：

- 从巨潮资讯网批量抓取上市公司公告（PDF）
- 从 AkShare（东方财富）抓取股票主营构成数据
- 自动处理 PDF 文件（大文件分割、重叠页保证连贯性）
- 将数据同步到 Notion 资讯流数据库
- 支持增量更新与基于 xxhash 的内容去重

## ⚠️ 重要：虚拟环境使用规范

**本项目必须使用 venv 虚拟环境运行！**

所有 Python 命令（包括运行、测试、依赖安装）都必须在虚拟环境中执行：

```bash
# 激活虚拟环境（每次会话开始时执行）
./venv/Scripts/activate

# 验证虚拟环境已激活（提示符应显示 "venv"）
python --version  # 应显示 Python 路径在 venv 下
```

**未激活虚拟环境就运行 Python 代码可能导致：**

- 模块找不到（ModuleNotFoundError）
- 依赖版本不匹配
- 数据库存储路径错误
- 测试无法正常运行

**deactivate 虚拟环境（完成工作后执行）**

```bash
deactivate
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

**确保虚拟环境已激活！** 然后运行：

```bash
python main.py
```

## 项目结构

```
DataLife/
├── core/                          # 核心代码
│   ├── data/                      # 数据采集层
│   │   ├── announcement.py        # 巨潮资讯网公告采集
│   │   ├── business.py            # AkShare 主营构成采集
│   │   ├── models.py              # 外部 API 响应 Pydantic 模型
│   │   └── pdf_split.py           # PDF 下载与分割
│   ├── db/                        # 本地持久化层
│   │   └── __init__.py            # SQLite 异步封装（去重 + 更新时间管理）
│   ├── models/                    # 共享领域模型
│   │   ├── __init__.py            # NotionDate、UpdateRecordKey 类型定义
│   │   ├── announcement.py        # AnnouncementWithHash
│   │   └── upload.py              # FileUploadRequest / Result / WithContent
│   ├── notion/                    # Notion API 集成层
│   │   ├── client.py              # 带速率限制的 AsyncClient（3 req/s）
│   │   ├── flow_database.py       # 资讯流数据库页面创建
│   │   ├── upload_file.py         # 文件上传（外链 + 本地两种模式）
│   │   ├── content_builder.py     # 链式 Notion Block 构建器
│   │   ├── stock_pool.py          # 股票池数据源查询
│   │   ├── datetime_helper.py     # 日期转换工具（UTC+8）
│   │   ├── retry_helper.py        # 指数退避重试装饰器
│   │   └── models.py              # Notion API Pydantic 模型
│   ├── handlers/                  # 业务编排层
│   │   ├── announcements/         # 公告处理子模块
│   │   │   ├── __init__.py        # 主流程编排
│   │   │   ├── fetcher.py         # 按更新时间分组获取公告
│   │   │   ├── deduplicator.py    # xxhash 去重
│   │   │   ├── uploader.py        # 分类上传（外链/本地分割）
│   │   │   └── page_creator.py    # Notion 页面批量创建
│   │   └── business.py            # 主营构成处理编排
│   ├── logs/                      # 日志模块
│   │   └── __init__.py            # logfire + 标准 logging 配置
│   ├── scheduler/                 # 调度器（预留）
│   │   └── __init__.py            # APScheduler 初始化
│   └── utils/                     # 通用工具
│       ├── __init__.py            # 工具导出
│       └── concurrency.py         # 并发控制（Semaphore 封装）
├── tests/                         # 测试目录
│   ├── conftest.py                # 测试配置与 fixture
│   ├── resource/                  # 静态资源（mock 数据）
│   │   ├── manager.py             # ResourceManager 资源管理器
│   │   └── fetch_*.py             # 资源获取脚本
│   ├── test_data/                 # 数据模块测试
│   ├── test_db/                   # 数据库测试
│   ├── test_notion/               # Notion 模块测试
│   └── test_*.py                  # Handler 测试
├── scripts/                       # 辅助脚本
│   └── fetch_static_resources.py  # 静态资源获取
├── .claude/                       # Claude Code 配置
│   ├── plans/                     # 编码计划
│   └── skills/                    # TDD 技能定义
├── main.py                        # 应用入口
├── .env                           # 环境变量（生产）
├── .dev.env                       # 环境变量（开发）
├── pyrightconfig.json             # 类型检查配置
└── pytest.ini                     # pytest 配置
```

## 架构设计

### 数据流架构

```
外部数据源 → core/data（采集） → core/handlers（编排）
   ↓                                    ↓
core/db（去重/记录） ←─────────→ core/notion（写入 Notion）
```

### 分层职责

| 层          | 包路径           | 职责                              | 依赖方向           |
| ----------- | ---------------- | --------------------------------- | ------------------ |
| 数据采集    | `core/data/`     | 外部 API 调用与原始数据获取       | → 外部 API         |
| 领域模型    | `core/models/`   | 跨模块共享的数据类型定义          | 无外部依赖         |
| 本地持久化  | `core/db/`       | SQLite 去重哈希与更新时间管理     | → aiosqlite        |
| Notion 集成 | `core/notion/`   | Notion API 交互（CRUD、文件上传） | → notion-client    |
| 业务编排    | `core/handlers/` | 协调各层完成业务流程              | → data, db, notion |
| 工具层      | `core/utils/`    | 并发控制等通用基础设施            | 无业务依赖         |

### 公告处理流程（handlers/announcements）

```
fetch_announcements_for_stocks()    # 1. 按更新时间分组，并发获取公告
    ↓
deduplicate_announcements()         # 2. xxhash 去重，过滤已处理公告
    ↓
upload_announcement_files()         # 3. 按大小/关键词分类上传
  ├── 小文件（≤200KB 且无关键词） → 外链上传
  └── 大文件或含关键词 → PDF 分割 → 本地上传
    ↓
create_announcement_pages()         # 4. 批量创建 Notion 资讯流页面
    ↓
save_hash() + set_update_time()     # 5. 记录哈希与更新时间
```

### 主营构成处理流程（handlers/business）

```
get_update_time()                   # 1. 检查半年度更新周期
    ↓
get_business()                      # 2. AkShare 获取分行业/产品/地区数据
    ↓
check_hash()                        # 3. xxhash 去重
    ↓
NotionContentBuilder → create_dataflow_page()  # 4. 构建表格内容并创建页面
    ↓
save_hash() + set_update_time()     # 5. 记录哈希与更新时间
```

## 代码规范

- **类型注释**：所有函数（含私有函数）必须有完整的 type hints（参数 + 返回值）。非必要禁止使用 `Any` 类型，如确需使用须在行内注释说明原因（如 `# Any: 第三方库返回类型不确定`）。代码编写完成后，执行 `basedpyright` 进行静态类型检查，确保无类型错误或警告
- **文档字符串**：使用 Google 风格 docstring
- **编码规范**：PEP 8（行宽 120 字符）
- **异步编程**：所有 I/O 操作使用 async/await
- **日志**：使用 logfire 模块，禁用 print()
- **数据类**：优先使用 `frozen dataclass` 而非 TypedDict
- **跨模块类型**：放入 `core/models/`
- **外部 API 调用**：必须包含超时设置
- **错误处理**：必须包含有意义的日志

## 关键技术点

### 1. 并发控制体系

项目采用两级并发控制：

| 控制点     | 机制              | 限制    | 位置                        |
| ---------- | ----------------- | ------- | --------------------------- |
| Notion API | aiolimiter 令牌桶 | 3 req/s | `core/notion/client.py`     |
| 巨潮 API   | asyncio.Semaphore | 5 并发  | `core/utils/concurrency.py` |
| PDF 下载   | asyncio.Semaphore | 3 并发  | `core/utils/concurrency.py` |

### 2. 去重机制

- 使用 `xxhash`（xxh3_64）计算内容哈希
- 哈希输入包含 `data_type` 和 `content` 的 JSON 序列化
- 批量查询与保存哈希值
- 通过 `hash` 表实现幂等性

### 3. 文件上传策略

| 条件              | 策略         | 说明                              |
| ----------------- | ------------ | --------------------------------- |
| ≤200KB 且无关键词 | 外链上传     | 直接提供 URL 给 Notion            |
| >200KB 或含关键词 | 本地分割上传 | PDF 按 20 页分割，相邻块重叠 2 页 |

关键词列表：`["年度报告", "年报", "中期"]`

### 4. PDF 分割参数

- `CHUNK_SIZE = 20`：单片最大页数
- `REP_SIZE = 2`：相邻分片重叠页数
- 分割使用 PyMuPDF（`pymupdf`），内存中操作不写临时文件

### 5. 增量更新策略

- 通过 `update_records` 表记录各股票的更新时间
- 按更新时间分组，合并查询请求
- 首次运行默认从一年前开始抓取
- 主营构成按半年度周期更新（Q2→次年1月，Q4→次年7月）

### 6. 重试机制

`@with_retry()` 装饰器提供指数退避重试：

- 默认最多重试 3 次
- 退避间隔：1s → 2s → 4s
- 可重试异常：`httpx.ConnectError`、`TimeoutException`、`NetworkError`、`ReadError`、`WriteError`、`RequestTimeoutError`
- 非可重试异常直接抛出

### 7. Notion 内容构建

`NotionContentBuilder` 提供链式 API：

```python
content = (
    NotionContentBuilder()
    .add_heading("标题", level=3)
    .add_table_from_dataframe(df)
    .add_divider()
    .add_callout("提示", icon="💡")
    .build()
)
```

### 8. 日志与可观测性

- **logfire**：主日志框架，基于 OpenTelemetry 提供 trace/span
- **标准 logging 桥接**：logfire 日志流入 logging 输出到文件
- **控制台**：INFO 级别彩色输出
- **全量日志**：`logs/app.log`，每日轮转保留 30 天
- **错误日志**：`logs/error.log`，每日轮转保留 90 天

## 测试运行

**务必在虚拟环境中运行测试！**

```bash
# 激活虚拟环境（如尚未激活）
./venv/Scripts/activate

# 运行所有测试
pytest tests/ -v

# 运行单元测试
pytest tests/ -m unit -v

# 运行异步测试
pytest tests/ -m asyncio -v

# 运行真实网络测试（需要配置 .env）
pytest tests/ -m real_network -v

# 生成覆盖率报告
pytest tests/ --cov=core --cov-report=html
```

### 测试标记说明

| 标记                        | 说明                   |
| --------------------------- | ---------------------- |
| `@pytest.mark.unit`         | 单元测试（使用 mock）  |
| `@pytest.mark.integration`  | 集成测试（跨模块协作） |
| `@pytest.mark.asyncio`      | 异步测试               |
| `@pytest.mark.fast`         | 执行时间 < 1 秒        |
| `@pytest.mark.slow`         | 执行时间 > 1 秒        |
| `@pytest.mark.real_network` | 需要真实网络请求       |

### 测试资源管理

- 静态资源存储在 `tests/resource/`
- 使用 `ResourceManager` 加载/保存资源
- Mock 资源获取脚本以 `fetch_*.py` 命名

## 开发指南

### 新增数据源接入

1. 在 `core/data/` 下新建采集模块
2. 在 `core/handlers/` 下新建 handler 模块
3. 复用 `core/db/` 的更新时间管理与去重
4. 复用 `core/notion/flow_database.py` 创建页面
5. 在 `main.py` 中注册调度入口

### 新增测试

- 测试文件与 `core/` 目录结构对应
- 使用 `ResourceManager` 管理静态资源
- 遵循单元测试/集成测试/真实网络测试三层结构

### 编码最佳实践

- 优先使用 `frozen dataclass` 而非 TypedDict
- 跨模块类型放入 `core/models/`
- 外部 API 调用必须包含超时设置
- 错误处理 must 包含有意义的日志

## 常用命令

**所有命令都必须在虚拟环境中执行！**

```bash
# 激活虚拟环境（如未激活）
./venv/Scripts/activate

# 运行项目
python main.py

# 运行测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_business_data_handler.py -v

# 运行特定标记的测试
pytest tests/ -m unit --tb=short

# 检查代码规范
ruff check .
# 静态类型检查
basedpyright
```

## 故障排查

### ⚠️ 通用排查步骤

**如果遇到模块找不到或依赖相关错误，请先确认：**

1. **虚拟环境是否已激活**
    
    ```bash
    ./venv/Scripts/activate
    python --version  # 确认路径在 venv 下
    ```
    
2. **依赖是否已安装**
    
    ```bash
    pip list  # 检查关键依赖是否安装
    pip install -r requirements.txt  # 如需要，重新安装
    ```
    
3. **确认环境变量已配置**
    - 检查 `.env` 或 `.dev.env` 是否存在
    - 确认 `NOTION_TOKEN`、`FLOW_DATABASE` 等变量已设置

### 常见问题

| 问题            | 排查方向                           |
| --------------- | ---------------------------------- |
| 环境变量缺失    | 检查 `.env` 或 `.dev.env` 是否配置 |
| Notion API 错误 | 检查 Token 权限与数据库 ID         |
| 数据库异常      | 检查 `core/db/notion.db` 文件权限  |
| 文件上传失败    | 查看日志中的轮询错误信息           |
| 并发异常        | 检查 Semaphore 配置与网络连接      |

### 日志位置

- 控制台：DEBUG 级别日志
- 文件：`logs/app.log`（全量）、`logs/error.log`（仅错误）