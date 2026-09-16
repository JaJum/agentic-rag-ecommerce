"""
转人工工单（A-10）。

写操作受 AGENT_ALLOW_WRITE_TOOLS 控制：
- true  ：写入 handoff_tickets 表
- false ：只生成工单号并返回模拟结果（默认，演示/CI 安全）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


def new_ticket_id() -> str:
    """生成可读工单号：HD-20261110-A1B2"""
    return f"HD-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"


async def create_handoff(
    reason: str,
    summary: str,
    session_id: str | None = None,
    user_id: int | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """创建转人工工单；persist=False 时只返回模拟结果"""
    ticket_id = new_ticket_id()
    record: dict[str, Any] = {
        "ticket_id": ticket_id,
        "reason": (reason or "").strip()[:255],
        "summary": (summary or "").strip()[:1000],
        "persisted": False,
    }
    if not persist:
        log.info("agent.handoff.simulated", ticket_id=ticket_id, reason=record["reason"])
        return record

    from app.db.base import AsyncSessionLocal
    from app.db.models import HandoffTicket

    async with AsyncSessionLocal() as session:
        session.add(
            HandoffTicket(
                id=ticket_id,
                session_id=session_id,
                user_id=user_id,
                reason=record["reason"],
                summary=record["summary"],
            )
        )
        await session.commit()

    record["persisted"] = True
    log.info("agent.handoff.created", ticket_id=ticket_id, reason=record["reason"])
    return record