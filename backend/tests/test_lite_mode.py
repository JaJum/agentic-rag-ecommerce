"""Lite 模式测试：SQLite 类型适配、BM25 单路检索、Mock LLM。"""
import pytest
from app.db.compat import BigInt, LongText, Ts6
from app.services import llm as llm_mod
from app.services.bm25_index import Bm25Index
from app.services.llm import MockChatModel
from app.services.rag import retrieval as retrieval_mod
from langchain_core.messages import HumanMessage, ToolMessage

CATALOG = [
    ("c1", "商品ID: P001\n名称: 星河 X5 智能手机\n电池容量: 5000mAh", {"doc_name": "商品参数表.csv", "chunk_type": "param"}),
    ("c2", "Q：商品支持无理由退货吗？\nA：支持，自签收之日起 7 天内可申请。", {"doc_name": "售后FAQ.md", "chunk_type": "faq"}),
    ("c3", "商品ID: P016\n名称: 风语者 Air Pro\n续航时间: 30小时", {"doc_name": "商品参数表.csv", "chunk_type": "param"}),
]


def test_compat_types_render_on_sqlite():
    """SQLite 方言下：主键降级为 INTEGER、时间戳/长文本降级为标准类型"""
    assert BigInt.dialect_impl(_dialect("sqlite")).__class__.__name__.lower() == "integer"
    assert Ts6.dialect_impl(_dialect("sqlite")).__class__.__name__.lower() == "datetime"
    assert LongText.dialect_impl(_dialect("sqlite")).__class__.__name__.lower() == "text"


def _dialect(name: str):
    from sqlalchemy.dialects import mysql, sqlite

    return sqlite.dialect() if name == "sqlite" else mysql.dialect()


def test_bm25_index_keeps_text_and_meta():
    """Lite 单路检索依赖索引内保存的原文与元数据"""
    idx = Bm25Index()
    idx.rebuild(CATALOG)
    doc = idx.get_doc("c1")
    assert doc is not None
    text, meta = doc
    assert "星河 X5" in text
    assert meta["doc_name"] == "商品参数表.csv"


def test_bm25_search_filters_out_of_catalog_product(monkeypatch):
    """库外商品（小米14）不应被同属性块误召回"""
    idx = Bm25Index()
    idx.rebuild(CATALOG)
    monkeypatch.setattr(retrieval_mod, "bm25_index", idx)

    assert retrieval_mod._bm25_search("小米14 的电池容量是多少？", k=5) == []
    hits = retrieval_mod._bm25_search("星河 X5 的电池容量", k=5)
    assert hits and hits[0]["chunk_id"] == "c1"


@pytest.mark.asyncio
async def test_mock_llm_one_tool_call_then_citation():
    """Mock LLM：首轮产出工具调用，拿到工具结果后给出带 [1] 的回答"""
    model = MockChatModel().bind_tools([object()])
    question = HumanMessage(content="ORD-20261101-0001 的物流到哪了？")

    first = await model.ainvoke([question])
    assert first.tool_calls and first.tool_calls[0]["name"] == "check_order_status"

    second = await model.ainvoke([
        question,
        first,
        ToolMessage(content="订单状态：已签收", tool_call_id=first.tool_calls[0]["id"]),
    ])
    assert "[1]" in second.content


@pytest.mark.asyncio
async def test_mock_llm_rewrite_returns_original_question():
    """查询改写：Mock 原样返回「最新问题」，保证多轮演示可复现"""
    prompt = "对话历史：\nuser: 星河 X5 多少钱\n最新问题：它的续航多久\n检索式："
    result = await MockChatModel().ainvoke(prompt)
    assert result.content == "它的续航多久"


@pytest.mark.asyncio
async def test_mock_llm_streams_in_chunks():
    """流式接口可用：分片输出且拼接后内容一致"""
    model = MockChatModel()
    pieces = [chunk.content async for chunk in model.astream([HumanMessage(content="你好")])]
    assert len(pieces) >= 1
    assert "".join(pieces) == "我是电商知识库智能客服（Lite 演示模式）。"


def test_mock_flag_switches_get_llm(monkeypatch):
    """MOCK_LLM=true 时 get_llm 返回 MockChatModel 而不是 ChatOpenAI"""
    monkeypatch.setattr(llm_mod.get_settings(), "mock_llm", True)
    assert isinstance(llm_mod.get_llm(), MockChatModel)