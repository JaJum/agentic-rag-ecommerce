"""会话接口：多用户多会话管理（需求 3/4）"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.schemas.chat import SessionCreate, SessionOut, SessionUpdate
from app.services import session_service

router = APIRouter(prefix="/sessions", tags=["会话"])


@router.get("", response_model=list[SessionOut], summary="会话列表")
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户的会话列表（按最近更新倒序）"""
    return await session_service.list_sessions(db, user.id)


@router.post("", response_model=SessionOut, summary="新建会话")
async def create_session(
    body: SessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建会话（标题可选，默认「新会话」）"""
    return await session_service.create_session(db, user.id, body.title)


@router.patch("/{session_id}", response_model=SessionOut, summary="重命名会话")
async def rename_session(
    session_id: str,
    body: SessionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """重命名会话"""
    session = await session_service.get_user_session(db, user.id, session_id)
    await session_service.rename_session(db, session, body.title)
    return session


@router.delete("/{session_id}", summary="删除会话（软删）")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """软删会话：历史保留可找回（需求 4）"""
    session = await session_service.get_user_session(db, user.id, session_id)
    await session_service.soft_delete_session(db, session)
    return {"message": "删除成功"}


@router.get("/{session_id}/messages", summary="历史消息（含引用）")
async def session_messages(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """历史消息列表：重新登录可找回完整对话与引用（需求 4）"""
    await session_service.get_user_session(db, user.id, session_id)
    return await session_service.list_messages(db, session_id)
