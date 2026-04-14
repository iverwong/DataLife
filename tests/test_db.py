"""数据库 Repository 函数测试。

测试 core/db/__init__.py 中的 4 个 Repository 函数：
- check_hash
- save_hash
- get_update_time
- set_update_time
"""

import pytest

from core.db import HashContent, check_hash, get_session, save_hash
from core.db.models import HashRecord, UpdateRecord
from core.models import NotionDate, UpdateRecordKey


class TestCheckHash:
    """测试 check_hash 函数。"""

    @pytest.mark.asyncio
    async def test_check_hash_filters_existing(self, test_engine):
        """插入已有哈希后调用 check_hash，验证仅返回不存在的项。"""
        # 先保存 content1-3 的哈希
        existing_hashes = [
            HashContent(data_type="test", content="content1"),
            HashContent(data_type="test", content="content2"),
            HashContent(data_type="test", content="content3"),
        ]
        await save_hash(existing_hashes)

        # 创建包含已存在和不存在哈希的列表
        data_list = [
            HashContent(data_type="test", content="content1"),
            HashContent(data_type="test", content="content2"),
            HashContent(data_type="test", content="content3"),
            HashContent(data_type="test", content="content4"),
            HashContent(data_type="test", content="content5"),
        ]

        # 应该只返回不存在的项（content4 和 content5）
        result = await check_hash(data_list)
        assert len(result) == 2  # content4 和 content5


class TestSaveHash:
    """测试 save_hash 函数。"""

    @pytest.mark.asyncio
    async def test_save_hash_persists(self, test_engine):
        """save_hash 后查询 HashRecord 验证持久化。"""
        hashes = ["hash_a", "hash_b", "hash_c"]
        await save_hash(hashes)

        # 验证保存成功
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(select(HashRecord))
            records = result.scalars().all()
            saved_hashes = {r.hash for r in records}

        assert saved_hashes == set(hashes)


class TestGetUpdateTime:
    """测试 get_update_time 函数。"""

    @pytest.mark.asyncio
    async def test_get_update_time_inserts_missing(self, test_engine):
        """对缺失股票调用 get_update_time，验证自动插入 NULL 行并返回 None。"""
        from core.db import get_update_time
        from sqlalchemy import select

        stocks = ["600000", "600001", "600002"]
        key: UpdateRecordKey = "announcements"

        # 调用 get_update_time
        result = await get_update_time(stocks, key)

        # 验证返回结果
        assert len(result) == 3
        for stock in stocks:
            assert stock in result
            assert result[stock] is None  # 新插入的记录应该是 None

        # 验证数据库中有记录
        async with get_session() as session:
            result_db = await session.execute(
                select(UpdateRecord).where(UpdateRecord.key == key)
            )
            records = result_db.scalars().all()
            assert len(records) == 3

    @pytest.mark.asyncio
    async def test_get_update_time_returns_existing(self, test_engine):
        """对已有记录的股票，验证返回更新时间。"""
        from core.db import get_update_time

        key: UpdateRecordKey = "announcements"

        # 先插入记录
        async with get_session() as session:
            record = UpdateRecord(
                stock="600000",
                key=key,
                update_time="2024-01-01T00:00:00",
            )
            session.add(record)

        # 调用 get_update_time
        result = await get_update_time(["600000"], key)
        # NotionDate 是一个 NewType，就是 str 的别名
        assert result["600000"] == "2024-01-01T00:00:00"


class TestSetUpdateTime:
    """测试 set_update_time 函数。"""

    @pytest.mark.asyncio
    async def test_set_update_time_updates_existing(self, test_engine):
        """先 get_update_time 插入行，再 set_update_time 更新，验证值变更。"""
        from core.db import get_update_time, set_update_time

        stock = "600000"
        key: UpdateRecordKey = "announcements"

        # 先调用 get_update_time 插入记录
        await get_update_time([stock], key)

        # 更新更新时间
        new_time = NotionDate("2024-06-01T12:00:00")
        await set_update_time(stock, key, new_time)

        # 验证更新成功
        result = await get_update_time([stock], key)
        assert result[stock] == new_time

    @pytest.mark.asyncio
    async def test_set_update_time_raises_on_missing(self, test_engine):
        """对不存在的记录调用 set_update_time，验证抛出 ValueError。"""
        from core.db import set_update_time

        stock = "999999"
        key: UpdateRecordKey = "announcements"

        # 尝试更新不存在的记录应抛出 ValueError
        with pytest.raises(ValueError):
            await set_update_time(stock, key, None)
