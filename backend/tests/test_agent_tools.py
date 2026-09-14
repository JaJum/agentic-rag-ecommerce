"""Agent 基座单测：脱敏、预览、上下文规范化、检索工具契约。"""
import pytest

from app.services.agent import tools as agent_tools
from app.services.agent.state import initial_state
from app.services.agent.trace import mask_sensitive, preview
from app.services.agent.tools import (
    EMPTY_RESULT_TEXT,
    _search_knowledge_base_impl,
    format_contexts,
    make_context,
)


def test_mask_sensitive_phone_email_order():
    text = "联系 13812345678 / user@example.com，订单 ORD-20261110-0001"
    masked = mask_sensitive(text)
    assert "138****5678" in masked
    assert "use***@example.com" in masked
    assert "ORD-20261110-****01" in masked
    assert "13812345678" not in masked


def test_preview_truncates_and_flattens():
    out = preview({"a": "x" * 500}, limit=40)
    assert len(out) <= 40
    assert out.endswith("…")
    assert "\n" not in out


def test_format_contexts_uses_stable_numbering():
    contexts = [
        make_context(
            {"chunk_id": "c1", "text": "电池 5000mAh", "meta": {"doc_name": "参数表.csv", "product_id": "P001"}},
            "search_knowledge_base",
        ),
        make_context(
            {"chunk_id": "c2", "text": "支持 100W 快充", "meta": {"doc_name": "详情.md", "section": "充电"}},
            "search_knowledge_base",
        ),
    ]
    text = format_contexts(contexts)
    assert text.startswith("[1] 来源：参数表.csv（P001）")
    assert "[2] 来源：详情.md（充电）" in text


def test_make_context_prefers_rerank_score():
    ctx = make_context(
        {"chunk_id": "c1", "text": "x", "rerank_score": 0.8, "rrf_score": 0.02},
        "search_knowledge_base",
    )
    assert ctx["score"] == 0.8
    assert ctx["source_tool"] == "search_knowledge_base"


def test_initial_state_defaults():
    state = initial_state("多少钱")
    assert state["query"] == "多少钱"
    assert state["route"] == "kb_simple"
    assert state["contexts"] == []


@pytest.mark.asyncio
async def test_search_tool_rejects_empty_query():
    content, artifact = await _search_knowledge_base_impl("   ")
    assert content == EMPTY_RESULT_TEXT
    assert artifact["error"] == "empty_query"


@pytest.mark.asyncio
async def test_search_tool_passes_through_numbered_contexts(monkeypatch):
    ctx = make_context(
        {"chunk_id": "c1", "text": "星河 X5 电池容量 5000mAh", "meta": {"doc_name": "参数表.csv", "product_id": "P001"}},
        "search_knowledge_base",
    )

    async def fake_hybrid(query: str, k: int):
        assert query == "星河 X5 电池"
        return [ctx], True

    monkeypatch.setattr(agent_tools, "_search_hybrid", fake_hybrid)
    content, artifact = await _search_knowledge_base_impl("星河 X5 电池", 3)
    assert content.startswith("[1] 来源：参数表.csv")
    assert artifact["count"] == 1
    assert artifact["contexts"][0]["chunk_id"] == "c1"


@pytest.mark.asyncio
async def test_search_tool_returns_empty_when_not_relevant(monkeypatch):
    async def fake_hybrid(query: str, k: int):
        return [], False

    monkeypatch.setattr(agent_tools, "_search_hybrid", fake_hybrid)
    content, artifact = await _search_knowledge_base_impl("今天天气", 3)
    assert content == EMPTY_RESULT_TEXT
    assert artifact["count"] == 0