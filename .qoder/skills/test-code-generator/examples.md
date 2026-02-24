# 测试代码生成器 - 使用示例

## 示例1: 为公告数据处理Handler生成测试

### 用户输入

**编排函数**: `announcements_data_handler.py`

```python
async def process_announcements(
    stock_codes: List[str],
    start_date: Optional[str] = None
) -> List[Dict]:
    """处理公告数据并同步到Notion.
    
    流程:
    1. 从巨潮资讯网获取公告列表
    2. 去重检查（基于xxhash）
    3. PDF内容提取（如需要）
    4. 创建Notion页面
    5. 更新数据库记录
    """
    # 实现...
```

**外部依赖**:
- `fetch_announcements()` - HTTP请求巨潮资讯网API
- `check_duplicate()` - 数据库查询
- `extract_pdf_content()` - PDF处理（CPU密集型）
- `create_notion_page()` - Notion API调用
- `update_db_record()` - 数据库写入

**用户要求的测试场景**:
1. 正常流程 - 获取公告并同步到Notion
2. 空股票列表 - 应返回空结果
3. API异常 - 应正确处理异常

### 生成步骤

#### Step 1: Mock策略决策

| 依赖 | 决策 | 理由 |
|-----|------|------|
| fetch_announcements() | Mock | 外部HTTP API，不稳定 |
| check_duplicate() | Mock | 数据库查询，需要确定性结果 |
| extract_pdf_content() | 真实 | CPU密集型，核心逻辑，无需mock |
| create_notion_page() | Mock | 外部API调用 |
| update_db_record() | Mock | 数据库写入，需要隔离 |

#### Step 2: 生成资源获取脚本

`tests/resource/fetch_announcements.py`:

```python
"""获取巨潮资讯网公告数据的真实响应."""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.resource.manager import ResourceManager, ResourceType
from core.data.announcement import fetch_announcements


async def main():
    """获取阳光电源(300274)的公告数据作为样本."""
    print("Fetching announcements from cninfo.com.cn...")
    
    # 获取真实数据
    data = await fetch_announcements(
        stock_codes=["300274"],
        start_date="2026-02-01"
    )
    
    # 保存资源（使用ResourceType指定类型）
    manager = ResourceManager()
    manager.save(
        name="ygdq_300274_announcements",
        data=data,
        resource_type=ResourceType.JSON,  # 公告数据为JSON格式
        version="1.0.0",
        description="阳光电源(300274)公告数据样本",
        source="http://www.cninfo.com.cn/new/information/topSearch/query",
        tags=["announcement", "300274", "阳光电源", "cninfo"]
    )
    
    print(f"Saved {len(data)} announcements")


if __name__ == "__main__":
    asyncio.run(main())
```

#### Step 3: 生成测试文件

`tests/test_announcements_data_handler.py`:

