# Notion集成模块

<cite>
**本文引用的文件**
- [main.py](file://main.py)
- [core/db/__init__.py](file://core/db/__init__.py)
- [core/models/__init__.py](file://core/models/__init__.py)
- [core/data/announcement.py](file://core/data/announcement.py)
- [core/data/pdf_split.py](file://core/data/pdf_split.py)
- [core/notebook/stock_pool.py](file://core/notebook/stock_pool.py)
- [core/notion/client.py](file://core/notion/client.py)
- [core/notion/upload_file.py](file://core/notion/upload_file.py)
- [core/notion/datetime_helper.py](file://core/notion/datetime_helper.py)
- [core/notion/content_builder.py](file://core/notion/content_builder.py)
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py)
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py)
</cite>

## 目录
1. [简介](#简介)
2. [项目结构](#项目结构)
3. [核心组件](#核心组件)
4. [架构总览](#架构总览)
5. [详细组件分析](#详细组件分析)
6. [依赖关系分析](#依赖关系分析)
7. [性能考量](#性能考量)
8. [故障排查指南](#故障排查指南)
9. [结论](#结论)
10. [附录](#附录)

## 简介
本文件面向Notion集成模块的技术文档，聚焦以下目标：
- Notion API客户端封装与调用路径
- 数据库操作接口与本地状态管理
- 文件上传策略（外链直传与本地上传）及分片机制
- 时间格式转换与统一时区处理
- 与公告数据处理模块的集成与数据同步流程
- API限制、错误处理与重试机制
- 面向初学者的易读性说明与面向资深开发者的深度细节

## 项目结构
模块采用“功能域+层次化”组织方式，核心目录如下：
- core/db：SQLite异步封装、去重与更新时间记录
- core/models：类型别名（如NotionDate）
- core/data：公告抓取、PDF分片
- core/notebook：Notion客户端、文件上传、时间工具、页面构建、资讯流数据库操作
- core/announcements_data_handler.py：公告数据处理主流程
- main.py：入口程序，调度各模块

```mermaid
graph TB
subgraph "应用入口"
M["main.py"]
end
subgraph "数据层"
D1["core/db/__init__.py"]
D2["core/models/__init__.py"]
end
subgraph "数据采集"
C1["core/data/announcement.py"]
C2["core/data/pdf_split.py"]
end
subgraph "Notion集成"
N1["core/notebook/stock_pool.py"]
N2["core/notion/client.py"]
N3["core/notion/upload_file.py"]
N4["core/notion/datetime_helper.py"]
N5["core/notion/content_builder.py"]
N6["core/notion/flow_databse.py"]
end
subgraph "编排"
P1["core/announcements_data_handler.py"]
end
M --> P1
P1 --> C1
P1 --> C2
P1 --> N1
P1 --> N3
P1 --> N6
N3 --> N2
N6 --> N2
N4 --> D2
P1 --> D1
```

图表来源
- [main.py](file://main.py#L20-L39)
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L21-L115)
- [core/data/announcement.py](file://core/data/announcement.py#L36-L112)
- [core/data/pdf_split.py](file://core/data/pdf_split.py#L15-L73)
- [core/notebook/stock_pool.py](file://core/notebook/stock_pool.py#L23-L51)
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L28-L179)
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py#L25-L66)
- [core/notion/client.py](file://core/notion/client.py#L1-L6)
- [core/db/__init__.py](file://core/db/__init__.py#L62-L217)
- [core/models/__init__.py](file://core/models/__init__.py#L1-L8)

章节来源
- [main.py](file://main.py#L1-L40)
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L1-L116)

## 核心组件
- Notion API客户端封装：基于AsyncClient封装全局实例，供上传与页面操作使用
- 文件上传策略：外链直传与本地上传两条路径，支持并发与轮询状态
- PDF分片：针对大文件按页数切分，避免单文件过大导致上传失败
- 时间处理：统一时区与时序转换，保证与Notion日期字段一致
- 页面构建：内容块构建器，支持标题、段落、表格、分隔线、Callout
- 资讯流数据库：创建页面、写入属性与附件
- 数据库接口：SQLite异步封装、去重与更新时间记录

章节来源
- [core/notion/client.py](file://core/notion/client.py#L1-L6)
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L28-L179)
- [core/data/pdf_split.py](file://core/data/pdf_split.py#L15-L127)
- [core/notion/datetime_helper.py](file://core/notion/datetime_helper.py#L12-L38)
- [core/notion/content_builder.py](file://core/notion/content_builder.py#L1-L103)
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py#L25-L66)
- [core/db/__init__.py](file://core/db/__init__.py#L62-L217)

## 架构总览
下图展示了从入口到数据落地的完整流程：获取股票池 → 抓取公告 → 分片/直传 → 创建资讯流页面。

```mermaid
sequenceDiagram
participant Entrypoint as "入口(main.py)"
participant Handler as "公告处理器(announcements_data_handler.py)"
participant Data as "公告采集(core/data/announcement.py)"
participant Split as "PDF分片(core/data/pdf_split.py)"
participant Pool as "股票池(core/notebook/stock_pool.py)"
participant Up as "文件上传(core/notion/upload_file.py)"
participant DB as "数据库(core/db/__init__.py)"
participant Notion as "Notion(FlowDatabase)"
Entrypoint->>Handler : 调用处理函数
Handler->>DB : 读取各股票更新时间
Handler->>Pool : 获取股票池
Handler->>Data : 按时间段批量抓取公告
Data-->>Handler : 返回公告列表
Handler->>Split : 对大文件进行分片
Split-->>Handler : 返回分片后的公告
Handler->>Up : 外链直传/本地上传(并发)
Up-->>Handler : 返回文件ID与状态
Handler->>Notion : 创建资讯流页面(写入属性与附件)
Notion-->>Handler : 成功/失败
Handler->>DB : 更新各股票更新时间
```

图表来源
- [main.py](file://main.py#L20-L39)
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L21-L115)
- [core/data/announcement.py](file://core/data/announcement.py#L36-L112)
- [core/data/pdf_split.py](file://core/data/pdf_split.py#L15-L73)
- [core/notebook/stock_pool.py](file://core/notebook/stock_pool.py#L23-L51)
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L28-L179)
- [core/db/__init__.py](file://core/db/__init__.py#L153-L217)
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py#L25-L66)

## 详细组件分析

### Notion API客户端封装
- 作用：提供全局异步客户端实例，供上传与页面操作使用
- 关键点：从环境变量读取令牌，构造AsyncClient实例
- 使用位置：文件上传、页面创建、数据源查询

章节来源
- [core/notion/client.py](file://core/notion/client.py#L1-L6)

### 文件上传策略与服务端上传机制
- 两条上传路径：
  - 外链直传：通过Notion文件上传接口的external_url模式，由Notion侧拉取文件
  - 本地上传：先下载文件内容，再调用Notion文件上传接口进行二进制上传
- 并发与聚合：对外提供upload_files_with_url与upload_files_with_local，内部使用asyncio.gather并发执行
- 轮询状态：上传后通过轮询查询上传状态，指数退避等待，最多16秒
- 结果结构：返回包含文件ID、成功标志与错误信息的结构化结果

```mermaid
flowchart TD
Start(["开始"]) --> Decide{"选择上传策略"}
Decide --> |外链| Ext["创建external_url上传任务"]
Decide --> |本地| Loc["下载文件内容"]
Ext --> PollExt["轮询上传状态"]
Loc --> UploadBin["二进制上传"]
UploadBin --> PollBin["轮询上传状态"]
PollExt --> ResultExt["汇总结果"]
PollBin --> ResultLoc["汇总结果"]
ResultExt --> End(["结束"])
ResultLoc --> End
```

图表来源
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L28-L179)

章节来源
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L28-L179)

### PDF分片与文件ID管理
- 分片策略：当公告文件大小超过阈值且标题命中关键词时，进行分片；否则直接使用原文件
- 分片算法：按固定块大小与重叠页数切分，生成带页码范围的新标题
- 文件ID管理：上传完成后返回包含file_id的结果，后续用于页面属性中的附件字段

章节来源
- [core/data/pdf_split.py](file://core/data/pdf_split.py#L15-L127)
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L66-L93)

### 时间处理工具与统一时区
- 统一时区：默认东八区，确保与Notion日期字段一致
- 转换函数：
  - Python datetime/date → NotionDate（带毫秒精度的ISO字符串）
  - NotionDate → Python datetime
- 应用：资讯流页面创建时，发布时间统一转换为NotionDate

章节来源
- [core/notion/datetime_helper.py](file://core/notion/datetime_helper.py#L12-L38)
- [core/models/__init__.py](file://core/models/__init__.py#L1-L8)
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py#L48-L54)

### 页面内容构建器
- 支持：标题、段落、表格、分隔线、Callout
- 用途：将结构化数据渲染为Notion页面的blocks数组
- 注意：表格构建依赖pandas，需在环境中安装

章节来源
- [core/notion/content_builder.py](file://core/notion/content_builder.py#L1-L103)

### 资讯流数据库操作
- 功能：在指定数据源（数据库）中创建页面，写入标题、发布时间、来源接口、数据类型、关联股票、附件与正文内容
- 关键点：数据类型映射、附件字段使用file_upload.id、日期字段使用转换后的NotionDate

章节来源
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py#L25-L66)

### 数据库接口与更新时间记录
- 初始化：创建update_records与hash两张表
- 去重：计算内容哈希，查询并过滤重复数据
- 更新时间：按股票与键读取/更新最近更新时间，用于增量抓取

章节来源
- [core/db/__init__.py](file://core/db/__init__.py#L62-L217)

### 股票池获取
- 从Notion数据源查询股票池，提取ID与代码，封装为StockPool对象
- 用于公告抓取时的分组与关联

章节来源
- [core/notebook/stock_pool.py](file://core/notebook/stock_pool.py#L23-L51)

### 公告数据处理主流程
- 增量策略：根据各股票上次更新时间分组抓取，减少请求次数
- 上传策略选择：
  - 小文件或非分片关键词：外链直传
  - 大文件且命中分片关键词：本地分片上传
- 页面创建：并发创建资讯流页面，写入附件ID与来源信息

```mermaid
sequenceDiagram
participant H as "处理器"
participant G as "抓取(get_announcements)"
participant S as "分片(split_pdf)"
participant U as "上传(upload_files_with_url/local)"
participant F as "创建(create_dataflow_page)"
H->>G : 按时间窗口抓取公告
G-->>H : 返回公告列表
H->>S : 对大文件进行分片
S-->>H : 返回分片后的公告
H->>U : 并发外链/本地上传
U-->>H : 返回文件ID列表
H->>F : 并发创建页面(写入附件ID)
```

图表来源
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L21-L115)
- [core/data/announcement.py](file://core/data/announcement.py#L36-L112)
- [core/data/pdf_split.py](file://core/data/pdf_split.py#L15-L73)
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L28-L179)
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py#L25-L66)

章节来源
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L21-L115)

## 依赖关系分析
- 模块内聚与耦合：
  - 公告处理器依赖数据采集、PDF分片、股票池、文件上传、数据库与Notion操作
  - 文件上传与资讯流页面均依赖Notion客户端
  - 时间工具与模型类型被多处共享
- 外部依赖：
  - 异步HTTP：httpx
  - PDF处理：PyMuPDF
  - 异步SQLite：aiosqlite
  - 哈希：xxhash
  - Notion SDK：notion-client

```mermaid
graph LR
A["core/announcements_data_handler.py"] --> B["core/data/announcement.py"]
A --> C["core/data/pdf_split.py"]
A --> D["core/notebook/stock_pool.py"]
A --> E["core/notion/upload_file.py"]
A --> F["core/notion/flow_databse.py"]
E --> G["core/notion/client.py"]
F --> G
A --> H["core/db/__init__.py"]
I["core/notion/datetime_helper.py"] --> J["core/models/__init__.py"]
A --> I
```

图表来源
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L1-L116)
- [core/data/announcement.py](file://core/data/announcement.py#L1-L141)
- [core/data/pdf_split.py](file://core/data/pdf_split.py#L1-L128)
- [core/notebook/stock_pool.py](file://core/notebook/stock_pool.py#L1-L52)
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L1-L180)
- [core/notion/flow_databse.py](file://core/notion/flow_databse.py#L1-L67)
- [core/notion/client.py](file://core/notion/client.py#L1-L6)
- [core/db/__init__.py](file://core/db/__init__.py#L1-L218)
- [core/notion/datetime_helper.py](file://core/notion/datetime_helper.py#L1-L39)
- [core/models/__init__.py](file://core/models/__init__.py#L1-L8)

## 性能考量
- 并发优化：
  - 抓取阶段：对同一时间段内的多股票并行请求
  - 上传阶段：外链与本地上传分别并发执行
  - 页面创建：并发创建资讯流页面
- I/O优化：
  - PDF分片在内存中进行，避免磁盘IO
  - 上传轮询采用指数退避，降低无效请求
- 存储优化：
  - 哈希去重减少重复上传
  - 增量更新时间记录，缩小抓取窗口

## 故障排查指南
- 环境变量缺失：
  - NOTION_TOKEN：导致Notion客户端无法初始化
  - STOCK_POOL/数据库环境变量：影响股票池与数据库路径
- 网络与权限：
  - 公告接口限流或返回异常：检查CNINFO接口可用性
  - PDF下载失败：确认URL可达与防盗链策略
- 上传失败：
  - 外链直传失败：检查URL有效性与跨域
  - 本地上传失败：查看轮询超时与错误信息
- 数据库问题：
  - 初始化失败：确认数据库目录可写
  - 哈希冲突：确认内容序列化一致性

章节来源
- [core/notion/client.py](file://core/notion/client.py#L1-L6)
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L153-L176)
- [core/db/__init__.py](file://core/db/__init__.py#L62-L94)

## 结论
本模块通过清晰的职责划分与并发设计，实现了从公告抓取、PDF分片、文件上传到资讯流页面创建的完整闭环。统一的时间处理与去重机制提升了稳定性与效率。建议在生产环境中结合监控与告警，进一步完善重试与熔断策略。

## 附录

### API限制与重试机制
- 上传轮询：最多尝试若干次，指数退避等待，超时返回失败
- 并发控制：合理设置并发度，避免触发Notion速率限制
- 错误分类：区分网络错误、Notion返回错误与解析错误，分别处理

章节来源
- [core/notion/upload_file.py](file://core/notion/upload_file.py#L153-L176)

### 上传策略选择逻辑
- 小于阈值或不命中分片关键词：外链直传
- 大于阈值且命中分片关键词：本地分片上传
- 分片规则：固定块大小与重叠页数，生成带页码范围的标题

章节来源
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L66-L93)
- [core/data/pdf_split.py](file://core/data/pdf_split.py#L15-L73)

### 数据同步流程要点
- 增量抓取：按股票维度记录更新时间，仅抓取新增公告
- 去重：对内容计算哈希，避免重复上传与页面创建
- 并发落地：上传与页面创建并行，提升吞吐

章节来源
- [core/db/__init__.py](file://core/db/__init__.py#L97-L151)
- [core/announcements_data_handler.py](file://core/announcements_data_handler.py#L27-L63)