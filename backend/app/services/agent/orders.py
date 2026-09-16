"""
Mock 订单查询（A-08）。

演示环境不连接真实订单系统，数据固定存放在 sample_data/mock_orders.json。
只读、无副作用；对外输出前统一做手机号打码。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.agent.trace import mask_sensitive

log = get_logger(__name__)

# 订单号白名单：防注入与异常输入
ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{6,32}$")

# 项目根目录：本文件位于 backend/app/services/agent/
_DATA_FILE = Path(__file__).resolve().parents[4] / "sample_data" / "mock_orders.json"


@lru_cache(maxsize=1)
def _load_orders() -> dict[str, dict[str, Any]]:
    """加载订单数据（按订单号索引）；文件缺失时返回空字典而不是崩溃"""
    if not _DATA_FILE.exists():
        log.warning("agent.orders.data_missing", path=str(_DATA_FILE))
        return {}
    try:
        rows = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("agent.orders.data_invalid", error=str(exc))
        return {}
    return {str(row.get("order_id", "")).upper(): row for row in rows if row.get("order_id")}


def is_valid_order_id(order_id: str) -> bool:
    return bool(ORDER_ID_PATTERN.match((order_id or "").strip()))


def find_order(order_id: str) -> dict[str, Any] | None:
    """按订单号查询（大小写不敏感）"""
    return _load_orders().get((order_id or "").strip().upper())


def format_order(order: dict[str, Any]) -> str:
    """把订单记录格式化为客服可读文本（敏感字段打码）"""
    lines = [
        f"订单号：{order.get('order_id', '-')}",
        f"商品：{order.get('product', '-')}",
        f"状态：{order.get('status', '-')}",
        f"金额：¥{order.get('amount', '-')}",
        f"下单时间：{order.get('created_at', '-')}",
        f"物流：{order.get('logistics', '-')}",
        f"收货人电话：{mask_sensitive(str(order.get('phone', '-')))}",
    ]
    return "\n".join(lines)