```python
"""Tests for announcements_data_handler module.

Test Categories:
    - Unit tests: 使用mock测试单个函数逻辑
    - Integration tests: 测试完整流程，部分使用真实调用
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from pathlib import Path
import pickle
from typing import List, Dict

from core.announcements_data_handler import process_announcements

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sample_stock_codes():
    """提供测试用的股票代码."""
    return ["300274", "000001"]


@pytest.fixture
def mock_announcements_data(resource_manager):
    """加载真实的公告数据作为mock."""
    resource = resource_manager.load("ygdq_300274_announcements")
    return resource.data


@pytest.fixture
def mock_notion_response():
    """Mock Notion API响应."""
    return {
        "id": "page-123",
        "object": "page",
        "created_time": "2026-02-16T10:00:00.000Z"
    }


class TestProcessAnnouncements:
    """测试process_announcements函数."""
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_success(
        self,
        sample_stock_codes,
        mock_announcements_data,
        mock_notion_response
    ):
        """测试正常流程：获取公告并成功同步到Notion."""
        # Arrange
        with patch("core.announcements_data_handler.fetch_announcements") as mock_fetch, \
             patch("core.announcements_data_handler.check_duplicate") as mock_dup, \
             patch("core.announcements_data_handler.create_notion_page") as mock_notion, \
             patch("core.announcements_data_handler.update_db_record") as mock_db:
            
            mock_fetch.return_value = mock_announcements_data
            mock_dup.return_value = False  # 非重复
            mock_notion.return_value = mock_notion_response
            mock_db.return_value = True
            
            # Act
            result = await process_announcements(
                stock_codes=sample_stock_codes,
                start_date="2026-02-01"
            )
            
            # Assert
            assert isinstance(result, list)
            mock_fetch.assert_called_once()
            mock_notion.assert_called()
            mock_db.assert_called()
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_empty_stock_codes(self):
        """测试空股票列表：应返回空结果."""
        # Arrange & Act
        result = await process_announcements(stock_codes=[])
        
        # Assert
        assert result == []
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_duplicate_announcement(
        self,
        sample_stock_codes,
        mock_announcements_data
    ):
        """测试重复公告：应跳过已存在的记录."""
        # Arrange
        with patch("core.announcements_data_handler.fetch_announcements") as mock_fetch, \
             patch("core.announcements_data_handler.check_duplicate") as mock_dup, \
             patch("core.announcements_data_handler.create_notion_page") as mock_notion:
            
            mock_fetch.return_value = mock_announcements_data
            mock_dup.return_value = True  # 已存在
            
            # Act
            result = await process_announcements(stock_codes=sample_stock_codes)
            
            # Assert
            mock_notion.assert_not_called()  # 不应创建Notion页面
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_api_error(self, sample_stock_codes):
        """测试API异常：应正确处理异常."""
        # Arrange
        with patch("core.announcements_data_handler.fetch_announcements") as mock_fetch:
            mock_fetch.side_effect = Exception("API Connection Error")
            
            # Act & Assert
            with pytest.raises(Exception) as exc_info:
                await process_announcements(stock_codes=sample_stock_codes)
            
            assert "API Connection Error" in str(exc_info.value)
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_notion_api_error(
        self,
        sample_stock_codes,
        mock_announcements_data
    ):
        """测试Notion API异常：应记录错误但不中断流程."""
        # Arrange
        with patch("core.announcements_data_handler.fetch_announcements") as mock_fetch, \
             patch("core.announcements_data_handler.check_duplicate") as mock_dup, \
             patch("core.announcements_data_handler.create_notion_page") as mock_notion:
            
            mock_fetch.return_value = mock_announcements_data
            mock_dup.return_value = False
            mock_notion.side_effect = Exception("Notion API Error")
            
            # Act & Assert
            with pytest.raises(Exception):
                await process_announcements(stock_codes=sample_stock_codes)
    
    @pytest.mark.integration
    @pytest.mark.slow
    async def test_process_real_pdf_extraction(
        self,
        sample_stock_codes,
        mock_announcements_data,
        mock_notion_response
    ):
        """测试真实PDF提取流程（不使用mock）.
        
        此测试验证PDF内容提取的核心逻辑，使用真实文件。
        """
        # Arrange
        with patch("core.announcements_data_handler.fetch_announcements") as mock_fetch, \
             patch("core.announcements_data_handler.check_duplicate") as mock_dup, \
             patch("core.announcements_data_handler.create_notion_page") as mock_notion, \
             patch("core.announcements_data_handler.update_db_record") as mock_db:
            
            mock_fetch.return_value = mock_announcements_data
            mock_dup.return_value = False
            mock_notion.return_value = mock_notion_response
            mock_db.return_value = True
            
            # Act - 使用真实的PDF提取（不mock extract_pdf_content）
            result = await process_announcements(
                stock_codes=sample_stock_codes,
                start_date="2026-02-01"
            )
            
            # Assert
            assert isinstance(result, list)
```

## 示例2: 为PDF处理模块生成测试

### 用户输入

**函数**: `split_pdf_by_keywords(file_path: str, keywords: List[str]) -> List[str]`

**功能**: 根据关键词分割PDF文件，返回分割后的文件路径列表

**外部依赖**: `pymupdf.open()` - PDF处理库

### 生成步骤

#### Step 1: Mock策略决策

| 依赖 | 决策 | 理由 |
|-----|------|------|
| pymupdf.open() | 真实 | 核心逻辑，本地文件可控 |

#### Step 2: 准备测试资源

在 `tests/resource/` 放置测试PDF文件：
- `sample_announcement.pdf` - 样本公告PDF
- `multi_page.pdf` - 多页测试PDF

#### Step 3: 生成测试文件

`tests/test_data/test_pdf_split.py`:

