"""SQLAlchemy TypeDecorator 类型定义。

提供 JSON 序列化/反序列化支持，用于 ORM 模型中的 JSON 字段。
"""

from dataclasses import asdict
from typing import Generic, TypeVar

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

from core.data.models import ChunkMeta
from core.data.summary_models import ChunkSummaryOutput, KeyDataItem

T = TypeVar("T", bound=object)


class JsonStringList(TypeDecorator):
    """JSON 序列化的字符串列表类型。

    用于存储 Python list，在数据库中以 JSON 形式保存。
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: list[str] | None, dialect) -> list[str] | None:
        if value is None:
            return None
        return value

    def process_result_value(self, value: list | None, dialect) -> list[str] | None:
        if value is None:
            return None
        return value


class JsonChunkMetaList(TypeDecorator):
    """JSON 序列化的 ChunkMeta 列表类型。

    用于存储 ChunkMeta 列表，在数据库中以 JSON 形式保存。
    反序列化时将 page_range 从 list 转换为 tuple。
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: list[ChunkMeta] | None, dialect) -> list[dict] | None:
        if value is None:
            return None
        return [asdict(chunk) for chunk in value]

    def process_result_value(self, value: list | None, dialect) -> list[ChunkMeta] | None:
        if value is None:
            return None
        return [
            ChunkMeta(
                title=item["title"],
                level=item["level"],
                page_range=tuple(item["page_range"]),
            )
            for item in value
        ]


class JsonKeyDataItemList(TypeDecorator):
    """JSON 序列化的 KeyDataItem 列表类型。

    用于存储 KeyDataItem 列表，在数据库中以 JSON 形式保存。
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: list[KeyDataItem] | None, dialect) -> list[dict] | None:
        if value is None:
            return None
        return [item.model_dump() for item in value]

    def process_result_value(self, value: list | None, dialect) -> list[KeyDataItem] | None:
        if value is None:
            return None
        return [KeyDataItem.model_validate(item) for item in value]


class JsonPydanticModel(TypeDecorator, Generic[T]):
    """泛型 JSON 序列化的 Pydantic 模型类型。

    用于存储任意 Pydantic BaseModel，在数据库中以 JSON 形式保存。
    序列化使用 model_dump()，反序列化使用 model_validate()。

    使用方式：
    - 具体类型：直接继承此类并指定 T
    - 或使用 `JsonChunkSummaryOutput` 具体类
    """

    impl = JSON
    cache_ok = True
    _model_class: type | None = None

    def __init__(self, model_class: type[T] | None = None, *args: object, **kwargs: object):
        """初始化时可选传入模型类。"""
        super().__init__(*args, **kwargs)
        if model_class is not None:
            self._model_class = model_class

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # 捕获第一个类型参数（如果有）

    @property
    def model_class(self) -> type:
        """获取要处理的 Pydantic 模型类。"""
        if self._model_class is not None:
            return self._model_class
        # 如果没有设置，尝试从类继承获取
        for base in type(self).__mro__:
            if hasattr(base, "__orig_bases__"):
                for orig in base.__orig_bases__:
                    if hasattr(orig, "__origin__") and orig.__origin__ is JsonPydanticModel:
                        args = getattr(orig, "__args__", ())
                        if args:
                            return args[0]
        raise ValueError(f"Cannot determine model class for {type(self)}")

    def process_bind_param(self, value: T | None, dialect) -> dict | None:
        if value is None:
            return None
        return value.model_dump()

    def process_result_value(self, value: dict | None, dialect) -> T | None:
        if value is None:
            return None
        # 使用运行时获取的模型类进行验证
        model_class = self.model_class
        return model_class.model_validate(value)


# 具体实现：ChunkSummaryOutput 类型
class JsonChunkSummaryOutput(JsonPydanticModel[ChunkSummaryOutput]):
    """用于 ChunkSummaryOutput 的具体 TypeDecorator。"""

    _model_class = ChunkSummaryOutput
