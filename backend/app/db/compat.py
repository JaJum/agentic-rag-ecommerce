"""
跨数据库类型适配。

同一套 ORM 模型要能在两种环境建表：
- MySQL 8：生产/演示环境（DATETIME(6) 微秒精度、MEDIUMTEXT 16MB、BIGINT 自增）
- SQLite：Lite 模式 / CI（无需安装数据库即可跑通 Agent 全链路）

SQLite 的两个硬约束：
1. 只有 INTEGER PRIMARY KEY 才会自增，BIGINT 主键插入时报 NOT NULL
2. 不支持 DATETIME(6) / MEDIUMTEXT 语法
"""
from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.types import BigInteger

# 主键/外键都用它：MySQL 为 BIGINT，SQLite 降级为 INTEGER（保证自增）
BigInt = BigInteger().with_variant(Integer, "sqlite")

# 微秒时间戳：MySQL 用 DATETIME(6)，其它方言退回标准 DateTime
Ts6 = DateTime().with_variant(MYSQL_DATETIME(fsp=6), "mysql")

# 长文本：MySQL 用 MEDIUMTEXT，其它方言用 TEXT
LongText = Text().with_variant(MEDIUMTEXT, "mysql")


def is_sqlite(url: str) -> bool:
    """连接串是否指向 SQLite（决定引擎参数与迁移策略）"""
    return url.startswith("sqlite")