"""
异步文档任务队列（无 Celery/Redis 依赖）：
asyncio 任务 + 进程内注册表 + 启动恢复。
任务状态以 MySQL documents 表为准，进程崩溃后可自愈。
"""
import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import Document
from app.services.rag.ingest import run_ingest

log = get_logger(__name__)

# 进程内运行中的任务注册表（doc_id → Task）
_running: dict[str, asyncio.Task] = {}

# 入库并发闸门：worker 并发=1（串行化避免 MySQL 死锁；批量向量化时也限流）
_ingest_semaphore = asyncio.Semaphore(1)

# 非终态状态集合（启动恢复用）
NON_TERMINAL = ("uploaded", "parsing", "cleaning", "chunking", "embedding", "indexing")


def submit_ingest(doc_id: str) -> None:
    """提交入库后台任务（同一文档重复提交时取消旧任务再起新任务）"""
    old = _running.pop(doc_id, None)
    if old and not old.done():
        old.cancel()
    task = asyncio.create_task(_safe_run(doc_id))
    _running[doc_id] = task


async def _safe_run(doc_id: str) -> None:
    """包裹 run_ingest：限并发（防死锁）+ 吞掉取消异常 + 清理注册表"""
    try:
        async with _ingest_semaphore:
            await run_ingest(doc_id)
    except asyncio.CancelledError:
        log.warning("ingest.cancelled", doc_id=doc_id)
    finally:
        _running.pop(doc_id, None)


async def recover_stale_documents() -> int:
    """
    启动恢复：上次进程退出时中断的入库任务统一标记 failed（可重试），
    避免文档永远卡在中间状态。
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.status.in_(NON_TERMINAL))
        )
        stale = result.scalars().all()
        for doc in stale:
            doc.status = "failed"
            doc.error_msg = "服务重启导致任务中断，可点击重试"
        await session.commit()
        if stale:
            log.warning("ingest.recovered_stale", count=len(stale))
        return len(stale)
