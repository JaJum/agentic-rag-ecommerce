"""
FastAPI 应用入口：
lifespan（建表+种子+模型预热预留）、trace_id 中间件、CORS、全局异常处理、路由注册。
启动命令：uvicorn app.main:app --reload --port 8000（在 backend/ 目录下）
"""
import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import BizError, biz_error_handler, generic_error_handler
from app.core.logging import get_logger, setup_logging
from app.db.base import AsyncSessionLocal, Base, engine
from app.db.models import Chunk
from app.db.seed import seed_admin
from app.services import embeddings, reranker
from app.services.agent.catalog import refresh_catalog
from app.services.bm25_index import bm25_index
from app.services.tasks import recover_stale_documents

setup_logging()
log = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动建表 + 种子数据；退出释放连接池"""
    # 建表（幂等，已存在跳过）+ 枚举迁移 + 管理员种子
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_message_status(conn)
        await _migrate_agent_columns(conn)
    await seed_admin()
    # 启动恢复：把上次中断的入库任务标记 failed（可重试），避免卡中间状态
    recovered = await recover_stale_documents()
    # 预热 BGE-M3 + reranker（常驻单例，避免首请求冷启动；M5 压测教训：reranker 也要预热）
    await asyncio.to_thread(embeddings.get_embedding_model)
    await asyncio.to_thread(reranker.get_reranker)
    await rebuild_bm25_on_startup()
    await _refresh_catalog_safe()
    log.info("app.started", llm_model=settings.llm_model, thinking=settings.llm_enable_thinking, recovered=recovered)
    yield
    await engine.dispose()
    log.info("app.stopped")


app = FastAPI(
    title="LangChain RAG 电商知识库问答系统",
    description="基于 LangChain 的 RAG 企业级知识库问答系统（毕设）",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS：仅放行前端 dev 服务器（企业级安全基线）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _migrate_message_status(conn) -> None:
    """
    幂等迁移：messages.status 枚举扩展 general/fallback（智能兜底，2026-11-09）。
    create_all 不会修改已存在的表，故存量库在此补齐；新库由模型定义直接建成。
    """
    col = (await conn.execute(text(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='messages' AND COLUMN_NAME='status'"
    ))).scalar()
    if col and "general" not in col:
        await conn.execute(text(
            "ALTER TABLE messages MODIFY COLUMN status "
            "ENUM('complete','partial','error','general','fallback') "
            "NOT NULL DEFAULT 'complete' "
            "COMMENT 'complete=完整 partial=断连截断 error=失败 general=通用闲聊回答(非知识库) fallback=兜底拒答'"
        ))
        log.info("migrate.message_status_extended")


async def _migrate_agent_columns(conn) -> None:
    """幂等迁移：qa_logs 增加 route / tool_count（存量 MySQL 库补齐；新库由模型直接建成）"""
    if conn.dialect.name != "mysql":
        return
    cols = (await conn.execute(text(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='qa_logs'"
    ))).scalars().all()
    if "route" not in cols:
        await conn.execute(text(
            "ALTER TABLE qa_logs ADD COLUMN route VARCHAR(16) NULL "
            "COMMENT '路由/来源：chitchat|kb_simple|business|multi_hop|rag|cache'"
        ))
        log.info("migrate.qa_logs_route_added")
    if "tool_count" not in cols:
        await conn.execute(text(
            "ALTER TABLE qa_logs ADD COLUMN tool_count INT NULL COMMENT 'Agent 工具调用步数'"
        ))
        log.info("migrate.qa_logs_tool_count_added")


async def _refresh_catalog_safe() -> None:
    """启动时加载商品目录；失败只告警，不阻塞服务启动"""
    try:
        catalog = await refresh_catalog()
        log.info("agent.catalog.ready", products=catalog.size())
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.catalog.startup_failed", error=str(exc))


async def rebuild_bm25_on_startup() -> None:
    """启动时从 MySQL chunks 全量重建 BM25 索引（进程内索引，重启即重建）"""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Chunk.id, Chunk.text))).all()
    bm25_index.rebuild([(r.id, r.text) for r in rows])


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """trace_id 中间件：为每个请求生成追踪号并绑定 structlog 上下文（贯穿全链路日志）"""
    import structlog

    trace_id = uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id
    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
    finally:
        structlog.contextvars.clear_contextvars()


# 全局异常处理：业务异常 → 友好 JSON；未捕获 → 500（不泄露堆栈）
app.add_exception_handler(BizError, biz_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

# 注册业务路由（/api/v1/*）
app.include_router(api_router, prefix="/api/v1")
