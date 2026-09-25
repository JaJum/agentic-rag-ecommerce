"""Agent 主链路集成测试（A-21）：快速路径、闲聊、库外拒答、整体超时。"""
import asyncio

import pytest
from app.core.config import get_settings
from app.services.agent import graph as graph_mod
from app.services.agent import runner as runner_mod
from app.services.agent.runner import run_agent_stream
from app.services.rag.generation import FALLBACK_TEXT
from langchain_core.messages import AIMessageChunk

CONTEXT = {
    "chunk_id": "c1",
    "doc_id": "d1",
    "doc_name": "商品参数表.csv",
    "chunk_type": "param",
    "text": "商品ID: P001\n名称: 星河 X5 智能手机\n价格: 3999\n电池容量: 5000mAh",
    "meta": {"product_id": "P001"},
}


class FakeStreamLLM:
    def __init__(self, text):
        self.text = text

    async def astream(self, messages):
        yield AIMessageChunk(content=self.text)


def _patch_rewrite(monkeypatch, text="星河 X5 电池容量"):
    async def fake_rewrite(query, history=None):
        return text

    monkeypatch.setattr(graph_mod, "rewrite_query", fake_rewrite)


@pytest.mark.asyncio
async def test_fast_path_single_hop_returns_cited_answer(monkeypatch):
    async def fake_search(query, k, chunk_types=None):
        return [CONTEXT], True

    monkeypatch.setattr(graph_mod, "_search_contexts", fake_search)
    _patch_rewrite(monkeypatch)
    monkeypatch.setattr(
        graph_mod, "get_llm",
        lambda model=None, streaming=True, temperature=None: FakeStreamLLM("电池容量为 5000mAh [1]。"),
    )

    events = [ev async for ev in run_agent_stream("星河 X5 多少钱")]
    done = events[-1]["data"]

    assert done["route"] == "kb_simple"
    assert done["steps"] == 0
    assert len(done["contexts"]) == 1
    assert done["cited"] == [1]
    assert done["status"] == "ok"
    assert not [ev for ev in events if ev["event"] == "tool_call"]


@pytest.mark.asyncio
async def test_chitchat_skips_retrieval(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("chitchat 不应触发检索")

    monkeypatch.setattr(graph_mod, "_search_contexts", boom)
    _patch_rewrite(monkeypatch, "你好")
    monkeypatch.setattr(
        graph_mod, "get_llm",
        lambda model=None, streaming=True, temperature=None: FakeStreamLLM("你好，我是电商智能客服。"),
    )

    events = [ev async for ev in run_agent_stream("你好")]
    done = events[-1]["data"]

    assert done["route"] == "chitchat"
    assert done["contexts"] == []
    assert done["answer"].startswith("你好")
    assert [ev["event"] for ev in events].count("token") == 1


@pytest.mark.asyncio
async def test_out_of_library_refuses_with_fallback(monkeypatch):
    async def empty_search(query, k, chunk_types=None):
        return [], False

    monkeypatch.setattr(graph_mod, "_search_contexts", empty_search)
    _patch_rewrite(monkeypatch)

    events = [ev async for ev in run_agent_stream("折叠屏手机的屏幕寿命是多少")]
    names = [ev["event"] for ev in events]
    done = events[-1]["data"]

    assert "fallback" in names
    assert done["status"] == "fallback"
    assert done["answer"] == FALLBACK_TEXT
    assert done["contexts"] == []
    assert "token" not in names


class HangingGraph:
    async def astream(self, state, config, stream_mode=None):
        await asyncio.sleep(1)
        if False:  # pragma: no cover —— 保持 async generator 语义
            yield None


@pytest.mark.asyncio
async def test_agent_timeout_emits_error_and_timeout_status(monkeypatch):
    monkeypatch.setattr(runner_mod, "get_graph", lambda: HangingGraph())
    monkeypatch.setattr(get_settings(), "agent_timeout_s", 1)

    events = [ev async for ev in run_agent_stream("对比星河 X5 和 X5 Pro")]
    names = [ev["event"] for ev in events]
    done = events[-1]["data"]

    assert "error" in names
    error = next(ev for ev in events if ev["event"] == "error")
    assert error["data"]["code"] == "AGENT_TIMEOUT"
    assert done["status"] == "timeout"
    assert done["answer"] == ""
