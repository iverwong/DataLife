---
name: test-code-generator
description: 根据编排函数/对象的函数签名和架构抽象信息，在tests目录中生成完整的单元测试和集成测试。适用于Python异步项目，支持基于抽象接口生成测试代码，自动管理mock静态资源，使用pytest标记区分测试类型。当用户要求为某个编排函数或模块编写测试时使用。
---

# 测试代码生成器

## 触发条件

当用户有以下请求时激活此技能：
- "为XX函数/模块编写测试"
- "生成XX的测试代码"
- "给XX添加单元测试"
- "测试一下这个功能"
- 任何涉及测试编写的请求

## 工作流程

### Phase 1: 需求澄清与业务理解

用户提供编排函数后，按以下清单进行理解：

```
业务理解检查清单：
□ 1. 编排函数的输入参数有哪些？每个参数的类型和含义？
□ 2. 编排函数的核心业务流程是什么？
□ 3. 函数调用了哪些外部依赖（HTTP API、数据库、文件系统等）？
□ 4. 用户要求的最低测试覆盖场景有哪些？
□ 5. 是否存在异常/边界情况需要处理？
```

**关键原则**：
- 对于任何不确定的业务逻辑，必须询问用户，不做假设
- 如果业务逻辑存在明显瑕疵，需指出并建议修正
- 确认所有外部依赖的mock策略（见下方Mock决策流程）

### Phase 2: Mock策略决策

对每个外部依赖，按以下流程决策：

```
Mock决策流程：
1. 该调用是否涉及网络请求（HTTP/HTTPS）？
   → 是：建议mock，需生成资源获取脚本
   
2. 该调用是否涉及耗时操作（>5秒）或不稳定资源？
   → 是：建议mock
   
3. 该调用是否是核心测试目标（需要验证真实行为）？
   → 是：不建议mock，使用真实调用
   
4. 其他情况
   → 建议mock，但提供真实集成测试选项
```

**Mock实施规则**：
- 所有mock对象必须先进行一次真实操作，获取真实响应
- 静态资源存储在 `tests/resource/` 目录
- 资源获取脚本命名为 `fetch_<resource_name>.py`
- 如果mock了某个对象，必须配套一个全流程真实集成测试

### Phase 3: 测试场景设计

基于用户要求的最低场景，补充以下测试类型：

| 测试类型 | 标记 | 说明 |
|---------|------|------|
| 单元测试 | `@pytest.mark.unit` | 测试单个函数/方法，依赖mock |
| 集成测试 | `@pytest.mark.integration` | 测试多个模块协作，可能涉及真实调用 |
| 异步测试 | `@pytest.mark.asyncio` | 异步函数测试，必须添加 |
| 同步测试 | （无特殊标记） | 同步函数测试 |
| 真实网络测试 | `@pytest.mark.real_network` | 涉及真实HTTP请求 |
| 快速测试 | `@pytest.mark.fast` | 执行时间<1秒 |
| 慢速测试 | `@pytest.mark.slow` | 执行时间>1秒 |

**必须覆盖的场景**：
1. 正常流程（Happy Path）
2. 空输入/边界值
3. 异常处理（每个可能抛出异常的点）
4. 并发/异步边界（如适用）

### Phase 4: 静态资源管理

对于需要mock的外部调用：

1. **生成资源获取脚本** `tests/resource/fetch_<name>.py`：
```python
"""获取XX接口的真实响应数据."""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.resource.manager import ResourceManager, ResourceType


async def fetch_and_save():
    """执行真实请求并保存响应."""
    # 真实调用代码
    response = await real_api_call()
    
    # 使用ResourceManager保存资源
    manager = ResourceManager()
    manager.save(
        name="<name>",
        data=response,
        resource_type=ResourceType.RESPONSE,  # 根据实际类型选择
        version="1.0.0",
        description="XX接口的真实响应",
        source="https://api.example.com/...",
        tags=["api", "external"]
    )
    
    print(f"Resource saved: <name>.pkl")


if __name__ == "__main__":
    asyncio.run(fetch_and_save())
```

2. **使用静态资源**：
```python
# conftest.py 或测试文件中
import pytest
from pathlib import Path
from tests.resource.manager import ResourceManager

@pytest.fixture
def resource_manager():
    """提供ResourceManager实例."""
    return ResourceManager()


@pytest.fixture
def mock_response(resource_manager):
    """加载mock响应数据."""
    resource = resource_manager.load("<name>")
    return resource.data


# 或者使用类型检查
@pytest.fixture
def mock_announcements(resource_manager):
    """加载公告数据并验证类型."""
    import pandas as pd
    resource = resource_manager.load("announcements", expected_type=pd.DataFrame)
    return resource.data
```

### Phase 5: 测试文件生成

#### 文件结构规范

测试文件必须与 `core/` 目录结构对应：

```
tests/
├── conftest.py              # 全局fixture
├── resource/                # 静态资源目录
│   ├── fetch_*.py          # 资源获取脚本
│   ├── *.pkl               # 序列化响应数据
│   └── *.meta.json         # 元数据
├── test_data/              # 数据模块测试
│   └── test_*.py
├── test_db/                # 数据库模块测试
│   └── test_*.py
├── test_notion/            # Notion模块测试
│   └── test_*.py
└── test_*.py               # 根级handler测试
```

