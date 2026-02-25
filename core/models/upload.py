"""文件上传相关的共享数据模型。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FileUploadRequest:
    """外链文件上传请求。

    Attributes:
        stock: 股票代码。
        url: 文件的外部 URL。
        title: 文件标题。
        published_date: 公告发布日期。
        hash_content: 用于去重的哈希内容标识。
    """

    stock: str
    url: str
    title: str
    published_date: datetime
    hash_content: str


@dataclass(frozen=True)
class FileUploadWithContent:
    """带有二进制内容的本地文件上传请求。

    Attributes:
        stock: 股票代码。
        url: 文件的原始 URL。
        title: 文件标题。
        published_date: 公告发布日期。
        hash_content: 用于去重的哈希内容标识。
        content: 文件的二进制内容。
    """

    stock: str
    url: str
    title: str
    published_date: datetime
    hash_content: str
    content: bytes


@dataclass(frozen=True)
class FileUploadResult:
    """文件上传结果。

    Attributes:
        stock: 股票代码。
        url: 文件的原始 URL。
        title: 文件标题。
        published_date: 公告发布日期。
        hash_content: 用于去重的哈希内容标识。
        file_id: Notion 文件上传任务 ID。
        succeeded: 上传是否成功。
        error: 失败时的错误信息，成功时为 None。
    """

    stock: str
    url: str
    title: str
    published_date: datetime
    hash_content: str
    file_id: str
    succeeded: bool
    error: str | None
