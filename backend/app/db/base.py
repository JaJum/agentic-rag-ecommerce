"""
SQLAlchemy 异步引擎与会话工厂：
- MySQL：连接池 10 常驻 + 20 溢出，pool_pre_ping 自动剔除断连
- SQLite（Lite/CI）：不传 pool_size（不支持），开启外键约束
"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.db.compat import is_sqlite


class Base(DeclarativeBase):
    """ORM 基类：models.py 中所有表继承它，metadata 用于 create_all 建表"""


settings = get_settings()
_url = settings.database_url

# 连接池参数只对 MySQL/PostgreSQL 这类真实连接池有意义；
# SQLite 走默认池，传 pool_size 会直接抛 TypeError。
_engine_kwargs: dict = {"pool_pre_ping": True, "echo": False}
if not is_sqlite(_url):
    _engine_kwargs.update(pool_size=10, max_overflow=20)

engine = create_async_engine(_url, **_engine_kwargs)

if is_sqlite(_url):
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragma(dbapi_conn, _record):  # pragma: no cover - 连接级副作用
        """SQLite 默认不校验外键，Lite 模式显式打开，保持与 MySQL 行为一致"""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# 会话工厂：expire_on_commit=False 避免提交后属性过期导致懒加载报错
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI 依赖：每个请求一个独立会话，请求结束自动关闭"""
    async with AsyncSessionLocal() as session:
        yield session