```python
"""Tests for PDF split module.

Test Categories:
    - Unit tests: 测试PDF分割逻辑
    
Note: 此模块不涉及外部网络调用，使用真实PDF文件测试。
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from core.data.pdf_split import split_pdf_by_keywords


@pytest.fixture
def resource_dir():
    """返回资源目录."""
    return Path(__file__).parent.parent / "resource"


@pytest.fixture
def temp_dir():
    """创建临时目录."""
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


class TestSplitPdfByKeywords:
    """测试split_pdf_by_keywords函数."""
    
    @pytest.mark.unit
    @pytest.mark.fast
    def test_split_with_keywords_found(self, resource_dir, temp_dir):
        """测试正常分割：找到关键词并分割PDF."""
        # Arrange
        pdf_path = resource_dir / "sample_announcement.pdf"
        keywords = ["重大事项", "风险提示"]
        
        # Act
        result = split_pdf_by_keywords(
            file_path=str(pdf_path),
            keywords=keywords,
            output_dir=str(temp_dir)
        )
        
        # Assert
        assert isinstance(result, list)
        # 验证分割后的文件存在
        for path in result:
            assert Path(path).exists()
    
    @pytest.mark.unit
    @pytest.mark.fast
    def test_split_no_keywords_found(self, resource_dir, temp_dir):
        """测试无匹配关键词：应返回空列表."""
        # Arrange
        pdf_path = resource_dir / "sample_announcement.pdf"
        keywords = ["不存在的词", "另一个不存在的词"]
        
        # Act
        result = split_pdf_by_keywords(
            file_path=str(pdf_path),
            keywords=keywords,
            output_dir=str(temp_dir)
        )
        
        # Assert
        assert result == []
    
    @pytest.mark.unit
    @pytest.mark.fast
    def test_split_empty_keywords(self, resource_dir, temp_dir):
        """测试空关键词列表：应返回空列表."""
        # Arrange
        pdf_path = resource_dir / "sample_announcement.pdf"
        
        # Act
        result = split_pdf_by_keywords(
            file_path=str(pdf_path),
            keywords=[],
            output_dir=str(temp_dir)
        )
        
        # Assert
        assert result == []
    
    @pytest.mark.unit
    @pytest.mark.fast
    def test_split_file_not_found(self, temp_dir):
        """测试文件不存在：应抛出FileNotFoundError."""
        # Arrange
        non_existent_path = "/path/to/nonexistent.pdf"
        
        # Act & Assert
        with pytest.raises(FileNotFoundError):
            split_pdf_by_keywords(
                file_path=non_existent_path,
                keywords=["测试"],
                output_dir=str(temp_dir)
            )
    
    @pytest.mark.unit
    @pytest.mark.slow
    def test_split_large_pdf(self, resource_dir, temp_dir):
        """测试大文件分割：验证性能."""
        # Arrange
        pdf_path = resource_dir / "multi_page.pdf"
        keywords = ["财务报告", "审计意见"]
        
        # Act
        import time
        start = time.time()
        result = split_pdf_by_keywords(
            file_path=str(pdf_path),
            keywords=keywords,
            output_dir=str(temp_dir)
        )
        elapsed = time.time() - start
        
        # Assert
        assert elapsed < 5.0  # 应在5秒内完成
        assert isinstance(result, list)
```

## 示例3: 为Notion客户端生成测试

### 用户输入

**类**: `NotionClient`

**方法**:
- `async create_page(database_id: str, properties: Dict) -> Dict`
- `async update_page(page_id: str, properties: Dict) -> Dict`
- `async query_database(database_id: str, filter: Dict) -> List[Dict]`

**外部依赖**: Notion API (HTTP)

### 生成步骤

#### Step 1: Mock策略决策

| 依赖 | 决策 | 理由 |
|-----|------|------|
| Notion API | Mock | 外部API，有速率限制，需要确定性结果 |

#### Step 2: 生成资源获取脚本

`tests/resource/fetch_notion_responses.py`:

```python
"""获取Notion API的真实响应."""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
import os

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from tests.resource.manager import ResourceManager, ResourceType
from core.notion.client import NotionClient


async def fetch_create_page_response():
    """获取创建页面的真实响应."""
    client = NotionClient(token=os.getenv("NOTION_TOKEN"))
    
    # 使用测试数据库创建页面
    test_db_id = os.getenv("TEST_DATABASE_ID")
    
    response = await client.create_page(
        database_id=test_db_id,
        properties={
            "标题": {"title": [{"text": {"content": "Test Page"}}]},
            "状态": {"select": {"name": "测试"}}
        }
    )
    
    return response


async def fetch_query_database_response():
    """获取查询数据库的真实响应."""
    client = NotionClient(token=os.getenv("NOTION_TOKEN"))
    
    test_db_id = os.getenv("TEST_DATABASE_ID")
    
    response = await client.query_database(
        database_id=test_db_id,
        filter={"property": "状态", "select": {"equals": "测试"}}
    )
    
    return response


async def main():
    """获取所有Notion响应."""
    manager = ResourceManager()
    
    print("Fetching Notion API responses...")
    
    # 获取创建页面响应
    create_response = await fetch_create_page_response()
    manager.save(
        name="notion_create_page",
        data=create_response,
        resource_type=ResourceType.JSON,
        version="1.0.0",
        description="Notion API创建页面的真实响应",
        source="https://api.notion.com/v1/pages",
        tags=["notion", "api", "pages.create"]
    )
    print("Saved: notion_create_page")
    
    # 获取查询响应
    query_response = await fetch_query_database_response()
    manager.save(
        name="notion_query_database",
        data=query_response,
        resource_type=ResourceType.JSON,
        version="1.0.0",
        description="Notion API查询数据库的真实响应",
        source="https://api.notion.com/v1/databases/{id}/query",
        tags=["notion", "api", "databases.query"]
    )
    print("Saved: notion_query_database")


if __name__ == "__main__":
    asyncio.run(main())
```