#### 测试文件模板

```python
"""Tests for <module_name>.

Test Categories:
    - Unit tests: 测试单个函数，使用mock
    - Integration tests: 测试完整流程，使用真实调用
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path
import pickle

# 标记所有测试为异步
pytestmark = pytest.mark.asyncio


@pytest.fixture
def sample_data():
    """提供测试数据."""
    return {
        "key": "value"
    }


@pytest.fixture
def mock_external_api(resource_manager):
    """Mock外部API响应."""
    resource = resource_manager.load("<api_name>")
    return resource.data


class Test<FunctionName>:
    """测试<FunctionName>函数."""
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_<function_name>_success(self, sample_data, mock_external_api):
        """测试正常流程."""
        # Arrange
        with patch("module.path.external_call", return_value=mock_external_api):
            # Act
            result = await function_name(sample_data)
            
            # Assert
            assert result is not None
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_<function_name>_empty_input(self):
        """测试空输入处理."""
        # Arrange & Act & Assert
        with pytest.raises(ValueError):
            await function_name(None)
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_<function_name>_api_error(self, mock_external_api):
        """测试API异常处理."""
        # Arrange
        with patch("module.path.external_call", side_effect=Exception("API Error")):
            # Act & Assert
            with pytest.raises(Exception):
                await function_name({})
    
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.real_network
    async def test_<function_name>_real_flow(self):
        """测试真实完整流程（不使用mock）."""
        # 使用真实调用，验证端到端流程
        result = await function_name(real_data)
        assert result is not None
```

#### conftest.py 模板

```python
"""全局测试配置和fixture."""

import pytest
import pytest_asyncio
import asyncio
from pathlib import Path


@pytest.fixture(scope="session")
def event_loop():
    """创建session级别的事件循环."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def resource_manager():
    """提供ResourceManager实例."""
    from tests.resource.manager import ResourceManager
    return ResourceManager()


@pytest.fixture
def load_resource(resource_manager):
    """加载静态资源."""
    def _load(name: str, expected_type=None):
        resource = resource_manager.load(name, expected_type=expected_type)
        return resource.data
    return _load
```

### Phase 6: 验证与交付

生成测试后，执行以下检查：

```
交付检查清单：
□ 1. 测试文件路径是否符合core/目录结构对应关系？
□ 2. 是否所有测试都有适当的pytest标记？
□ 3. 每个mock是否都有对应的集成测试覆盖？
□ 4. 资源获取脚本是否能正常运行并生成静态资源？
□ 5. 测试是否能通过（至少单元测试）？
□ 6. 是否遵循项目编码规范（PEP 8、type hints）？
```

## 项目特定约定

### 当前项目结构

```
core/
├── data/           # 数据采集模块
├── db/             # 数据库模块
├── notion/         # Notion API模块
├── announcements_data_handler.py
└── business_data_handler.py
```

测试文件对应关系：
- `core/data/announcement.py` → `tests/test_data/test_announcement.py`
- `core/notion/client.py` → `tests/test_notion/test_client.py`
- `core/announcements_data_handler.py` → `tests/test_announcements_data_handler.py`

### 常用Mock模式

**HTTP请求（httpx）**：
```python
with patch("httpx.AsyncClient.get") as mock_get:
    mock_get.return_value = Mock(status_code=200, json=lambda: {...})
```

**数据库（aiosqlite）**：
```python
with patch("core.db.execute_query") as mock_query:
    mock_query.return_value = [(1, "data")]
```

**Notion API**：
```python
with patch("notion_client.AsyncClient.pages.create") as mock_create:
    mock_create.return_value = {"id": "page-id"}
```

## 示例

### 示例1：为公告数据处理handler生成测试

**用户输入**：
- 编排函数：`process_announcements(stock_codes: List[str], start_date: str)`
- 调用：`fetch_announcements()`（HTTP API）、`save_to_db()`、`create_notion_page()`
- 要求场景：正常流程、空股票列表、API异常

**生成内容**：
1. `tests/test_announcements_data_handler.py` - 主测试文件
2. `tests/resource/fetch_announcements.py` - 获取真实公告数据
3. 标记：@pytest.mark.unit / @pytest.mark.integration / @pytest.mark.asyncio

### 示例2：为PDF处理模块生成测试

**用户输入**：
- 函数：`split_pdf_by_keywords(file_path: str, keywords: List[str])`
- 调用：`pymupdf.open()`（CPU密集型，无需mock）
- 要求场景：正常分割、无关键词匹配、文件不存在

**生成内容**：
1. `tests/test_data/test_pdf_split.py`
2. 使用真实PDF文件作为测试资源（无需mock）
3. 标记：@pytest.mark.unit / @pytest.mark.slow

## 注意事项

1. **不假设业务逻辑**：任何不确定的地方必须询问用户
2. **优先真实调用**：非必要不使用mock，尤其是核心业务流程
3. **保持独立**：每个测试用例应该独立运行，不依赖其他测试
4. **清理资源**：测试完成后清理创建的临时文件和数据
5. **文档化**：复杂测试场景添加注释说明测试意图
