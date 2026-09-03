"""
SQLAlchemy 异步引擎与会话工厂：
连接池 10 常驻 + 20 溢出，pool_pre_ping 自动剔除断连。
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """ORM 基类：models.py 中所有表继承它，metadata 用于 create_all 建表"""


settings = get_settings()

# 异步引擎（连接池参数为企业级并发预留）
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

# 会话工厂：expire_on_commit=False 避免提交后属性过期导致懒加载报错
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI 依赖：每个请求一个独立会话，请求结束自动关闭"""
    async with AsyncSessionLocal() as session:
        yield session
