"""
静态资源管理模块

提供统一的静态资源管理机制，支持：
- 资源元数据管理（版本、类型、创建时间、描述等）
- 资源类型自动判断
- 资源加载和保存
- 基于类的资源定义
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Generic, TypeVar


class ResourceType(Enum):
    """资源类型枚举"""

    DATAFRAME = auto()  # pandas DataFrame
    JSON = auto()  # JSON 数据
    PICKLE = auto()  # 任意 Python 对象
    RESPONSE = auto()  # HTTP 响应数据
    TEXT = auto()  # 文本内容
    BINARY = auto()  # 二进制数据


@dataclass(frozen=True)
class ResourceMeta:
    """
    资源元数据类

    属性:
        name: 资源名称
        resource_type: 资源类型
        version: 版本号，格式为 "major.minor.patch"
        created_at: 创建时间 ISO 格式
        description: 资源描述
        source: 数据来源（如 API 端点、股票代码等）
        tags: 标签列表
    """

    name: str
    resource_type: ResourceType
    version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""
    source: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """转换为字典"""
        return {
            "name": self.name,
            "resource_type": self.resource_type.name,
            "version": self.version,
            "created_at": self.created_at,
            "description": self.description,
            "source": self.source,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ResourceMeta:
        """从字典创建"""
        raw_tags = data.get("tags", [])
        tags = tuple(str(t) for t in raw_tags) if isinstance(raw_tags, list) else ()
        resource_type_str = str(data.get("resource_type", "PICKLE"))
        return cls(
            name=str(data["name"]),
            resource_type=ResourceType[resource_type_str],
            version=str(data.get("version", "1.0.0")),
            created_at=str(data.get("created_at", datetime.now().isoformat())),
            description=str(data.get("description", "")),
            source=str(data.get("source", "")),
            tags=tags,
        )


T = TypeVar("T")


@dataclass
class StaticResource(Generic[T]):
    """
    静态资源容器类

    属性:
        meta: 资源元数据
        data: 实际数据
    """

    meta: ResourceMeta
    data: T

    def is_type(self, expected_type: type[object]) -> bool:
        """判断数据是否为指定类型"""
        return isinstance(self.data, expected_type)

    def get_data(self, expected_type: type[T] | None = None) -> T:
        """
        获取数据，可选类型检查

        Args:
            expected_type: 期望的数据类型，如果提供会进行类型检查

        Raises:
            TypeError: 如果类型不匹配
        """
        if expected_type is not None and not isinstance(self.data, expected_type):
            raise TypeError(
                f"资源 {self.meta.name} 类型不匹配: "
                f"期望 {expected_type.__name__}, 实际 {type(self.data).__name__}"
            )
        return self.data


class ResourceManager:
    """
    静态资源管理器

    管理测试静态资源的加载、保存和元数据。
    资源文件结构：
        resource/
        ├── manager.py          # 本文件
        ├── __init__.py
        ├── {name}.pkl          # 数据文件
        └── {name}.meta.json    # 元数据文件
    """

    resource_dir: Path
    _cache: dict[str, StaticResource[object]]

    def __init__(self, resource_dir: Path | None = None):
        """
        初始化资源管理器

        Args:
            resource_dir: 资源目录路径，默认为当前文件所在目录
        """
        if resource_dir is None:
            resource_dir = Path(__file__).parent
        self.resource_dir = Path(resource_dir)
        self._cache = {}

    def _get_pickle_path(self, name: str) -> Path:
        """获取 pickle 文件路径"""
        return self.resource_dir / f"{name}.pkl"

    def _get_meta_path(self, name: str) -> Path:
        """获取元数据文件路径"""
        return self.resource_dir / f"{name}.meta.json"

    def save(
        self,
        name: str,
        data: object,
        resource_type: ResourceType,
        version: str = "1.0.0",
        description: str = "",
        source: str = "",
        tags: list[str] | None = None,
        use_cache: bool = True,
    ) -> StaticResource[object]:
        """
        保存资源到文件

        Args:
            name: 资源名称
            data: 要保存的数据
            resource_type: 资源类型
            version: 版本号
            description: 资源描述
            source: 数据来源
            tags: 标签列表
            use_cache: 是否缓存到内存

        Returns:
            StaticResource: 资源对象
        """
        meta = ResourceMeta(
            name=name,
            resource_type=resource_type,
            version=version,
            description=description,
            source=source,
            tags=tuple(tags or []),
        )

        resource: StaticResource[object] = StaticResource(meta=meta, data=data)

        # 保存 pickle 数据
        pickle_path = self._get_pickle_path(name)
        with open(pickle_path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

        # 保存元数据
        meta_path = self._get_meta_path(name)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)

        # 缓存
        if use_cache:
            self._cache[name] = resource

        return resource

    def load(
        self,
        name: str,
        expected_type: type[T] | None = None,
        use_cache: bool = True,
    ) -> StaticResource[T]:
        """
        加载资源

        Args:
            name: 资源名称
            expected_type: 期望的数据类型
            use_cache: 是否使用缓存

        Returns:
            StaticResource: 资源对象

        Raises:
            FileNotFoundError: 资源文件不存在
            TypeError: 类型不匹配（当 expected_type 指定时）
        """
        # 检查缓存
        if use_cache and name in self._cache:
            resource = self._cache[name]
            if expected_type is not None:
                resource.get_data(expected_type)
            return resource  # pyright: ignore[reportReturnType]

        # 加载元数据
        meta_path = self._get_meta_path(name)
        if not meta_path.exists():
            raise FileNotFoundError(f"资源元数据不存在: {meta_path}")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta_data: dict[str, object] = json.load(f)
            meta = ResourceMeta.from_dict(meta_data)

        # 加载数据
        pickle_path = self._get_pickle_path(name)
        if not pickle_path.exists():
            raise FileNotFoundError(f"资源数据不存在: {pickle_path}")

        with open(pickle_path, "rb") as f:
            data: object = pickle.load(f)  # noqa: S301

        resource_obj: StaticResource[object] = StaticResource(meta=meta, data=data)

        # 类型检查
        if expected_type is not None:
            resource_obj.get_data(expected_type)

        # 缓存
        if use_cache:
            self._cache[name] = resource_obj

        return resource_obj  # pyright: ignore[reportReturnType]

    def exists(self, name: str) -> bool:
        """检查资源是否存在"""
        return (
            self._get_pickle_path(name).exists() and self._get_meta_path(name).exists()
        )

    def get_meta(self, name: str) -> ResourceMeta:
        """仅获取资源元数据"""
        meta_path = self._get_meta_path(name)
        with open(meta_path, "r", encoding="utf-8") as f:
            meta_data: dict[str, object] = json.load(f)
            return ResourceMeta.from_dict(meta_data)

    def list_resources(self) -> list[str]:
        """列出所有资源名称"""
        resources: list[str] = []
        for meta_file in self.resource_dir.glob("*.meta.json"):
            resources.append(meta_file.stem.replace(".meta", ""))
        return sorted(resources)

    def clear_cache(self) -> None:
        """清空内存缓存"""
        self._cache.clear()


# 全局资源管理器实例
resource_manager = ResourceManager()


# 便捷函数
def save_resource(
    name: str,
    data: object,
    resource_type: ResourceType,
    version: str = "1.0.0",
    description: str = "",
    source: str = "",
    tags: list[str] | None = None,
    use_cache: bool = True,
) -> StaticResource[object]:
    """使用全局管理器保存资源"""
    return resource_manager.save(
        name,
        data,
        resource_type,
        version=version,
        description=description,
        source=source,
        tags=tags,
        use_cache=use_cache,
    )


def load_resource(
    name: str,
    expected_type: type[T] | None = None,
    use_cache: bool = True,
) -> StaticResource[T]:
    """使用全局管理器加载资源"""
    return resource_manager.load(name, expected_type, use_cache=use_cache)
