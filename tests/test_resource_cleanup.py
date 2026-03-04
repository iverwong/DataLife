"""资源清理函数测试。

验证 close_client() 和 close_db() 函数存在且工作正常。
以及检测线程泄露问题（P4）。
"""

import asyncio
import threading


class TestCloseClient:
    """测试 core.notion.client.close_client() 函数。"""

    def test_close_client_exists_and_works(self):
        """验证 close_client 函数存在且调用后 httpx_client.is_closed 为 True。"""
        from core.notion import client as notion_client_module

        # 验证函数存在
        assert hasattr(notion_client_module, "close_client"), (
            "close_client 函数不存在"
        )

        # 懒加载模式：先调用 get_httpx_client() 触发创建
        notion_client_module.get_httpx_client()

        # 验证可以调用
        asyncio.get_event_loop().run_until_complete(
            notion_client_module.close_client()
        )

        # 验证客户端已关闭
        assert notion_client_module.httpx_client is None or notion_client_module.httpx_client.is_closed is True

    def test_close_client_idempotent(self):
        """验证连续调用 close_client() 两次不会抛出异常。"""
        from core.notion import client as notion_client_module

        # 第一次调用（客户端已关闭）
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


class TestThreadLeakDetection:
    """测试 P4: 检测 httpx.AsyncClient 导致的线程泄露。"""

    def test_no_dangling_threads_after_cleanup(self):
        """验证 close_client() 和 close_db() 后不存在残留非 daemon 线程。

        P4 问题：httpx.AsyncClient 在模块 import 时创建，测试结束后未关闭，
        导致测试进程挂起（非 daemon 线程阻止进程退出）。
        """
        import core.db as db_module
        from core.notion import client as notion_client_module

        # 记录清理前的非 daemon 线程
        def get_non_daemon_threads() -> list[threading.Thread]:
            return [
                t for t in threading.enumerate()
                if not t.daemon and t.name != "MainThread"
            ]

        # 执行清理
        asyncio.get_event_loop().run_until_complete(
            notion_client_module.close_client()
        )
        asyncio.get_event_loop().run_until_complete(db_module.close_db())

        # 等待一小段时间让线程完成清理
        import time
        time.sleep(0.5)

        # 检查是否存在非 daemon 线程
        dangling_threads = get_non_daemon_threads()

        # 过滤掉 aiosqlite 或 httpx/anyio 相关的线程
        suspicious_threads = [
            t for t in dangling_threads
            if any(
                keyword in t.name.lower()
                for keyword in ["aiosqlite", "httpx", "anyio", "asyncio"]
            )
        ]

        assert len(suspicious_threads) == 0, (
            f"发现 {len(suspicious_threads)} 个可疑的残留非 daemon 线程: "
            f"{[t.name for t in suspicious_threads]}"
        )
