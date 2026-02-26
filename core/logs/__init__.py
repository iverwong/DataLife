# logger_config.py
"""日志配置模块。

使用 loguru 配置控制台彩色输出、JSON 文件日志和错误日志，
并拦截标准 logging 库的输出统一处理。支持 trace_id 便于并发场景追踪。
"""

import contextvars
import logging
import secrets
import sys
from types import FrameType
from typing import override

from loguru import Record, logger

# 用于跨异步任务追踪的 trace_id
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """获取当前上下文的 trace_id。"""
    return _trace_id.get()


def set_trace_id(trace_id: str | None = None) -> str:
    """设置当前上下文的 trace_id，若未指定则自动生成。

    Args:
        trace_id: 指定的 trace_id，None 时自动生成 8 位十六进制字符串。

    Returns:
        设置后的 trace_id。
    """
    tid = trace_id or secrets.token_hex(4)
    _ = _trace_id.set(tid)
    return tid


def _trace_id_patcher(record: Record) -> None:
    """为日志记录添加 trace_id 字段。"""
    record["extra"]["trace_id"] = get_trace_id()


def setup_logging() -> None:
    """配置全局日志系统，必须在导入其他库之前调用。

    配置内容：
    - 控制台输出：彩色、INFO 级别、包含 trace_id
    - 文件输出：JSON 格式、INFO 级别、每日轮换、保留 30 天
    - 错误日志：单独记录 ERROR 级别、保留 90 天
    - 拦截标准 logging 输出统一为 loguru 格式
    """
    logger.remove()
    _ = logger.configure(patcher=_trace_id_patcher)

    # 控制台输出（彩色），生产环境使用 INFO 级别
    console_format = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[trace_id]:>8}</cyan> | "
        "<yellow>{function}</yellow> | "
        "{message}"
    )
    _ = logger.add(
        sys.stderr,
        format=console_format,
        level="INFO",
        colorize=True,
    )

    # 文件输出（JSON），serialize=True 会自动包含 extra 字段
    _ = logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        format="{message}",
        serialize=True,
        rotation="00:00",
        retention="30 days",
        compression="zip",
        level="INFO",
        enqueue=True,
    )

    # 错误日志单独记录
    _ = logger.add(
        "logs/error_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="90 days",
        level="ERROR",
    )

    # 拦截标准 logging
    class InterceptHandler(logging.Handler):
        @override
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level: str | int = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame: FrameType | None = logging.currentframe()
            depth = 2
            while frame is not None and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
