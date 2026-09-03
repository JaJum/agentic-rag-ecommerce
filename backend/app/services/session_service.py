"""会话业务逻辑：多用户多会话管理（需求 3/4），数据按 user_id 隔离"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.db.models import ChatSession, Message, MessageCitation


async def get_user_session(db: AsyncSession, user_id: int, session_id: str) -> ChatSession:
    """
    获取属于该用户的会话（越权访问 → 404，不泄露他人会话存在性）。
    """
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id or session.deleted_at is not None:
        raise BizError("会话不存在", code="SESSION_NOT_FOUND", status_code=404)
    return session


async def list_sessions(db: AsyncSession, user_id: int) -> list[ChatSession]:
    """会话列表（未删除，按最近更新倒序）"""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id, ChatSession.deleted_at.is_(None))
        .order_by(ChatSession.updated_at.desc())
    )
    return result.scalars().all()


async def create_session(db: AsyncSession, user_id: int, title: str | None = None) -> ChatSession:
    """新建会话"""
    session = ChatSession(user_id=user_id, title=title or "新会话")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def rename_session(db: AsyncSession, session: ChatSession, title: str) -> None:
    """重命名会话"""
    session.title = title
    await db.commit()


async def soft_delete_session(db: AsyncSession, session: ChatSession) -> None:
    """软删会话（历史保留，可找回；需求 4）"""
    from datetime import datetime

    session.deleted_at = datetime.now()
    await db.commit()


async def touch_session(db: AsyncSession, session_id: str) -> None:
    """更新会话时间戳（让会话在列表中置顶）"""
    from datetime import datetime

    await db.execute(
        update(ChatSession)
        .where(ChatSession.id == session_id)
        .values(updated_at=datetime.now())
    )


async def list_messages(db: AsyncSession, session_id: str, limit: int = 200) -> list[dict]:
    """
    历史消息（含引用，按时间升序）。
    引用读 messages.citations JSON 冗余快照（文档删除后仍可回放，需求 4）。
    """
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
        .limit(limit)
    )
    out = []
    for m in result.scalars().all():
        out.append(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "rewritten_query": m.rewritten_query,
                "citations": m.citations or [],
                "status": m.status,
                "created_at": m.created_at,
            }
        )
    return out


async def get_citations(db: AsyncSession, message_id: str) -> list[dict]:
    """查询某回答的引用列表（来自 message_citations 表）"""
    result = await db.execute(
        select(MessageCitation)
        .where(MessageCitation.message_id == message_id)
        .order_by(MessageCitation.citation_no)
    )
    return [
        {
            "citation_no": c.citation_no,
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "snippet": c.snippet,
            "score": c.score,
            "cited": bool(c.cited),
        }
        for c in result.scalars().all()
    ]
