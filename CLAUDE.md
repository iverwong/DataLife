# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

本项目是一个**A股资讯自动采集与 Notion 同步系统**，主要功能：
- 从巨潮资讯网批量抓取上市公司公告
- 从 AkShare 抓取股票主营构成数据
- 自动处理 PDF 文件（大文件分割）
- 将数据同步到 Notion 数据流数据库
- 支持增量更新与去重

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

** deactivate 虚拟环境（完成工作后执行）**
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
Notion/
├── core/                      # 核心代码
│   ├── data/                  # 数据采集模块
│   │   ├── announcement.py    # 巨潮公告采集
│   │   ├── business.py        # 主营构成采集
│   │   └── pdf_split.py       # PDF 文件分割
│   ├── db/                    # 数据库模块
│   │   └── __init__.py        # SQLite 异步封装
│   ├── models/                # 数据模型
│   │   ├── __init__.py
│   │   ├── announcement.py
│   │   └── upload.py
│   ├── notion/                # Notion 集成
│   │   ├── client.py          # Notion 异步客户端
│   │   ├── flow_database.py   # 数据流页面创建
│   │   ├── upload_file.py     # 文件上传与轮询
│   │   ├── content_builder.py # 内容构建器
│   │   ├── datetime_helper.py # 日期转换工具
│   │   └── stock_pool.py      # 股票池查询
│   ├── handlers/              # 业务编排层
│   │   ├── __init__.py
│   │   ├── announcements/     # 公告处理子模块
│   │   │   ├── __init__.py
│   │   │   ├── fetcher.py
│   │   │   ├── deduplicator.py
│   │   │   ├── uploader.py
│   │   │   └── page_creator.py
│   │   └── business.py        # 主营构成处理
│   ├── logs/                  # 日志模块
│   └── scheduler/             # 调度器（预留）
├── tests/                     # 测试目录
│   ├── conftest.py            # 测试配置与 fixture
│   ├── resource/              # 静态资源（mock 数据）
│   │   ├── manager.py         # 资源管理器
│   │   └── fetch_*.py         # 资源获取脚本
│   ├── test_data/             # 数据模块测试
│   ├── test_db/               # 数据库测试
│   ├── test_notion/           # Notion 模块测试
│   └── test_*.py              # Handler 测试
├── main.py                    # 应用入口
├── .env                       # 环境变量（生产）
├── .dev.env                   # 环境变量（开发）
└── pytest.ini                 # pytest 配置
```

## 架构设计

### 数据流架构

```
外部数据源 → core/data（采集） → core/handlers（编排）
   ↓                              ↓
core/db（去重/记录） ←───→ core/notion（写入 Notion）
```

### 代码规范

- **类型注解**：所有公共函数必须有 type hints
- **文档字符串**：使用 Google 风格 docstring
- **编码规范**：PEP 8，行宽 120 字符
- **异步编程**：所有 I/O 操作使用 async/await
- **日志**：使用 logging 模块，禁用 print()

### 模块职责边界

- `core/data/`：只负责外部数据采集与预处理
- `core/notion/`：只负责 Notion API 交互
- `core/db/`：只负责本地持久化（共享存储）
- `core/models/`：共享数据类型定义
- `core/handlers/`：编排层，协调各模块完成业务流程

## 测试运行

**务必在虚拟环境中运行测试！**

```bash
# 激活虚拟环境（如果尚未激活）
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

| 标记 | 说明 |
|------|------|
| `@pytest.mark.unit` | 单元测试（使用 mock） |
| `@pytest.mark.integration` | 集成测试（跨模块协作） |
| `@pytest.mark.asyncio` | 异步测试 |
| `@pytest.mark.fast` | 执行时间 < 1 秒 |
| `@pytest.mark.slow` | 执行时间 > 1 秒 |
| `@pytest.mark.real_network` | 需要真实网络请求 |

### 测试资源管理

- 静态资源存储在 `tests/resource/`
- 使用 `ResourceManager` 加载/保存资源
- Mock 资源获取脚本以 `fetch_*.py` 命名

## 关键技术点

### 1. 异步并发

- 使用 `asyncio.gather()` 实现并发抓取与上传
- HTTP 客户端使用 `httpx.AsyncClient`
- 数据库使用 `aiosqlite` 异步连接

### 2. 增量更新策略

- 通过 `update_records` 表记录各股票的更新时间
- 按更新时间分组，合并查询请求
- 首次运行默认从一年前开始抓取

### 3. 去重机制

- 使用 `xxhash` 计算内容哈希
- 批量查询与保存哈希值
- 通过 `hash` 表实现幂等性

### 4. 文件上传策略

- **外链上传**：小文件（<=1000KB）或不含关键词
- **本地上传**：大文件且含关键词 → PDF 分割 → 本地上传

### 5. PDF 分割策略

- `CHUNK_SIZE`: 单片最大页数（默认 95）
- `REP_SIZE`: 重叠页数（默认 5）

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
- 遵循单元测试/集成测试/真实测试三层结构

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
pytest tests/test_announcements_data_handler.py -v

# 运行特定标记的测试
pytest tests/ -m unit --tb=short

# 检查代码规范（如已配置 ruff/pylint）
ruff check .
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

1. **环境变量缺失**：检查 `.env` 或 `.dev.env` 是否配置
2. **Notion API 错误**：检查 Token 权限与数据库 ID
3. **数据库异常**：检查 `core/db/notion.db` 文件权限
4. **文件上传失败**：查看日志中的轮询错误信息

### 日志位置

- 控制台：DEBUG 级别日志
- 文件：`logs/` 目录
