"""
健康检查接口：验证数据库连通性，暴露模型加载状态。
供前端启动探测与演示使用。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.base import get_db

router = APIRouter(tags=["运维"])
log = get_logger(__name__)


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """
    健康检查：db=数据库连通状态；model_ready=Embedding/Rerank 是否加载完成。
    任一核心依赖异常时 status 置 degraded。
    """
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 —— 健康检查需吞掉异常只报状态
        db_ok = False
        log.warning("health.db_check_failed", error=str(exc))

    settings = get_settings()
    from app.services.embeddings import is_ready as model_ready

    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "down",
        "model_ready": model_ready(),   # Embedding 是否就绪（lifespan 预热）
        "embedding_provider": settings.embedding_provider,
        "embedding_model": (
            settings.embedding_api_model
            if settings.embedding_provider == "api"
            else settings.embedding_model
        ),
        "rerank_provider": settings.rerank_provider,
        "llm_model": settings.llm_model,
        "llm_thinking": settings.llm_enable_thinking,
        "version": "0.1.0",
    }
