"""chat.py Agent 分支接线测试（A-21）：开关关停回归、失败降级、成功持久化。"""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessageChunk

from app.api.v1 import chat as chat_mod
from app.schemas.chat import ChatStreamRequest

TOP = [
    {
        "chunk_id": "c1",
        "doc_id": "d1",
        "doc_name": "商品参数表.csv",
        "chunk_type": "param",
        "text": "商品ID: P001\n名称: 星河 X5 智能手机\n价格: 3999\n电池容量: 5000mAh",
        "meta": {"product_id": "P001", "doc_name": "商品参数表.csv"},
        "rerank_score": 0.92,
    }
]


class FakeStreamLLM:
    async def astream(self, messages):
        yield AIMessageChunk(content="星河 X5 售价 3999 元 [1]。")


class FakeCache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value


class FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def harness(monkeypatch):
    """装配 chat_stream 所需的全部外部依赖，返回事件收集器"""
    state = {"agent_enabled": False, "qa_logs": [], "messages": [], "agent_runs": [], "cache_sets": []}
    cache = FakeCache()

    async def fake_session(*args, **kwargs):
        return SimpleNamespace(id="s1", title="新会话")

    async def fake_messages(*args, **kwargs):
        return []

    async def fake_touch(*args, **kwargs):
        return None

    monkeypatch.setattr(chat_mod.session_service, "get_user_session", fake_session)
    monkeypatch.setattr(chat_mod.session_service, "create_session", fake_session)
    monkeypatch.setattr(chat_mod.session_service, "list_messages", fake_messages)
    monkeypatch.setattr(chat_mod.session_service, "touch_session", fake_touch)

    monkeypatch.setattr(chat_mod, "check_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(chat_mod, "clean_input", lambda q: q)
    monkeypatch.setattr(chat_mod, "check_sensitive", lambda q: None)
    monkeypatch.setattr(chat_mod, "get_cache", lambda: cache)
    monkeypatch.setattr(
        chat_mod, "get_settings",
        lambda: SimpleNamespace(agent_enabled=state["agent_enabled"]),
    )

    async def fake_rewrite(query, history=None):
        return query

    monkeypatch.setattr(chat_mod, "rewrite_query", fake_rewrite)
    monkeypatch.setattr(chat_mod, "hybrid_search", lambda q: list(TOP))
    monkeypatch.setattr(chat_mod, "rerank_top", lambda q, c: list(c))
    monkeypatch.setattr(chat_mod, "is_relevant", lambda top: bool(top))
    monkeypatch.setattr(chat_mod, "get_llm", lambda *a, **k: FakeStreamLLM())

    async def fake_persist_message(*args, **kwargs):
        state["messages"].append((args, kwargs))

    async def fake_persist_citations(*args, **kwargs):
        return None

    async def fake_persist_qa_log(*args, **kwargs):
        state["qa_logs"].append(kwargs)

    async def fake_persist_agent_run(**kwargs):
        state["agent_runs"].append(kwargs)

    monkeypatch.setattr(chat_mod, "_persist_message", fake_persist_message)
    monkeypatch.setattr(chat_mod, "_persist_citations", fake_persist_citations)
    monkeypatch.setattr(chat_mod, "_persist_qa_log", fake_persist_qa_log)
    monkeypatch.setattr(chat_mod, "_persist_agent_run", fake_persist_agent_run)

    real_set = cache.set

    def recording_set(key, value, ttl=None):
        state["cache_sets"].append(value)
        real_set(key, value, ttl)

    cache.set = recording_set

    async def run(query="星河 X5 多少钱"):
        body = ChatStreamRequest(query=query)
        user = SimpleNamespace(id=1)
        resp = await chat_mod.chat_stream(body, user=user, db=FakeDB())
        events = []
        async for raw in resp.body_iterator:
            if isinstance(raw, dict):
                payload = raw.get("data") or "{}"
                events.append({
                    "event": raw.get("event"),
                    "data": json.loads(payload) if isinstance(payload, str) else payload,
                })
            else:
                payload = getattr(raw, "data", None)
                events.append({
                    "event": getattr(raw, "event", None),
                    "data": json.loads(payload) if isinstance(payload, str) else (payload or {}),
                })
        return events

    state["run"] = run
    return state


def _done(events):
    return next(ev["data"] for ev in events if ev["event"] == "done")


@pytest.mark.asyncio
async def test_agent_disabled_uses_legacy_rag(harness, monkeypatch):
    called = {"agent": False}

    async def should_not_run(*args, **kwargs):
        called["agent"] = True
        yield {"event": "done", "data": {}}

    monkeypatch.setattr(chat_mod, "run_agent_stream", should_not_run)

    events = await harness["run"]()
    names = [ev["event"] for ev in events]

    assert called["agent"] is False
    assert "citation" in names
    assert _done(events)["hit"] is True
    assert harness["qa_logs"][-1]["route"] == "rag"
    assert harness["cache_sets"][-1]["route"] == "rag"


@pytest.mark.asyncio
async def test_agent_failure_degrades_to_legacy_rag(harness, monkeypatch):
    harness["agent_enabled"] = True

    async def failing_agent(*args, **kwargs):
        yield {"event": "error", "data": {"code": "AGENT_ERROR", "message": "boom"}}
        yield {"event": "done", "data": {
            "route": "multi_hop", "status": "error", "steps": 0,
            "contexts": [], "answer": "", "usage": {}, "error": "boom",
        }}

    monkeypatch.setattr(chat_mod, "run_agent_stream", failing_agent)

    events = await harness["run"]()
    done = _done(events)
    names = [ev["event"] for ev in events]

    assert "error" in names
    assert done["hit"] is True  # 降级后的 RAG 命中
    assert harness["agent_runs"][-1]["status"] == "error"
    assert harness["qa_logs"][-1]["route"] == "rag"


@pytest.mark.asyncio
async def test_agent_success_persists_run_and_route(harness, monkeypatch):
    harness["agent_enabled"] = True

    async def ok_agent(*args, **kwargs):
        yield {"event": "step", "data": {"step_no": 0, "node": "route", "status": "ok", "label": "路由：multi_hop"}}
        yield {"event": "tool_call", "data": {"step_no": 1, "tool": "compare_products", "args_preview": "星河 X5 vs X5 Pro"}}
        yield {"event": "tool_result", "data": {"step_no": 1, "tool": "compare_products", "ok": True, "summary": "对比表"}}
        yield {"event": "token", "data": {"delta": "X5 3999 元 [1]，X5 Pro 5299 元 [2]。"}}
        yield {"event": "done", "data": {
            "route": "multi_hop", "status": "ok", "steps": 1,
            "contexts": [
                {"chunk_id": "c1", "doc_name": "商品参数表.csv", "text": "星河 X5 3999", "score": 0.9, "meta": {}},
                {"chunk_id": "c2", "doc_name": "商品参数表.csv", "text": "星河 X5 Pro 5299", "score": 0.8, "meta": {}},
            ],
            "answer": "X5 3999 元 [1]，X5 Pro 5299 元 [2]。",
            "usage": {"total_tokens": 321}, "rewritten_query": "对比星河 X5 和 X5 Pro", "error": None,
        }}

    monkeypatch.setattr(chat_mod, "run_agent_stream", ok_agent)

    events = await harness["run"]("对比星河 X5 和 X5 Pro")
    done = _done(events)

    assert done["route"] == "multi_hop"
    assert done["steps"] == 1
    assert done["hit"] is True
    assert harness["qa_logs"][-1]["route"] == "multi_hop"
    assert harness["qa_logs"][-1]["tool_count"] == 1
    run = harness["agent_runs"][-1]
    assert run["status"] == "ok"
    assert run["token_usage"] == 321
    assert [t["node"] for t in run["trace"]] == ["route", "tool_call", "tool_result"]
    assert harness["cache_sets"][-1]["route"] == "multi_hop"
