"""公告工具集的共享数据类型。"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# ── LLM 可选的公告类型枚举（Literal）─────────────────

CategoryName = Literal[
    "年报", "半年报", "一季报", "三季报", "业绩预告", "权益分派",
    "董事会", "监事会", "股东会", "日常经营", "公司治理", "中介报告",
    "首发", "增发", "股权激励", "配股", "解禁", "公司债",
    "可转债", "其他融资", "股权变动", "补充更正", "澄清致歉", "风险提示",
    "特别处理和退市", "退市整理期",
]

# ── Pydantic args_schema（LLM 看到的 tool input schema）─────

class SearchInput(BaseModel):
    """搜索公告的输入参数。"""
    keyword: str = Field(default="", description="搜索关键词")
    stock_code: str = Field(default="", description="股票代码（如 600519）")
    category: list[CategoryName] | None = Field(
        default=None,
        description="公告类型筛选列表，传入 None 则不限类型",
    )
    start_date: date | None = Field(
        default=None,
        description="开始日期，格式 YYYY-MM-DD，不填则默认近一年",
    )
    end_date: date | None = Field(
        default=None,
        description="结束日期，格式 YYYY-MM-DD，不填则默认今天",
    )
    page: int = Field(default=1, description="页码，每页 30 条")

class GrepInput(BaseModel):
    """在公告全文中 grep 的输入参数。"""
    announcement_id: str = Field(description="公告 ID")
    pattern: str = Field(description="正则表达式搜索模式")
    ignore_case: bool = Field(default=True, description="不区分大小写")
    context_lines: int = Field(default=3, description="上下文行数，前后对称")
    before_context: int | None = Field(default=None, description="匹配前行数，覆盖 context_lines")
    after_context: int | None = Field(default=None, description="匹配后行数，覆盖 context_lines")
    head_limit: int = Field(default=50, description="限制返回的匹配数量")

class ReadInput(BaseModel):
    """读取公告全文的输入参数。"""
    announcement_id: str = Field(description="公告 ID")
    offset: int = Field(default=1, description="起始行号")
    limit: int = Field(default=200, description="读取行数限制")

# ── 业务数据类 ─────────────────────────────────

@dataclass(frozen=True)
class AnnouncementInfo:
    """公告搜索结果条目。

    Attributes:
        announcement_id: 巨潮资讯网公告唯一标识。
        stock_code: 股票代码。
        stock_name: 股票简称。
        title: 公告标题。
        published_date: 发布日期。
        pdf_url: PDF 下载链接。
        size_kb: 文件大小（KB）。
    """

    announcement_id: str
    stock_code: str
    stock_name: str
    title: str
    published_date: date
    pdf_url: str
    size_kb: int

@dataclass(frozen=True)
class GrepMatch:
    """grep 命中结果。

    Attributes:
        line_number: 命中行号（从 1 开始）。
        content: 命中行内容。
        context_before: 前置上下文行。
        context_after: 后置上下文行。
    """

    line_number: int
    content: str
    context_before: list[str]
    context_after: list[str]
