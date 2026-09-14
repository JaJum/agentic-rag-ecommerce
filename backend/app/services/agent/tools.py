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

from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.bm25_index import bm25_index
from app.services.rag.retrieval import hybrid_search, is_relevant, rerank_top

log = get_logger(__name__)

EMPTY_RESULT_TEXT = "知识库中未检索到相关内容。"

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


async def _search_hybrid(query: str, k: int) -> tuple[list[dict[str, Any]], bool]:
    """混合检索 + rerank；rerank 不可用时退回 RRF 排序（保证 Lite 模式可用）"""
    candidates = await asyncio.to_thread(hybrid_search, query)
    if not candidates:
        return [], False
    try:
        ranked = await asyncio.to_thread(rerank_top, query, candidates)
        relevant = is_relevant(ranked)
        return [make_context(c, "search_knowledge_base") for c in ranked[:k]], relevant
    except Exception as exc:  # noqa: BLE001 —— 模型不可用时降级，不阻塞问答
        log.warning("agent.tool.rerank_failed", error=str(exc))
        return [make_context(c, "search_knowledge_base") for c in candidates[:k]], True


async def _search_bm25(query: str, k: int) -> list[dict[str, Any]]:
    """BM25 单路检索（RETRIEVAL_MODE=bm25 / 无 embedding 时使用）"""
    hits = bm25_index.search(query, k=k)
    if not hits:
        return []
    rows = await _fetch_chunks([cid for cid, _ in hits])
    score_map = dict(hits)
    ordered: list[dict[str, Any]] = []
    for cid, _ in hits:
        row = rows.get(cid)
        if not row:
            continue
        ordered.append(
            make_context({**row, "bm25_score": score_map.get(cid, 0.0)}, "search_knowledge_base")
        )
    return ordered


async def _search_knowledge_base_impl(query: str, top_k: int = 5) -> ToolResult:
    """search_knowledge_base 的实际实现（便于单测直接调用）"""
    settings = get_settings()
    query = (query or "").strip()
    if not query:
        return EMPTY_RESULT_TEXT, {"contexts": [], "error": "empty_query", "query": query}

    k = max(1, min(int(top_k or 5), 8))
    try:
        if settings.retrieval_mode == "bm25" or settings.embedding_provider == "none":
            contexts = await _search_bm25(query, k)
            relevant = bool(contexts)
        else:
            contexts, relevant = await _search_hybrid(query, k)
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


@tool("search_knowledge_base", response_format="content_and_artifact")
async def search_knowledge_base(query: str, top_k: int = 5) -> ToolResult:
    """检索电商知识库（商品详情、卖点、材质、使用说明、售后政策等非结构化知识）。

    当问题无法用结构化参数字段直接回答，或需要引用原文时使用。
    返回带 [n] 编号的资料片段，编号可在最终回答中引用。

    Search the e-commerce knowledge base for unstructured product knowledge,
    policies and FAQ content. Returns numbered snippets for citation.
    """
    return await _search_knowledge_base_impl(query, top_k)


# 后续工具（get_product_spec / compare_products / check_order_status /
# get_after_sales_policy / escalate_to_human）在 A-05 ~ A-10 加入此列表。
ALL_TOOLS = [search_knowledge_base]