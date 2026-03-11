"""SQLAlchemy TypeDecorator 类型定义。

提供 JSON 序列化/反序列化支持，用于 ORM 模型中的 JSON 字段。
"""

from __future__ import annotations

from dataclasses import Field, asdict, is_dataclass
from typing import (
    Any,
    ClassVar,
    Protocol,
    TypeVar,
    cast,
    final,
    get_args,
    get_origin,
    get_type_hints,
    overload,
    override,
)

from pydantic import BaseModel
from sqlalchemy import Dialect
from sqlalchemy.types import JSON, TypeDecorator

T = TypeVar("T", bound=object)


class DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]  # pyright: ignore[reportExplicitAny]


@final
class JsonDataclassList[T: DataclassInstance](TypeDecorator[list[T]]):
    impl = JSON
    cache_ok = True
    _dc_class: type[T]

    def __init__(self, dc_class: type[T]) -> None:
        super().__init__()
        self._dc_class = dc_class

    @override
    def process_bind_param(
        self, value: list[T] | None, dialect: Dialect
    ) -> list[dict[str, Any]] | None:  # pyright: ignore[reportExplicitAny]
        if value is None:
            return None
        return [asdict(item) for item in value]

    @override
    def process_result_value(
        self,
        value: list[dict[str, Any]] | None,  # pyright: ignore[reportExplicitAny]
        dialect: Dialect,
    ) -> list[T] | None:
        if value is None:
            return None
        return [_reconstruct_dataclass(self._dc_class, item) for item in value]


@final
class JsonDataclass[T: DataclassInstance](TypeDecorator[T]):
    impl = JSON
    cache_ok = True
    _dc_class: type[T]

    def __init__(self, dc_class: type[T]) -> None:
        super().__init__()
        self._dc_class = dc_class

    @override
    def process_bind_param(
        self, value: T | None, dialect: Dialect
    ) -> dict[str, Any] | None:  # pyright: ignore[reportExplicitAny]
        if value is None:
            return None
        return asdict(value)

    @override
    def process_result_value(
        self,
        value: dict[str, Any] | None,  # pyright: ignore[reportExplicitAny]
        dialect: Dialect,
    ) -> T | None:
        if value is None:
            return None
        return _reconstruct_dataclass(self._dc_class, value)


@final
class JsonPydanticModelList[T: BaseModel](TypeDecorator[list[T]]):
    impl = JSON
    cache_ok: bool | None = True
    _model_class: type[T]

    def __init__(self, model_class: type[T]) -> None:
        super().__init__()
        self._model_class = model_class

    @override
    def process_bind_param(
        self, value: list[T] | None, dialect: Dialect
    ) -> list[dict[str, Any]] | None:  # pyright: ignore[reportExplicitAny]
        if value is None:
            return None
        return [item.model_dump(mode="json") for item in value]

    @override
    def process_result_value(
        self,
        value: list[dict[str, Any]] | None,  # pyright: ignore[reportExplicitAny]
        dialect: Dialect,
    ) -> list[T] | None:
        if value is None:
            return None
        return [self._model_class.model_validate(item) for item in value]


@final
class JsonPydanticModel[T: BaseModel](TypeDecorator[T]):
    """泛型 JSON 序列化的 Pydantic 模型类型。

    用于存储任意 Pydantic BaseModel，在数据库中以 JSON 形式保存。
    序列化使用 model_dump()，反序列化使用 model_validate()。

    使用方式：
    - 具体类型：直接用 Pydantic BaseModel 实例化此类
    """

    impl = JSON
    cache_ok = True
    _model_class: type[T]

    def __init__(self, model_class: type[T]) -> None:
        """
        初始化时传入 Pydantic BaseModel
        """
        super().__init__()
        self._model_class = model_class

    @override
    def process_bind_param(
        self, value: T | None, dialect: Dialect
    ) -> dict[str, Any] | None:  # pyright: ignore[reportExplicitAny]
        if value is None:
            return None
        return value.model_dump(mode="json")

    @override
    def process_result_value(
        self,
        value: dict[str, Any] | None,  # pyright: ignore[reportExplicitAny]
        dialect: Dialect,
    ) -> T | None:
        if value is None:
            return None
        # 使用运行时获取的模型类进行验证
        return self._model_class.model_validate(value)


