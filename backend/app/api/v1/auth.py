"""认证接口：注册 / 登录 / 修改密码 / 当前用户信息"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.db.base import get_db
from app.db.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services import auth_service

router = APIRouter(tags=["认证"])


@router.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册",
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册新账号（普通用户角色）"""
    return await auth_service.register_user(db, body.username, body.password)


@router.post("/auth/login", response_model=TokenResponse, summary="登录")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录：返回 JWT（24h）与用户信息"""
    user = await auth_service.authenticate(db, body.username, body.password)
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        user=UserOut.model_validate(user),
    )


@router.put("/auth/password", summary="修改密码")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改密码（需登录；校验原密码）"""
    await auth_service.change_password(db, user, body.old_password, body.new_password)
    return {"message": "密码修改成功"}


@router.get("/users/me", response_model=UserOut, summary="当前用户信息")
async def me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return user
