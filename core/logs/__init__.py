# logger_config.py
import logging
import sys

from loguru import logger


def setup_logging():
    """必须在导入其他库之前调用"""

    # 配置 loguru
    logger.remove()

    # 控制台输出（彩色）
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="DEBUG",
        colorize=True,
    )

    # 文件输出（JSON）
    logger.add(
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
    logger.add(
        "logs/error_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="90 days",
        level="ERROR",
    )

    # 拦截标准 logging
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
