"""
FastAPI 依赖注入：
- get_current_user：解析 Authorization 头获取当前用户（缺失/无效 → 401）
- require_admin：仅放行管理员（普通用户 → 403），与前端路由守卫构成双重控制
"""
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_token
from app.db.base import get_db
from app.db.models import User


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """从请求头解析 Bearer token，返回用户实体（供业务接口注入）"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AuthError()
    payload = decode_token(auth_header.removeprefix("Bearer ").strip())
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise AuthError("用户不存在或已注销")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员校验：非 admin 角色返回 403"""
    if user.role != "admin":
        raise ForbiddenError("仅管理员可执行此操作")
    return user