def _coerce_value(annotation: type, value: Any) -> Any:  # pyright: ignore[reportAny, reportExplicitAny]
    """
    根据目标的类型标注，将Json值还原为正确的Python类型
    """
    if value is None:
        return None
    origin = get_origin(annotation)
    if origin is tuple:
        args = get_args(annotation)
        if not args:
            # tuple 无参
            return tuple(value)  # pyright: ignore[reportAny]
        if len(args) == 2 and args[1] is Ellipsis:
            # tuple[X, ...] 单一类型
            return tuple(_coerce_value(args[0], v) for v in value)  # pyright: ignore[reportAny]
        # tuple[X, Y, Z] 每个元素与其类型单独走还原
        return tuple(_coerce_value(t, v) for t, v in zip(args, value, strict=True))  # pyright: ignore[reportAny]
    if origin is list:
        # list[X] 单一类型，每个元素单独走还原
        (item_type,) = get_args(annotation)  # pyright: ignore[reportAny]
        return [_coerce_value(item_type, v) for v in value]  # pyright: ignore[reportAny]

    if is_dataclass(annotation) and isinstance(value, dict):
        # dataclass嵌套
        return _reconstruct_dataclass(annotation, value)  # pyright: ignore[reportUnknownArgumentType]
    # 其余类型直接返回
    return value  # pyright: ignore[reportAny]


def _reconstruct_dataclass[T: DataclassInstance](
    dc: type[T],
    data: dict[str, Any],  # pyright: ignore[reportExplicitAny]
) -> T:
    """
    将一个Json反序列化的产物 data: dict 还原成目标 dc 类型的实例

    """
    resolved = get_type_hints(dc)
    kwargs = {}
    for name, val in data.items():  # pyright: ignore[reportAny]
        if name in resolved:
            kwargs[name] = _coerce_value(resolved[name], val)  # pyright: ignore[reportAny]
        else:
            kwargs[name] = val

    return dc(**kwargs)


@overload
def json_pydantic[T: BaseModel](typ: type[T]) -> JsonPydanticModel[T]: ...


@overload
def json_pydantic[T: BaseModel](typ: type[list[T]]) -> JsonPydanticModelList[T]: ...


def json_pydantic(typ: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny]
    origin = get_origin(typ)  # pyright: ignore[reportAny]
    if origin is list:
        (item_type,) = get_args(typ)  # pyright: ignore[reportAny]
        if not (isinstance(item_type, type) and issubclass(item_type, BaseModel)):
            raise TypeError(f"Expected list[BaseModelSubclass], got {typ!r}")
        return JsonPydanticModelList(item_type)
    if not (isinstance(typ, type) and issubclass(typ, BaseModel)):
        raise TypeError(f"Expected BaseModel subclass, got {typ!r}")
    return JsonPydanticModel(typ)


@overload
def json_dataclass[T: DataclassInstance](typ: type[T]) -> JsonDataclass[T]: ...


@overload
def json_dataclass[T: DataclassInstance](
    typ: type[list[T]],
) -> JsonDataclassList[T]: ...


def json_dataclass(typ: Any) -> Any:  # pyright: ignore[reportAny, reportExplicitAny]
    origin = get_origin(typ)  # pyright: ignore[reportAny]
    if origin is list:
        (item_type,) = get_args(typ)  # pyright: ignore[reportAny]
        if not is_dataclass(item_type):  # pyright: ignore[reportAny]
            raise TypeError(f"Expected list[dataclass], got {typ!r}")
        return JsonDataclassList(cast(type[DataclassInstance], item_type))
    if not is_dataclass(typ):  # pyright: ignore[reportAny]
        raise TypeError(f"Expected dataclass, got {typ!r}")
    return JsonDataclass(cast(type[DataclassInstance], typ))
