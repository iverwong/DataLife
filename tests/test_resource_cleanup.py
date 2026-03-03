"""资源清理函数测试。

验证 close_client() 和 close_db() 函数存在且工作正常。
"""

import asyncio

import pytest


class TestCloseClient:
    """测试 core.notion.client.close_client() 函数。"""

    def test_close_client_exists_and_works(self):
        """验证 close_client 函数存在且调用后 httpx_client.is_closed 为 True。"""
        from core.notion import client as notion_client_module

        # 验证函数存在
        assert hasattr(notion_client_module, "close_client"), (
            "close_client 函数不存在"
        )

        # 验证可以调用
        asyncio.get_event_loop().run_until_complete(
            notion_client_module.close_client()
        )

        # 验证客户端已关闭
        assert notion_client_module.httpx_client.is_closed is True

    def test_close_client_idempotent(self):
        """验证连续调用 close_client() 两次不会抛出异常。"""
        from core.notion import client as notion_client_module

        # 第一次调用
        asyncio.get_event_loop().run_until_complete(
            notion_client_module.close_client()
        )

        # 第二次调用应该不抛出异常
        asyncio.get_event_loop().run_until_complete(
            notion_client_module.close_client()
        )


class TestCloseDb:
    """测试 core.db.close_db() 函数。"""

    def test_close_db_exists_and_works(self):
        """验证 close_db 函数存在且调用后 db 被重置为 None。"""
        import core.db as db_module

        # 先调用一次 _get_db 确保连接存在
        asyncio.get_event_loop().run_until_complete(db_module._get_db())

        # 验证 db 不为 None
        assert db_module.db is not None

        # 验证函数存在
        assert hasattr(db_module, "close_db"), "close_db 函数不存在"

        # 调用 close_db
        asyncio.get_event_loop().run_until_complete(db_module.close_db())

        # 验证 db 被重置为 None
        assert db_module.db is None

    def test_close_db_idempotent(self):
        """验证连续调用 close_db() 两次不会抛出异常。"""
        import core.db as db_module

        # 第一次调用（即使 db 已经是 None）
        asyncio.get_event_loop().run_until_complete(db_module.close_db())

        # 第二次调用应该不抛出异常
        asyncio.get_event_loop().run_until_complete(db_module.close_db())
