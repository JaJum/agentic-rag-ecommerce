"""
Agent 工具集（M8）。

统一约定：
- 所有工具返回 (content, artifact)；artifact["contexts"] 为可引用的知识块。
- 工具只负责取数与格式化，不做最终回答；最终生成仍由 generation 层完成。
- 任何异常都转成结构化错误返回，交给 Agent 决定重试或放弃，不直接抛给请求层。
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.agent.catalog import get_catalog, match_fields, refresh_catalog
from app.services.agent.handoff import create_handoff
from app.services.agent.orders import find_order, format_order, is_valid_order_id
from app.services.bm25_index import bm25_index
from app.services.rag.retrieval import hybrid_search, is_relevant, rerank_top

log = get_logger(__name__)

EMPTY_RESULT_TEXT = "知识库中未检索到相关内容。"


class ToolTimeoutError(RuntimeError):
    """工具执行超时（由 guardrail 捕获并转结构化错误）"""

# 工具统一返回类型
ToolResult = tuple[str, dict[str, Any]]


def format_contexts(contexts: list[dict[str, Any]]) -> str:
    """把知识块格式化为带编号的文本，编号与 finalize 阶段 build_context_block 一致"""
    blocks: list[str] = []
    for i, c in enumerate(contexts, start=1):
        meta = c.get("meta") or {}
        source = c.get("doc_name") or meta.get("doc_name") or "未知来源"
        section = meta.get("section") or meta.get("product_id") or ""
        header = f"[{i}] 来源：{source}" + (f"（{section}）" if section else "")
        blocks.append(f"{header}\n{c.get('text', '')}")
    return "\n\n".join(blocks)


def make_context(raw: dict[str, Any], source_tool: str, doc_name: str = "") -> dict[str, Any]:
    """把检索原始结果规范化为统一知识块结构"""
    meta = dict(raw.get("meta") or {})
    name = doc_name or raw.get("doc_name") or meta.get("doc_name") or "未知来源"
    meta["doc_name"] = name
    text = raw.get("text") or ""
    score = raw.get("rerank_score")
    if score is None:
        score = raw.get("rrf_score")
    if score is None:
        score = raw.get("bm25_score", 0.0)
    return {
        "chunk_id": raw.get("chunk_id") or meta.get("chunk_id", ""),
        "doc_id": raw.get("doc_id") or meta.get("doc_id", ""),
        "doc_name": name,
        "chunk_type": raw.get("chunk_type") or meta.get("chunk_type", ""),
        "text": text,
        "snippet": text[:120],
        "score": float(score or 0.0),
        "meta": meta,
        "source_tool": source_tool,
    }


def synthetic_context(text: str, source: str, source_tool: str, ref_id: str, chunk_type: str = "") -> dict[str, Any]:
    """为订单/工单等非知识库事实构造可引用上下文"""
    return {
        "chunk_id": f"{source_tool}:{ref_id}",
        "doc_id": "",
        "doc_name": source,
        "chunk_type": chunk_type or source_tool,
        "text": text,
        "snippet": text[:120],
        "score": 1.0,
        "meta": {"doc_name": source, "ref_id": ref_id},
        "source_tool": source_tool,
    }


def _dedupe(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 chunk_id 去重并保持顺序（同一块可能被多路召回）"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in contexts:
        cid = c.get("chunk_id") or c.get("text", "")[:64]
        if cid in seen:
            continue
        seen.add(cid)
        out.append(c)
    return out


async def _fetch_chunks(ids: list[str]) -> dict[str, dict[str, Any]]:
    """按 chunk_id 从 MySQL 取原文与文档名（BM25 只返回 id，需要补全文本）"""
    if not ids:
        return {}
    from sqlalchemy import select

    from app.db.base import AsyncSessionLocal
    from app.db.models import Chunk, Document

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Chunk, Document.orig_name)
                .join(Document, Chunk.doc_id == Document.id)
                .where(Chunk.id.in_(ids))
            )
        ).all()
    return {
        chunk.id: {
            "chunk_id": chunk.id,
            "doc_id": chunk.doc_id,
            "doc_name": doc_name,
            "chunk_type": chunk.chunk_type,
            "text": chunk.text,
            "meta": dict(chunk.meta or {}),
        }
        for chunk, doc_name in rows
    }


async def _search_hybrid(
    query: str, k: int, chunk_types: set[str] | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """混合检索 + rerank；rerank 不可用时退回 RRF 排序（保证 Lite 模式可用）"""
    candidates = await asyncio.to_thread(hybrid_search, query)
    if chunk_types:
        candidates = [
            c for c in candidates if (c.get("meta") or {}).get("chunk_type") in chunk_types
        ]
    if not candidates:
        return [], False
    try:
        ranked = await asyncio.to_thread(rerank_top, query, candidates)
        relevant = is_relevant(ranked)
        return [make_context(c, "search_knowledge_base") for c in ranked[:k]], relevant
    except Exception as exc:  # noqa: BLE001 —— 模型不可用时降级，不阻塞问答
        log.warning("agent.tool.rerank_failed", error=str(exc))
        return [make_context(c, "search_knowledge_base") for c in candidates[:k]], True


async def _search_bm25(
    query: str, k: int, chunk_types: set[str] | None = None
) -> list[dict[str, Any]]:
    """BM25 单路检索（RETRIEVAL_MODE=bm25 / 无 embedding 时使用）"""
    hits = bm25_index.search(query, k=k * 3 if chunk_types else k)
    if not hits:
        return []
    rows = await _fetch_chunks([cid for cid, _ in hits])
    score_map = dict(hits)
    ordered: list[dict[str, Any]] = []
    for cid, _ in hits:
        row = rows.get(cid)
        if not row:
            continue
        if chunk_types and row.get("chunk_type") not in chunk_types:
            continue
        ordered.append(
            make_context({**row, "bm25_score": score_map.get(cid, 0.0)}, "search_knowledge_base")
        )
        if len(ordered) >= k:
            break
    return ordered


async def _search_contexts(
    query: str, k: int, chunk_types: set[str] | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """按检索模式分发，返回 (上下文, 是否相关)；带单工具超时保护"""
    settings = get_settings()
    timeout = float(settings.agent_tool_timeout_s or 8)

    async def _dispatch():
        if settings.retrieval_mode == "bm25" or settings.embedding_provider == "none":
            contexts = await _search_bm25(query, k, chunk_types)
            return _dedupe(contexts)[:k], bool(contexts)
        return await _search_hybrid(query, k, chunk_types)

    try:
        return await asyncio.wait_for(_dispatch(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ToolTimeoutError(f"检索超时（>{timeout:g}s）") from exc


async def _search_knowledge_base_impl(query: str, top_k: int = 5) -> ToolResult:
    """search_knowledge_base 的实际实现（便于单测直接调用）"""
    query = (query or "").strip()
    if not query:
        return EMPTY_RESULT_TEXT, {"contexts": [], "error": "empty_query", "query": query}

    k = max(1, min(int(top_k or 5), 8))
    try:
        contexts, relevant = await _search_contexts(query, k)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.tool.search_failed", query=query, error=str(exc))
        return f"知识库检索失败：{str(exc)[:200]}", {
            "contexts": [],
            "error": str(exc)[:200],
            "query": query,
        }

    contexts = _dedupe(contexts)[:k]
    if not contexts or not relevant:
        return EMPTY_RESULT_TEXT, {"contexts": [], "query": query, "count": 0}

    log.info("agent.tool.search", query=query, count=len(contexts))
    return format_contexts(contexts), {
        "contexts": contexts,
        "query": query,
        "count": len(contexts),
    }


async def _ensure_catalog():
    """目录为空时懒加载（启动钩子未执行、脚本/测试场景）"""
    catalog = get_catalog()
    if catalog.size() == 0:
        try:
            await refresh_catalog()
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.catalog.load_failed", error=str(exc))
    return catalog


async def _get_product_spec_impl(product: str, fields: list[str] | None = None) -> ToolResult:
    """get_product_spec 的实际实现"""
    product = (product or "").strip()
    if not product:
        return "请提供商品名称或商品 ID。", {"contexts": [], "error": "empty_product"}

    catalog = await _ensure_catalog()
    record, candidates = catalog.resolve(product)
    if record is None:
        names = "、".join(c.name for c in candidates[:5])
        message = f"未找到商品「{product}」。"
        if names:
            message += f" 你可能想问：{names}。"
        return message, {
            "contexts": [],
            "error": "product_not_found",
            "candidates": [c.name for c in candidates],
        }

    selected = match_fields(record.fields, fields)
    if not selected:
        selected = dict(record.fields)

    lines = [f"商品：{record.name}（{record.product_id}）"]
    lines.extend(f"{key}: {value}" for key, value in selected.items())
    text = "\n".join(lines)
    log.info("agent.tool.product_spec", product=record.name, fields=list(selected))
    return text, {
        "contexts": [record.to_context("get_product_spec")],
        "product": record.name,
        "product_id": record.product_id,
        "fields": selected,
    }


async def _compare_products_impl(
    products: list[str], dimensions: list[str] | None = None
) -> ToolResult:
    """compare_products 的实际实现"""
    names = [p.strip() for p in (products or []) if p and p.strip()]
    if len(names) < 2:
        return "请提供至少 2 个商品名称进行对比。", {"contexts": [], "error": "need_two_products"}
    if len(names) > 4:
        names = names[:4]

    catalog = await _ensure_catalog()
    records = []
    missing: list[str] = []
    for name in names:
        record, _ = catalog.resolve(name)
        if record is None:
            missing.append(name)
        elif record not in records:
            records.append(record)

    if not records:
        return "未找到要对比的商品，请确认商品名称。", {
            "contexts": [],
            "error": "no_product_found",
            "missing": missing,
        }

    if dimensions:
        dims: list[str] = []
        for dim in dimensions:
            dims.extend(match_fields(records[0].fields, [dim]).keys())
        dims = list(dict.fromkeys(dims))
    else:
        dims = []
        for record in records:
            for key in record.fields:
                if key in ("商品ID", "名称") or key in dims:
                    continue
                dims.append(key)

    header = "| 字段 | " + " | ".join(r.name for r in records) + " |"
    separator = "|" + "---|" * (len(records) + 1)
    rows = [f"| {dim} | " + " | ".join(r.fields.get(dim, "—") for r in records) + " |" for dim in dims]
    table = "\n".join([header, separator, *rows])
    note = f"\n\n未找到商品：{'、'.join(missing)}" if missing else ""

    log.info("agent.tool.compare", products=[r.name for r in records], dimensions=len(dims))
    return f"商品对比（{len(records)} 款）：\n\n{table}{note}", {
        "contexts": [r.to_context("compare_products") for r in records],
        "products": [r.name for r in records],
        "missing": missing,
        "dimensions": dims,
    }


async def _check_order_status_impl(order_id: str) -> ToolResult:
    """check_order_status 的实际实现"""
    oid = (order_id or "").strip()
    if not is_valid_order_id(oid):
        return "订单号格式不正确，请提供形如 ORD-20261101-0001 的订单号。", {
            "contexts": [],
            "error": "invalid_order_id",
        }
    order = find_order(oid)
    if order is None:
        return f"未找到订单 {oid}，请确认订单号是否正确。", {
            "contexts": [],
            "error": "order_not_found",
        }
    text = format_order(order)
    context = synthetic_context(text, "订单系统（演示数据）", "check_order_status", oid, chunk_type="order")
    log.info("agent.tool.order", order_id=oid, status=order.get("status"))
    return text, {
        "contexts": [context],
        "order_id": oid,
        "status": order.get("status"),
    }


async def _get_after_sales_policy_impl(topic: str) -> ToolResult:
    """get_after_sales_policy 的实际实现：优先 FAQ 分类，未命中再放宽"""
    topic = (topic or "").strip()
    if not topic:
        return "请说明想了解哪方面的售后政策（退货、保修、换货、发票等）。", {
            "contexts": [],
            "error": "empty_topic",
        }
    try:
        contexts, relevant = await _search_contexts(topic, 5, {"faq"})
        note = ""
        if not contexts:
            contexts, relevant = await _search_contexts(topic, 5, None)
            note = "\n\n（未命中 FAQ 分类，以下为知识库相关片段）"
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.tool.after_sales_failed", error=str(exc))
        return f"售后政策查询失败：{str(exc)[:200]}", {"contexts": [], "error": str(exc)[:200]}

    contexts = _dedupe(contexts)[:5]
    if not contexts or not relevant:
        return EMPTY_RESULT_TEXT, {"contexts": [], "topic": topic}

    for c in contexts:
        c["source_tool"] = "get_after_sales_policy"
    return format_contexts(contexts) + note, {
        "contexts": contexts,
        "topic": topic,
        "count": len(contexts),
    }


async def _escalate_to_human_impl(
    reason: str, summary: str, config: dict[str, Any] | None = None
) -> ToolResult:
    """escalate_to_human 的实际实现"""
    settings = get_settings()
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    record = await create_handoff(
        reason=reason,
        summary=summary,
        session_id=configurable.get("session_id"),
        user_id=configurable.get("user_id"),
        persist=settings.agent_allow_write_tools,
    )
    text = f"已为你创建转人工工单：{record['ticket_id']}，客服将在 24 小时内联系你。"
    if not record["persisted"]:
        text += "\n（演示模式：工单未写入数据库）"
    context = synthetic_context(text, "转人工工单", "escalate_to_human", record["ticket_id"])
    return text, {"contexts": [context], "ticket": record}


# ---------------- LangChain Tool 包装 ----------------

@tool("search_knowledge_base", response_format="content_and_artifact")
async def search_knowledge_base(query: str, top_k: int = 5) -> ToolResult:
    """检索电商知识库（商品详情、卖点、材质、使用说明、售后政策等非结构化知识）。

    当问题无法用结构化参数字段直接回答，或需要引用原文时使用。
    返回带 [n] 编号的资料片段，编号可在最终回答中引用。

    Search the e-commerce knowledge base for unstructured product knowledge,
    policies and FAQ content. Returns numbered snippets for citation.
    """
    return await _search_knowledge_base_impl(query, top_k)


@tool("get_product_spec", response_format="content_and_artifact")
async def get_product_spec(product: str, fields: list[str] | None = None) -> ToolResult:
    """查询单个商品的结构化参数（价格、重量、电池、屏幕、颜色等）。

    当问题只涉及一个商品的具体字段时优先使用，比向量检索更准更快。
    product 可以是商品名称或商品 ID（如 P001）。
    fields 可选，用于只返回关心的字段；为空则返回全部参数。

    Look up structured specs of a single product by name or product ID.
    """
    return await _get_product_spec_impl(product, fields)


@tool("compare_products", response_format="content_and_artifact")
async def compare_products(
    products: list[str], dimensions: list[str] | None = None
) -> ToolResult:
    """对比 2~4 个商品的参数（价格、重量、电池、屏幕等），输出 Markdown 对比表。

    当用户询问「A 和 B 哪个更好/有什么区别/怎么选」时使用。
    dimensions 可选，指定只对比哪些维度。

    Compare specs of 2-4 products and return a markdown table.
    """
    return await _compare_products_impl(products, dimensions)


@tool("check_order_status", response_format="content_and_artifact")
async def check_order_status(order_id: str) -> ToolResult:
    """查询订单状态与物流信息（演示数据，只读）。

    仅当用户提供了订单号（形如 ORD-20261101-0001）时使用。
    不要猜测订单号，也不要查询他人订单。

    Check order status and logistics by order ID (demo data, read-only).
    """
    return await _check_order_status_impl(order_id)


@tool("get_after_sales_policy", response_format="content_and_artifact")
async def get_after_sales_policy(topic: str) -> ToolResult:
    """查询售后政策（退货、退款、保修、换货、发票、运费等 FAQ）。

    当问题涉及售后规则而不是具体商品参数时使用。

    Look up after-sales policy and FAQ content.
    """
    return await _get_after_sales_policy_impl(topic)


@tool("escalate_to_human", response_format="content_and_artifact")
async def escalate_to_human(reason: str, summary: str, config: RunnableConfig) -> ToolResult:
    """转人工客服。仅当知识库与所有工具都无法解决、或用户明确要求人工时使用。

    reason 为简短原因，summary 为给人工客服的问题摘要。

    Escalate the conversation to a human agent when self-service fails.
    """
    return await _escalate_to_human_impl(reason, summary, config)


ALL_TOOLS = [
    search_knowledge_base,
    get_product_spec,
    compare_products,
    check_order_status,
    get_after_sales_policy,
    escalate_to_human,
]