"""智能兜底测试：业务问题拒答 / 闲聊通用回答的分类与消息组装"""
from app.services.rag.fallback import (
    GENERAL_SYSTEM_PROMPT,
    is_business_query,
    make_general_messages,
)
from app.services.rag.generation import FALLBACK_TEXT
from langchain_core.messages import HumanMessage, SystemMessage

# 业务域问题（商品/参数/价格/售后/品牌）→ 必须拒答，防止编造
BUSINESS_QUERIES = [
    "星河 X5 的电池容量是多少",
    "商品支持无理由退货吗",
    "小米14好不好",
    "保修期是多久",
    "这款笔记本重量多少",
    "退货的运费由谁承担",
    "如何申请售后",
    "快充充电器 65W 多少钱",
    "pro65w充电头价格",  # 大小写混合的品牌/品类词
]

# 闲聊/通用问题 → 走通用大模型回答
GENERAL_QUERIES = [
    "你是什么大模型",
    "你好",
    "今天天气怎么样",
    "帮我写一首诗",
    "讲个笑话",
    "你会做什么",
    "谢谢",
]


def test_business_query_detected():
    for q in BUSINESS_QUERIES:
        assert is_business_query(q), f"业务问题被漏判为闲聊：{q}"


def test_general_query_not_blocked():
    for q in GENERAL_QUERIES:
        assert not is_business_query(q), f"闲聊被误判为业务问题：{q}"


def test_empty_query_is_general():
    assert not is_business_query("")
    assert not is_business_query(None)


def test_general_messages_structure():
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
    ]
    msgs = make_general_messages("你是什么大模型", history)
    assert isinstance(msgs[0], SystemMessage)
    assert FALLBACK_TEXT in GENERAL_SYSTEM_PROMPT  # 涉商业务仍守"不编造"红线
    assert isinstance(msgs[-1], HumanMessage)
    assert msgs[-1].content == "你是什么大模型"
    assert len(msgs) == 4  # system + 2 历史 + 当前问题


def test_general_messages_without_history():
    msgs = make_general_messages("你好", None)
    assert len(msgs) == 2
