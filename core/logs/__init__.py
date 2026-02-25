# logger_config.py
"""日志配置模块。

使用 loguru 配置控制台彩色输出、JSON 文件日志和错误日志，
并拦截标准 logging 库的输出统一处理。
"""

import logging
import sys
from types import FrameType
from typing import override

from loguru import logger


def setup_logging() -> None:
    """配置全局日志系统，必须在导入其他库之前调用。

    配置内容：
    - 控制台输出：彩色、DEBUG 级别
    - 文件输出：JSON 格式、INFO 级别、每日轮换、保留 30 天
    - 错误日志：单独记录 ERROR 级别、保留 90 天
    - 拦截标准 logging 输出统一为 loguru 格式
    """

    # 配置 loguru
    logger.remove()

    # 控制台输出（彩色）
    _ = logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <yellow>{function}</yellow> | {message}",
        level="DEBUG",
        colorize=True,
    )

    # 文件输出（JSON）
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
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
