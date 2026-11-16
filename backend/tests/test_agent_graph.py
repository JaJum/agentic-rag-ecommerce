"""LangGraph 状态机单测：路由、步数上限、端到端事件流（假 LLM）。"""
import pytest
from app.services.agent import graph as graph_mod
from app.services.agent.catalog import get_catalog, reset_catalog
from app.services.agent.graph import (
    classify_route,
    filter_duplicate_calls,
    get_graph,
    route_after_agent,
)
from app.services.agent.runner import run_agent_stream
from langchain_core.messages import AIMessage, AIMessageChunk

PRODUCTS = [
    {
        "chunk_id": "c1",
        "doc_id": "d1",
        "doc_name": "商品参数表.csv",
        "text": "商品ID: P001\n名称: 星河 X5 智能手机\n价格: 3999\n电池容量: 5000mAh\n重量: 198g",
        "meta": {"product_id": "P001"},
    },
    {
        "chunk_id": "c2",
        "doc_id": "d1",
        "doc_name": "商品参数表.csv",
        "text": "商品ID: P002\n名称: 星河 X5 Pro 智能手机\n价格: 5299\n电池容量: 5500mAh\n重量: 205g",
        "meta": {"product_id": "P002"},
    },
]


class FakeAgentLLM:
    """第一次返回工具调用，第二次返回结束信号"""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "compare_products",
                        "args": {"products": ["星河 X5", "星河 X5 Pro"]},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="已获取对比数据。")


class FakeStreamLLM:
    async def astream(self, messages):
        for piece in ["星河 X5 价格 3999 元 [1]，", "X5 Pro 价格 5299 元 [2]。"]:
            yield AIMessageChunk(content=piece)


@pytest.fixture(autouse=True)
def _fresh_catalog():
    reset_catalog()
    get_catalog().rebuild(PRODUCTS)
    yield
    reset_catalog()


def test_classify_route():
    assert classify_route("你好") == "chitchat"
    assert classify_route("星河 X5 多少钱") == "kb_simple"
    assert classify_route("对比星河 X5 和 X5 Pro") == "multi_hop"
    assert classify_route("星河 X6 和 X6 Pro 哪个电池更大") == "multi_hop"
    assert classify_route("风语者 Air 和 Air Pro 差价多少") == "multi_hop"
    assert classify_route("星河平板 T10 和 T11 哪个更值得买") == "multi_hop"
    assert classify_route("X5 Pro 比 X5 贵多少") == "multi_hop"
    assert classify_route("这款性价比高吗") == "kb_simple"
    assert classify_route("订单 ORD-20260905-0001 到哪了") == "business"
    assert classify_route("商品支持7天无理由退货吗") == "business"
    assert classify_route("保修期是多久") == "business"
    assert classify_route("今天天气怎么样") == "chitchat"


def test_route_after_agent_stops_at_max_steps():
    state = {
        "messages": [AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1", "type": "tool_call"}])],
        "steps": 3,
    }
    assert route_after_agent(state) == "finalize"
    state["steps"] = 1
    assert route_after_agent(state) == "tools"


def test_graph_has_expected_nodes():
    graph = get_graph()
    nodes = set(graph.get_graph().nodes)
    assert {"route", "agent", "tools", "collect", "finalize", "verify"} <= nodes


@pytest.mark.asyncio
async def test_multi_hop_stream_runs_tools_and_citations(monkeypatch):
    agent_llm = FakeAgentLLM()

    def fake_get_llm(model=None, streaming=True, temperature=None):
        return FakeStreamLLM() if streaming else agent_llm

    monkeypatch.setattr(graph_mod, "get_llm", fake_get_llm)

    events = [ev async for ev in run_agent_stream("对比星河 X5 和 X5 Pro")]

    names = [ev["event"] for ev in events]
    assert "step" in names
    assert "tool_call" in names
    assert "tool_result" in names
    assert "token" in names
    assert names[-1] == "done"

    done = events[-1]["data"]
    assert done["route"] == "multi_hop"
    assert done["steps"] == 1
    assert len(done["contexts"]) == 2
    assert "[1]" in done["answer"]
    assert done["cited"] == [1, 2]
    assert done["status"] == "ok"
class RepeatingAgentLLM:
    """每轮都返回同一个工具调用，用于验证重复调用过滤"""

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "compare_products",
                    "args": {"products": ["星河 X5", "星河 X5 Pro"]},
                    "id": "call_repeat",
                    "type": "tool_call",
                }
            ],
        )


class AlternatingAgentLLM:
    """每轮参数不同，用于验证最大步数熔断"""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        products = (
            ["星河 X5", "星河 X5 Pro"]
            if self.calls % 2
            else ["星河 X5 Pro", "星河 X5"]
        )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "compare_products",
                    "args": {"products": products},
                    "id": f"call_{self.calls}",
                    "type": "tool_call",
                }
            ],
        )


def test_filter_duplicate_calls_unit():
    calls = [
        {"name": "search_knowledge_base", "args": {"query": "电池"}, "id": "1"},
        {"name": "search_knowledge_base", "args": {"query": "电池"}, "id": "2"},
        {"name": "search_knowledge_base", "args": {"query": "价格"}, "id": "3"},
    ]
    kept, fingerprints = filter_duplicate_calls(calls, [])
    assert [c["id"] for c in kept] == ["1", "3"]
    assert len(fingerprints) == 2

    kept_again, fingerprints_again = filter_duplicate_calls(calls, fingerprints)
    assert kept_again == []
    assert len(fingerprints_again) == 2


@pytest.mark.asyncio
async def test_graph_filters_duplicate_tool_calls(monkeypatch):
    def fake_get_llm(model=None, streaming=True, temperature=None):
        return FakeStreamLLM() if streaming else RepeatingAgentLLM()

    monkeypatch.setattr(graph_mod, "get_llm", fake_get_llm)

    events = [ev async for ev in run_agent_stream("对比星河 X5 和 X5 Pro")]
    done = events[-1]["data"]

    tool_calls = [ev for ev in events if ev["event"] == "tool_call"]
    assert len(tool_calls) == 1
    assert done["steps"] == 1
    assert done["status"] == "ok"


@pytest.mark.asyncio
async def test_graph_stops_at_max_steps(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_max_steps", 2)
    llm = AlternatingAgentLLM()

    def fake_get_llm(model=None, streaming=True, temperature=None):
        return FakeStreamLLM() if streaming else llm

    monkeypatch.setattr(graph_mod, "get_llm", fake_get_llm)

    events = [ev async for ev in run_agent_stream("对比星河 X5 和 X5 Pro")]
    done = events[-1]["data"]

    assert done["steps"] == 2
    assert llm.calls == 3  # 第 3 次决策被步数上限截断，不再执行工具
    assert len([ev for ev in events if ev["event"] == "tool_call"]) == 2
    assert done["status"] == "ok"


@pytest.mark.asyncio
async def test_finalize_clarifies_when_tool_returns_validation_message():
    from app.services.agent.graph import finalize_node

    state = {
        "query": "我的订单到哪了",
        "rewritten": "我的订单到哪了",
        "contexts": [],
        "tool_events": [{
            "step_no": 1,
            "tool": "check_order_status",
            "ok": False,
            "summary": "订单号格式不正确，请提供形如 ORD-20260905-0001 的订单号。",
        }],
        "steps": 1,
        "usage": {},
    }
    result = await finalize_node(state, {})
    assert result["status"] == "ok"
    assert "订单号" in result["answer"]
