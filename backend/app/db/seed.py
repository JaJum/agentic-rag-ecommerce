"""
种子数据：启动时确保存在管理员账号 admin/123456（需求 6）。
幂等实现——已存在则跳过。注意：123456 为演示初始密码，答辩后应修改。
"""
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import User

log = get_logger(__name__)


async def seed_admin() -> None:
    """初始化管理员账号（幂等）"""
    import bcrypt

    async with AsyncSessionLocal() as session:
        exists = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one_or_none()
        if exists:
            return
        pwd_hash = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        session.add(User(username="admin", password_hash=pwd_hash, role="admin"))
        await session.commit()
        log.info("seed.admin_created", username="admin")
