# 注意：notion 使用懒加载，通过 __getattr__ 在 core.notion.client 中实现
# 直接导入会导致客户端被创建，所以这里不导入 notion
from .content_builder import NotionContentBuilder
from .datetime_helper import (
    convert_datetime_to_notion_date,
    convert_notion_date_to_datetime,
    # 向后兼容别名
    cover_datetime_to_notion_date,
    cover_notion_date_to_datetime,
)
from .flow_database import create_dataflow_page
from .stock_pool import StockPool, get_stock_pool
from .upload_file import upload_files_with_local, upload_files_with_url


def __getattr__(name: str):
    """实现包级别的懒加载。"""
    if name == "notion":
        from .client import notion as _notion
        return _notion
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # "notion" 通过 __getattr__ 懒加载，不直接导出
    "get_stock_pool",
    "create_dataflow_page",
    "NotionContentBuilder",
    "convert_datetime_to_notion_date",
    "convert_notion_date_to_datetime",
    "cover_datetime_to_notion_date",
    "cover_notion_date_to_datetime",
    "StockPool",
    "upload_files_with_url",
    "upload_files_with_local",
]
