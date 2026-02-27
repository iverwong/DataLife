"""日志配置模块。

使用 logfire 配置控制台彩色输出、文件日志和错误日志。
基于 OpenTelemetry 提供自动分布式追踪（trace_id / span_id）。
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import logfire


def setup_logging() -> None:
    """配置全局日志系统。

    配置内容：
    - 控制台输出：彩色、INFO 级别、包含 trace_id
    - 文件输出：每日轮换、保留 30 天
    - 错误日志：单独记录 ERROR 级别、保留 90 天
    - 拦截标准 logging 输出统一处理
    """
    # 1. 配置 logfire
    _ = logfire.configure(
        service_name="notion-stock-sync",
        send_to_logfire="if-token-present",
        console=logfire.ConsoleOptions(
            min_log_level="info",
            colors="auto",
            span_style="simple",
            include_timestamps=True,
        ),
    )

    # 2. 桥接：logfire 日志流入标准 logging
    logfire_handler = logfire.LogfireLoggingHandler()

    # 3. 标准 logging 挂文件 handler
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(otelTraceID)s | %(message)s"
    )

    # 全量日志：每日轮转，保留 30 天
    file_handler = TimedRotatingFileHandler(
        log_dir / "app.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    # 错误日志：每日轮转，保留 90 天
    error_handler = TimedRotatingFileHandler(
        log_dir / "error.log",
        when="midnight",
        backupCount=90,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    # 4. 配置 root logger
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(logfire_handler)
    root.addHandler(file_handler)
    root.addHandler(error_handler)

    # 5. 抑制第三方库噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
