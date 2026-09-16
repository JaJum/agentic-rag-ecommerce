"""
商品目录索引（A-05）。

从 chunk_type='param' 的知识块构建「商品名 / 商品 ID → 结构化字段」索引，
供 get_product_spec / compare_products 使用：
- 避免每次参数查询都走向量检索（更快、更准、可解释）
- 保留来源 chunk，最终回答仍可引用原文

索引在启动时加载，文档入库完成后刷新。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

from sqlalchemy import select

from app.core.logging import get_logger

log = get_logger(__name__)

# 「键: 值」行（兼容中英文冒号）
_KV = re.compile(r"^\s*([^:：]{1,40})\s*[:：]\s*(.*?)\s*$")
# 归一化时移除的空白与标点
_PUNCT = re.compile(r"[\s（）()【】\[\]·\-_/]+")
# 品类后缀：仅用于相似度打分，不改变展示名称
_CATEGORY = ("智能手机", "无线耳机", "降噪耳机", "笔记本电脑", "平板电脑", "智能手环", "充电器", "台灯")

# 常见问法 → 字段名（用于字段过滤）
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "价格": ("价格", "售价", "多少钱", "价位", "报价", "贵"),
    "重量": ("重量", "多重", "克重"),
    "电池容量": ("电池", "电池容量", "续航"),
    "屏幕尺寸": ("屏幕", "屏幕尺寸"),
    "颜色": ("颜色", "配色"),
    "品牌": ("品牌",),
    "名称": ("名称", "型号", "叫什么"),
    "上市时间": ("上市", "上市时间", "发布时间"),
}


def _norm(text: str) -> str:
    """归一化：小写、去空白与常见标点"""
    return _PUNCT.sub("", (text or "").lower())


def _core(text: str) -> str:
    """去掉品类后缀后的核心名称（仅用于相似度）"""
    out = _norm(text)
    for word in _CATEGORY:
        out = out.replace(word.lower(), "")
    return out


def parse_param_text(text: str) -> dict[str, str]:
    """解析参数块「字段: 值」为字典（忽略无法识别的行）"""
    fields: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _KV.match(line)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            if key and value and value not in ("-", "—", "/"):
                fields[key] = value
    return fields


def match_fields(fields: dict[str, str], requested: Iterable[str] | None) -> dict[str, str]:
    """按用户请求的字段名做宽松匹配（支持别名与子串）"""
    if not requested:
        return dict(fields)
    terms = [str(t).strip().lower() for t in requested if str(t).strip()]
    out: dict[str, str] = {}
    for key, value in fields.items():
        key_low = key.lower()
        aliases = FIELD_ALIASES.get(key, ())
        for term in terms:
            if term in key_low or key_low in term or any(term in a for a in aliases):
                out[key] = value
                break
    return out


@dataclass
class ProductRecord:
    """一个商品的参数与来源信息"""

    product_id: str
    name: str
    fields: dict[str, str]
    chunk_id: str
    doc_id: str
    doc_name: str
    raw_text: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_context(self, source_tool: str) -> dict[str, Any]:
        """转为统一知识块，供最终回答引用"""
        meta = dict(self.meta)
        meta.update({"doc_name": self.doc_name, "product_id": self.product_id})
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "chunk_type": "param",
            "text": self.raw_text,
            "snippet": self.raw_text[:120],
            "score": 1.0,
            "meta": meta,
            "source_tool": source_tool,
        }


class ProductCatalog:
    """进程内商品目录（参数块数量级：百~千，全量常驻无压力）"""

    def __init__(self) -> None:
        self._records: list[ProductRecord] = []
        self._by_key: dict[str, ProductRecord] = {}

    def rebuild(self, rows: list[dict[str, Any]]) -> None:
        """重建目录。rows: {chunk_id, doc_id, doc_name, text, meta}"""
        records: list[ProductRecord] = []
        by_key: dict[str, ProductRecord] = {}
        for row in rows:
            fields = parse_param_text(row.get("text", ""))
            name = fields.get("名称") or fields.get("商品名称") or ""
            pid = fields.get("商品ID") or fields.get("product_id") or (row.get("meta") or {}).get("product_id", "")
            if not name and not pid:
                continue
            record = ProductRecord(
                product_id=str(pid),
                name=name or str(pid),
                fields=fields,
                chunk_id=row.get("chunk_id", ""),
                doc_id=row.get("doc_id", ""),
                doc_name=row.get("doc_name", "未知来源"),
                raw_text=row.get("text", ""),
                meta=dict(row.get("meta") or {}),
            )
            records.append(record)
            if record.product_id:
                by_key[_norm(record.product_id)] = record
            by_key[_norm(record.name)] = record
        self._records = records
        self._by_key = by_key
        log.info("agent.catalog.rebuilt", products=len(records))

    def size(self) -> int:
        return len(self._records)

    def all(self) -> list[ProductRecord]:
        return list(self._records)

    def resolve(self, query: str, limit: int = 5) -> tuple[ProductRecord | None, list[ProductRecord]]:
        """
        解析用户输入的商品名/ID。
        返回 (唯一命中或 None, 候选列表)。
        规则：精确 > 包含 > 相似度；多个包含时优先最短名称（基础款）。
        """
        q = _norm(query)
        if not q or not self._records:
            return None, []

        exact = self._by_key.get(q)
        if exact:
            return exact, [exact]

        contains = [r for r in self._records if q in _norm(r.name) or _norm(r.name) in q]
        if len(contains) == 1:
            return contains[0], contains
        if len(contains) > 1:
            # 「星河 X5」同时命中 X5 与 X5 Pro：优先最短名称（基础款）
            shortest = min(contains, key=lambda r: len(_core(r.name)))
            return shortest, contains

        scored = sorted(
            ((self._similarity(q, r), r) for r in self._records),
            key=lambda item: item[0],
            reverse=True,
        )
        candidates = [r for score, r in scored[:limit] if score >= 0.55]
        # 短输入（如「星河X9」）更容易一字之差误命中，阈值收紧
        threshold = 0.85 if len(_core(q)) <= 6 else 0.72
        if scored and scored[0][0] >= threshold:
            if len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08:
                return scored[0][1], candidates
        return None, candidates

    @staticmethod
    def _similarity(q: str, record: ProductRecord) -> float:
        """归一化相似度：核心名相同/包含给高分，否则用序列相似度"""
        core_q, core_n = _core(q), _core(record.name)
        if not core_q or not core_n:
            return 0.0
        if core_q == core_n:
            return 1.0
        if core_q in core_n or core_n in core_q:
            return 0.95
        # 型号数字不同（X9 vs X5）直接判为不相似，避免一字之差误命中
        q_digits = re.findall(r"\d+", core_q)
        n_digits = re.findall(r"\d+", core_n)
        if q_digits and n_digits and q_digits != n_digits:
            return 0.0
        return SequenceMatcher(None, core_q, core_n).ratio()


_catalog: ProductCatalog | None = None


def get_catalog() -> ProductCatalog:
    """获取进程内商品目录单例（未加载时为空目录）"""
    global _catalog
    if _catalog is None:
        _catalog = ProductCatalog()
    return _catalog


async def refresh_catalog() -> ProductCatalog:
    """从 MySQL 重新加载全部参数块（启动 / 入库完成后调用）"""
    from app.db.base import AsyncSessionLocal
    from app.db.models import Chunk, Document

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Chunk, Document.orig_name)
                .join(Document, Chunk.doc_id == Document.id)
                .where(Chunk.chunk_type == "param")
            )
        ).all()

    catalog = get_catalog()
    catalog.rebuild(
        [
            {
                "chunk_id": chunk.id,
                "doc_id": chunk.doc_id,
                "doc_name": doc_name,
                "text": chunk.text,
                "meta": dict(chunk.meta or {}),
            }
            for chunk, doc_name in rows
        ]
    )
    return catalog
def reset_catalog() -> None:
    """清空进程内目录（仅测试/演示重置用）"""
    global _catalog
    _catalog = ProductCatalog()