#### Step 3: 生成测试文件

`tests/test_notion/test_client.py`:

```python
"""Tests for Notion client module.

Test Categories:
    - Unit tests: 使用mock测试API调用逻辑
    - Integration tests: 可选的真实API测试（需配置环境变量）
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path
import os

from core.notion.client import NotionClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def notion_client():
    """提供NotionClient实例."""
    return NotionClient(token="test-token")


@pytest.fixture
def mock_create_response(resource_manager):
    """加载创建页面的mock响应."""
    resource = resource_manager.load("notion_create_page")
    return resource.data


@pytest.fixture
def mock_query_response(resource_manager):
    """加载查询数据库的mock响应."""
    resource = resource_manager.load("notion_query_database")
    return resource.data


class TestNotionClient:
    """测试NotionClient类."""
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_create_page_success(
        self,
        notion_client,
        mock_create_response
    ):
        """测试创建页面成功."""
        # Arrange
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_create_response
            )
            
            # Act
            result = await notion_client.create_page(
                database_id="db-123",
                properties={"标题": {"title": [{"text": {"content": "Test"}}]}}
            )
            
            # Assert
            assert result["id"] == mock_create_response["id"]
            mock_post.assert_called_once()
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_create_page_api_error(self, notion_client):
        """测试创建页面API错误."""
        # Arrange
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=400,
                json=lambda: {"message": "Invalid property"}
            )
            
            # Act & Assert
            with pytest.raises(Exception) as exc_info:
                await notion_client.create_page(
                    database_id="db-123",
                    properties={}
                )
            
            assert "Invalid property" in str(exc_info.value)
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_query_database_success(
        self,
        notion_client,
        mock_query_response
    ):
        """测试查询数据库成功."""
        # Arrange
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_query_response
            )
            
            # Act
            result = await notion_client.query_database(
                database_id="db-123",
                filter={"property": "状态", "select": {"equals": "测试"}}
            )
            
            # Assert
            assert isinstance(result, list)
    
    @pytest.mark.unit
    @pytest.mark.fast
    async def test_rate_limit_handling(self, notion_client):
        """测试速率限制处理."""
        # Arrange
        call_count = 0
        
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Mock(status_code=429, headers={"Retry-After": "1"})
            return Mock(status_code=200, json=lambda: {"id": "page-123"})
        
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = side_effect
            
            # Act
            result = await notion_client.create_page(
                database_id="db-123",
                properties={}
            )
            
            # Assert
            assert mock_post.call_count == 2  # 重试一次
    
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.real_network
    @pytest.mark.skipif(
        not os.getenv("NOTION_TOKEN"),
        reason="需要NOTION_TOKEN环境变量"
    )
    async def test_real_api_call(self):
        """测试真实Notion API调用.
        
        此测试需要配置NOTION_TOKEN和TEST_DATABASE_ID环境变量。
        """
        # Arrange
        client = NotionClient(token=os.getenv("NOTION_TOKEN"))
        test_db_id = os.getenv("TEST_DATABASE_ID")
        
        # Act
        result = await client.create_page(
            database_id=test_db_id,
            properties={
                "标题": {"title": [{"text": {"content": "Integration Test"}}]}
            }
        )
        
        # Assert
        assert "id" in result
        assert result["object"] == "page"
```

## 快速参考

### 常用pytest标记

```python
# 基础标记
@pytest.mark.unit              # 单元测试
@pytest.mark.integration       # 集成测试
@pytest.mark.asyncio          # 异步测试
@pytest.mark.fast             # 快速测试(<1s)
@pytest.mark.slow             # 慢速测试(>1s)
@pytest.mark.real_network     # 真实网络调用

# 组合使用
@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fast
async def test_something():
    pass
```

### 常用fixture模式

```python
# 加载静态资源
@pytest.fixture
def mock_data(resource_manager):
    resource = resource_manager.load("resource_name")
    return resource.data

# 临时目录
@pytest.fixture
def temp_dir():
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)

# Mock外部API
@pytest.fixture
def mock_http_client():
    with patch("httpx.AsyncClient") as mock:
        yield mock
```
