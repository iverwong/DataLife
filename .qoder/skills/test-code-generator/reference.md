# 测试代码生成器 - 参考文档

## 目录
1. [测试标记详解](#测试标记详解)
2. [Mock策略详细指南](#mock策略详细指南)
3. [异步测试模式](#异步测试模式)
4. [静态资源管理](#静态资源管理)
5. [常见问题处理](#常见问题处理)

## 测试标记详解

### 标记组合规范

```python
# 单元测试 + 异步 + 快速
@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fast
async def test_something():
    pass

# 集成测试 + 异步 + 慢速 + 真实网络
@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.slow
@pytest.mark.real_network
async def test_real_api():
    pass
```

### 运行指定标记的测试

```bash
# 只运行单元测试
pytest -m unit

# 排除慢速测试
pytest -m "not slow"

# 只运行集成测试且需要真实网络
pytest -m "integration and real_network"
```

## Mock策略详细指南

### 决策矩阵

| 依赖类型 | 建议策略 | 理由 | 必须集成测试 |
|---------|---------|------|------------|
| HTTP API (外部) | Mock | 不稳定、有速率限制 | 是 |
| 数据库 (SQLite本地) | 真实 | 轻量、可控 | 否 |
| 数据库 (远程) | Mock | 网络依赖 | 是 |
| 文件系统 (临时文件) | 真实 | 本地可控 | 否 |
| 文件系统 (系统文件) | Mock | 环境差异 | 是 |
| CPU密集型计算 | 真实 | 核心逻辑 | 否 |
| 时间相关函数 | Mock | 确定性要求 | 是 |

### Mock实现示例

#### HTTP请求 (httpx)

```python
from unittest.mock import AsyncMock, Mock

# 方式1: 使用patch
with patch("httpx.AsyncClient.get") as mock_get:
    mock_get.return_value = Mock(
        status_code=200,
        json=lambda: {"data": "value"},
        text='{"data": "value"}'
    )
    result = await fetch_data()

# 方式2: 使用AsyncMock
with patch("httpx.AsyncClient.post") as mock_post:
    mock_post = AsyncMock(return_value=Mock(status_code=201))
    result = await create_resource()
```

#### 数据库操作

```python
# 使用内存数据库替代真实数据库
@pytest.fixture
async def db_connection():
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    yield conn
    await conn.close()
```

#### 时间函数

```python
from unittest.mock import patch
from datetime import datetime

with patch("datetime.datetime") as mock_dt:
    mock_dt.now.return_value = datetime(2026, 2, 16, 12, 0, 0)
    result = get_current_timestamp()
    assert result == "2026-02-16T12:00:00"
```

## 异步测试模式

### 基本模式

```python
import pytest

pytestmark = pytest.mark.asyncio  # 模块级别标记

async def test_async_function():
    result = await async_function()
    assert result is not None
```

### 使用pytest-asyncio的fixture

```python
@pytest_asyncio.fixture
async def async_resource():
    resource = await create_resource()
    yield resource
    await resource.cleanup()
```

### 并发测试

```python
async def test_concurrent_requests():
    tasks = [async_function(i) for i in range(10)]
    results = await asyncio.gather(*tasks)
    assert len(results) == 10
```

### 超时测试

```python
import asyncio

async def test_timeout():
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow_function(), timeout=1.0)
```

## 静态资源管理

### 资源目录结构

```
tests/resource/
├── __init__.py
├── manager.py              # 资源管理工具
├── fetch_*.py              # 资源获取脚本
├── *.pkl                   # Python对象序列化
├── *.json                  # JSON格式数据
└── *.meta.json             # 元数据
```

### 资源管理工具 (manager.py)

```python
"""静态资源管理工具.

提供统一的静态资源管理机制，支持：
- 资源元数据管理（版本、类型、创建时间、描述等）
- 资源类型自动判断
- 资源加载和保存
- 基于类的资源定义
"""

import pickle
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Generic, TypeVar, Any


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
    """资源元数据类
    
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


T = TypeVar("T")


@dataclass
class StaticResource(Generic[T]):
    """静态资源容器类
    
    属性:
        meta: 资源元数据
        data: 实际数据
    """
    meta: ResourceMeta
    data: T
    
    def get_data(self, expected_type: type[T] | None = None) -> T:
        """获取数据，可选类型检查"""
        if expected_type is not None and not isinstance(self.data, expected_type):
            raise TypeError(
                f"资源 {self.meta.name} 类型不匹配: "
                f"期望 {expected_type.__name__}, 实际 {type(self.data).__name__}"
            )
        return self.data


class ResourceManager:
    """静态资源管理器
    
    管理测试静态资源的加载、保存和元数据。
    资源文件结构：
        resource/
        ├── manager.py          # 本文件
        ├── __init__.py
        ├── {name}.pkl          # 数据文件
        └── {name}.meta.json    # 元数据文件
    """
    
    def __init__(self, resource_dir: Path | None = None):
        if resource_dir is None:
            resource_dir = Path(__file__).parent
        self.resource_dir = Path(resource_dir)
        self._cache: dict[str, StaticResource[Any]] = {}
    
    def save(
        self,
        name: str,
        data: Any,
        resource_type: ResourceType,
        version: str = "1.0.0",
        description: str = "",
        source: str = "",
        tags: list[str] | None = None,
        use_cache: bool = True,
    ) -> StaticResource[Any]:
        """保存资源到文件
        
        Args:
            name: 资源名称
            data: 要保存的数据
            resource_type: 资源类型（ResourceType枚举）
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
        
        resource: StaticResource[Any] = StaticResource(meta=meta, data=data)
        
        # 保存 pickle 数据
        pickle_path = self.resource_dir / f"{name}.pkl"
        with open(pickle_path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        
        # 保存元数据
        meta_path = self.resource_dir / f"{name}.meta.json"
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
        """加载资源
        
        Args:
            name: 资源名称
            expected_type: 期望的数据类型（用于类型检查）
            use_cache: 是否使用缓存
        
        Returns:
            StaticResource: 资源对象
        """
        # 检查缓存
        if use_cache and name in self._cache:
            resource = self._cache[name]
            if expected_type is not None:
                resource.get_data(expected_type)
            return resource  # type: ignore
        
        # 加载元数据
        meta_path = self.resource_dir / f"{name}.meta.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = ResourceMeta.from_dict(json.load(f))
        
        # 加载数据
        pickle_path = self.resource_dir / f"{name}.pkl"
        with open(pickle_path, "rb") as f:
            data = pickle.load(f)
        
        resource_obj: StaticResource[Any] = StaticResource(meta=meta, data=data)
        
        # 类型检查
        if expected_type is not None:
            resource_obj.get_data(expected_type)
        
        # 缓存
        if use_cache:
            self._cache[name] = resource_obj
        
        return resource_obj  # type: ignore
    
    def exists(self, name: str) -> bool:
        """检查资源是否存在"""
        return (
            (self.resource_dir / f"{name}.pkl").exists() and 
            (self.resource_dir / f"{name}.meta.json").exists()
        )
    
    def get_meta(self, name: str) -> ResourceMeta:
        """仅获取资源元数据"""
        meta_path = self.resource_dir / f"{name}.meta.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            return ResourceMeta.from_dict(json.load(f))
    
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
```

### 资源获取脚本模板

```python
"""获取XX资源的真实数据.

运行方式:
    cd tests/resource && python fetch_xx.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.resource.manager import ResourceManager, ResourceType


async def fetch_real_data():
    """执行真实请求."""
    # 导入实际模块
    from core.data.xxx import fetch_data
    
    # 执行真实调用
    result = await fetch_data()
    return result


async def main():
    """主函数."""
    print("Fetching real data...")
    
    data = await fetch_real_data()
    
    # 保存资源（使用ResourceType指定类型）
    manager = ResourceManager()
    manager.save(
        name="xxx_data",
        data=data,
        resource_type=ResourceType.RESPONSE,  # 根据实际类型选择
        version="1.0.0",
        description="XX接口的真实响应",
        source="https://api.example.com/endpoint",
        tags=["api", "external", "v1"]
    )
    
    print(f"Resource saved: xxx_data.pkl")
    print(f"Metadata saved: xxx_data.meta.json")


if __name__ == "__main__":
    asyncio.run(main())
```

## 常见问题处理

### 问题1: 异步fixture与同步fixture混用

**问题**: 在异步测试中使用同步fixture导致错误。

**解决**:
```python
# 错误
@pytest.fixture
def sync_data():
    return load_data()

# 正确
@pytest_asyncio.fixture
async def async_data():
    return await load_data()

# 或者使用同步fixture但标记asyncio
@pytest.fixture
def sync_data():
    return load_data()

@pytest.mark.asyncio
async def test_with_sync_fixture(sync_data):
    result = await process(sync_data)
```

### 问题2: Mock异步上下文管理器

**问题**: 需要mock async with语句。

**解决**:
```python
from unittest.mock import AsyncMock, MagicMock

mock_client = MagicMock()
mock_client.__aenter__ = AsyncMock(return_value=mock_client)
mock_client.__aexit__ = AsyncMock(return_value=False)
mock_client.get = AsyncMock(return_value=mock_response)

with patch("httpx.AsyncClient", return_value=mock_client):
    async with httpx.AsyncClient() as client:
        response = await client.get("url")
```

### 问题3: 测试依赖执行顺序

**问题**: 测试需要按特定顺序执行。

**解决**:
```python
# 使用pytest-order插件
@pytest.mark.order(1)
async def test_first():
    pass

@pytest.mark.order(2)
async def test_second():
    pass
```

### 问题4: 捕获日志输出

**问题**: 需要验证日志输出。

**解决**:
```python
import logging

def test_logging(caplog):
    caplog.set_level(logging.INFO)
    
    await function_that_logs()
    
    assert "Expected log message" in caplog.text
```

### 问题5: 参数化测试

**问题**: 需要多组参数运行同一测试。

**解决**:
```python
@pytest.mark.parametrize("input,expected", [
    ("case1", "result1"),
    ("case2", "result2"),
    ("case3", "result3"),
])
@pytest.mark.asyncio
async def test_with_params(input, expected):
    result = await process(input)
    assert result == expected
```
