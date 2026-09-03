"""
管理端接口（仅 admin，普通用户 403）：
统计仪表盘（M6 完整版）：问答量/命中率/延迟/token/Top 查询/反馈占比/7 日趋势。
数据源 = qa_logs + feedback + 基础表（与 qa_logs 明细严格一致）。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.base import get_db
from app.db.models import Chunk, Document, Feedback, Message, QaLog, User

router = APIRouter(tags=["管理"])


@router.get("/admin/stats", summary="统计仪表盘（仅管理员）")
async def stats(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """仪表盘全量指标（M6）：概览卡片 + 图表数据一次返回"""

    # ---- 概览指标 ----
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    doc_count = (await db.execute(select(func.count(Document.id)))).scalar() or 0
    chunk_count = (await db.execute(select(func.count(Chunk.id)))).scalar() or 0
    msg_count = (await db.execute(
        select(func.count(Message.id)).where(Message.role == "assistant")
    )).scalar() or 0

    # ---- 问答质量/性能（qa_logs 聚合）----
    qa_row = (await db.execute(select(
        func.count(QaLog.id),
        func.avg(QaLog.latency_ms),
        func.avg(QaLog.first_token_ms),
        func.sum(QaLog.token_usage),
    ))).one()
    total_qa, avg_latency, avg_first_token, total_tokens = qa_row
    hit_count = (await db.execute(
        select(func.count(QaLog.id)).where(QaLog.hit == 1)
    )).scalar() or 0
    hit_rate = round(hit_count / total_qa, 4) if total_qa else 0

    # ---- Top 5 高频查询 ----
    top_rows = (await db.execute(
        select(QaLog.query, func.count(QaLog.id).label("cnt"))
        .group_by(QaLog.query)
        .order_by(func.count(QaLog.id).desc())
        .limit(5)
    )).all()
    top_queries = [{"query": q, "count": c} for q, c in top_rows]

    # ---- 反馈占比 ----
    like_count = (await db.execute(
        select(func.count(Feedback.id)).where(Feedback.rating == 1)
    )).scalar() or 0
    dislike_count = (await db.execute(
        select(func.count(Feedback.id)).where(Feedback.rating == -1)
    )).scalar() or 0

    # ---- 近 7 日问答量趋势 ----
    since = datetime.now() - timedelta(days=7)
    trend_rows = (await db.execute(
        select(func.date(QaLog.created_at).label("day"), func.count(QaLog.id))
        .where(QaLog.created_at >= since)
        .group_by(func.date(QaLog.created_at))
        .order_by(func.date(QaLog.created_at))
    )).all()
    trend = [{"date": str(day), "count": cnt} for day, cnt in trend_rows]

    return {
        "overview": {
            "user_count": user_count,
            "document_count": doc_count,
            "chunk_count": chunk_count,
            "answer_count": msg_count,
        },
        "quality": {
            "total_queries": total_qa or 0,
            "hit_rate": hit_rate,
            "avg_latency_ms": round(avg_latency or 0),
            "avg_first_token_ms": round(avg_first_token or 0),
            "total_tokens": total_tokens or 0,
        },
        "top_queries": top_queries,
        "feedback": {"like": like_count, "dislike": dislike_count},
        "trend": trend,
    }
