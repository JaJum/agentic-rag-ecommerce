"""认证业务逻辑：注册 / 登录 / 修改密码（数据访问与规则集中在服务层）"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError, BizError
from app.core.security import hash_password, verify_password
from app.db.models import User


async def register_user(db: AsyncSession, username: str, password: str) -> User:
    """注册新用户（默认 user 角色）；用户名重复抛 409"""
    exists = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if exists:
        raise BizError("用户名已被注册", code="USERNAME_TAKEN", status_code=409)
    user = User(username=username, password_hash=hash_password(password), role="user")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, username: str, password: str) -> User:
    """登录校验：用户名不存在与密码错误统一提示，避免账号枚举"""
    user = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("用户名或密码错误")
    return user


async def change_password(
    db: AsyncSession, user: User, old_password: str, new_password: str
) -> None:
    """修改密码：校验原密码后写入新哈希（需求 5）"""
    if not verify_password(old_password, user.password_hash):
        raise BizError("原密码错误", code="WRONG_OLD_PASSWORD")
    if old_password == new_password:
        raise BizError("新密码不能与原密码相同", code="SAME_PASSWORD")
    user.password_hash = hash_password(new_password)
    await db.commit()
