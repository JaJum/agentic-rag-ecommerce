"""
LLM 工厂：阿里云百炼 qwen3.8-flash（OpenAI 兼容，AsyncChatOpenAI）。
- 多模型分工：查询改写用 llm_rewrite_model，回答生成用 llm_model（.env 可配）
- enable_thinking 经 extra_body 透传（默认关闭保首字延迟）
- MOCK_LLM=true 时返回确定性 MockChatModel：无 Key / CI / 离线演示可跑通全链路
"""
import asyncio
import re

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

_ORDER = re.compile(r"ORD-\d{8}-\d{4}", re.IGNORECASE)
_ORDER_HINT = re.compile(r"(订单|物流|快递|发货|签收|运单)")
_AFTERSALES = re.compile(r"(退货|退款|换货|保修|质保|售后|发票)")
_COMPARE = re.compile(r"(对比|比较|区别|差别|哪个|哪款|怎么选)")
_COMPARE_SPLIT = re.compile(r"(.+?)\s*(?:和|与|跟)\s*(.+?)(?:的|哪个|哪款|怎么|$)")


class MockChatModel:
    """
    确定性假模型。

    只模拟项目实际用到的三种行为，不追求通用性：
    1. 绑定工具后：首轮产出一个 tool_call，拿到 ToolMessage 后给出带 [1] 的最终回答
    2. 有 <资料> 的生成请求：固定引用 [1]
    3. 查询改写：原样返回「最新问题」，保证多轮 demo 可复现
    """

    def __init__(self, streaming: bool = True, tools: list | None = None):
        self.streaming = streaming
        self.tools = tools or []

    # --- 与 ChatOpenAI 保持一致的调用面 ---
    def bind_tools(self, tools, **kwargs):  # noqa: ARG002 - 兼容 LangChain 接口
        return MockChatModel(streaming=self.streaming, tools=list(tools))

    async def ainvoke(self, messages, config=None, **kwargs):  # noqa: ARG002
        return self._decide(messages)

    async def astream(self, messages, config=None, **kwargs):  # noqa: ARG002
        text = self._decide(messages).content
        for i in range(0, len(text), 8):
            await asyncio.sleep(0)
            yield AIMessageChunk(content=text[i:i + 8])

    # --- 内部决策 ---
    def _decide(self, messages) -> AIMessage:
        # rewrite.py 传入的是字符串 prompt，其余调用传入消息列表
        question = messages if isinstance(messages, str) else _last_human_text(messages)

        # 1) 查询改写：从模板里抽出原问题，避免 mock 改写出无关内容
        if "检索式：" in question:
            m = re.search(r"最新问题：(.+?)(?:\n检索式：|$)", question, re.S)
            return AIMessage(content=(m.group(1).strip() if m else question))

        # 2) 已拿到工具结果 → 收尾（有引用）
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        if tool_msgs:
            content = str(tool_msgs[-1].content or "").strip()
            if content.startswith(("请提供", "未找到", "商品不存在", "订单不存在")):
                return AIMessage(content=content)  # 澄清/校验信息直接转述
            snippet = content.replace("\n", " ")[:120]
            return AIMessage(content=f"根据知识库资料：{snippet} [1]")

        # 3) Agent 决策：首轮抛一个工具调用
        if self.tools:
            name, args = _pick_tool(question)
            return AIMessage(
                content="",
                tool_calls=[{"name": name, "args": args, "id": f"mock-call-{abs(hash(question)) % 10000}"}],
            )

        # 4) RAG 生成：摘取第一条资料并固定引用 [1]
        if "<资料>" in question:
            m = re.search(r"\[1\][^\n]*\n(.+)", question)
            snippet = m.group(1).strip().replace("\n", " ")[:80] if m else ""
            return AIMessage(content=f"根据知识库资料：{snippet} [1]。")

        # 5) 闲聊/通用
        return AIMessage(content="我是电商知识库智能客服（Lite 演示模式）。")


def _last_human_text(messages) -> str:
    """取最后一条人类消息的纯文本"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            if isinstance(msg.content, str):
                return msg.content
            return " ".join(str(p) for p in msg.content)
    return ""


def _pick_tool(question: str) -> tuple[str, dict]:
    """按关键词选工具：订单 → 订单查询；售后 → 政策；其它 → 知识库检索"""
    if _ORDER.search(question) or _ORDER_HINT.search(question):
        m = _ORDER.search(question)
        return "check_order_status", {"order_id": m.group(0) if m else ""}
    if _COMPARE.search(question):
        q = re.sub(r"^(帮我|请|麻烦)?(比较|对比)(一下)?", "", question)
        m = _COMPARE_SPLIT.search(q)
        if m:
            return "compare_products", {"products": [m.group(1).strip(), m.group(2).strip()]}
    if _AFTERSALES.search(question):
        return "get_after_sales_policy", {"topic": question[:50]}
    return "search_knowledge_base", {"query": question[:100]}


def get_llm(model: str | None = None, streaming: bool = True, temperature: float | None = None):
    """
    构造 Chat 模型客户端（轻量对象，按需创建即可）。
    model=None 时用生成模型；改写等轻任务传 llm_rewrite_model。
    """
    settings = get_settings()
    if settings.mock_llm:
        return MockChatModel(streaming=streaming)
    return ChatOpenAI(
        api_key=settings.resolved_llm_api_key,
        base_url=settings.llm_base_url,
        model=model or settings.llm_model,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_retries=settings.llm_max_retries,
        timeout=settings.llm_request_timeout,
        streaming=streaming,
        # 仅 LLM_SEND_THINKING_PARAM=true 时透传 enable_thinking（Qwen 系专用参数）
        extra_body=settings.thinking_extra_body or None,
    )
