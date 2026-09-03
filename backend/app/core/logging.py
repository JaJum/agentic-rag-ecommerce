"""
structlog 结构化日志：
JSON/彩色输出 + trace_id 贯穿全链路（请求→改写→检索→生成）。
"""
import logging

import structlog


def setup_logging(level: int = logging.INFO) -> None:
    """初始化 structlog（进程启动时调用一次）"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,   # 合并 trace_id 等上下文变量
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),           # 开发期彩色可读输出
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """获取带模块名的结构化 logger"""
    return structlog.get_logger(name)
