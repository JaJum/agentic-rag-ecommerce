"""
LangGraph 状态机（A-13）。

route → general_chat / rag_fast / agent ⇄ tools → finalize → verify → END

设计要点：
- 单跳知识问题走 rag_fast（原 RAG 快速路径），只有业务/多跳问题进 Agent；
- agent 最多 AGENT_MAX_STEPS 步，达到上限强制 finalize；
- 所有知识块只能来自工具 artifact，保证引用可溯源；
- 任何节点异常由 runner 统一兜底，chat 层可回退到原 RAG 链路。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.agent.prompts import AGENT_SYSTEM_PROMPT
from app.services.agent.state import AgentState
from app.services.agent.tools import (
    ALL_TOOLS,
    EMPTY_RESULT_TEXT,
    _dedupe,
    _search_contexts,
)
from app.services.agent.trace import preview
from app.services.bm25_index import bm25_index
from app.services.llm import get_llm
from app.services.rag.fallback import is_business_query, make_general_messages
from app.services.rag.generation import FALLBACK_TEXT, extract_citations, make_messages
from app.services.rag.rewrite import rewrite_query

log = get_logger(__name__)

# 路由规则
_ORDER_HINT = re.compile(r"(订单|物流|快递|发货|签收|运单|到哪了)", re.IGNORECASE)
_ORDER_ID = re.compile(r"ORD-\d{8}-\d{4}", re.IGNORECASE)
# 售后/交易流程：走 Agent 工具（政策检索 / 工单），而非单跳 RAG
_AFTERSALES_HINT = re.compile(
    r"(退货|退款|换货|退换|保修|质保|三包|售后|维修|发票|价保|以旧换新)",
    re.IGNORECASE,
)
_COMPARE_HINT = re.compile(
    r"(对比|比较|区别|差异|哪个.{0,6}(?:更|最)|哪款.{0,6}(?:更|最)|怎么选|选哪个|差价|差多少|相差"
    r"|更值得|更划算|哪个好|\bvs\b|还是|比价|(?<!价)比.{0,10}(?:贵|便宜|高|低|大|小|重|轻|强|快))",
    re.IGNORECASE,
)
_CHITCHAT = re.compile(
    r"^\s*(你好|您好|hi|hello|嗨|在吗|谢谢|再见|你是谁|你能做什么)[!！。？?~\s]*$",
    re.IGNORECASE,
)


def _writer() -> Callable[[dict], None]:
    """获取自定义流写入器；非流式上下文下退化为空函数"""
    try:
        return get_stream_writer()
    except Exception:  # noqa: BLE001
        return lambda _event: None


def _history_messages(history: list[dict] | None) -> list[Any]:
    """把历史记录转成 LangChain 消息（限量，防上下文膨胀）"""
    messages: list[Any] = []
    for item in (history or [])[-6:]:
        content = (item.get("content") or "")[:1000]
        if not content:
            continue
        if item.get("role") == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    return messages


def filter_duplicate_calls(
    calls: list[dict], seen: list[str]
) -> tuple[list[dict], list[str]]:
    """过滤「同一工具 + 同一参数」的重复调用，返回 (保留的调用, 新指纹列表)"""
    kept: list[dict] = []
    fingerprints = list(seen)
    for call in calls:
        fp = f"{call.get('name')}|{json.dumps(call.get('args', {}), ensure_ascii=False, sort_keys=True)}"
        if fp in fingerprints:
            continue
        fingerprints.append(fp)
        kept.append(call)
    return kept, fingerprints


def classify_route(query: str, rewritten: str = "") -> str:
    """规则路由：闲聊 / 单跳知识 / 业务操作 / 多跳对比"""
    text = f"{query} {rewritten}".strip()
    if _CHITCHAT.match(query or ""):
        return "chitchat"
    if _ORDER_ID.search(text) or _ORDER_HINT.search(text) or _AFTERSALES_HINT.search(text):
        return "business"
    if _COMPARE_HINT.search(text):
        return "multi_hop"
    if is_business_query(text):
        return "kb_simple"
    return "chitchat"


async def route_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """路由 + 指代消解；同时初始化 Agent 消息"""
    writer = _writer()
    query = state.get("query", "")
    history = state.get("history") or []
    rewritten = query
    try:
        rewritten = await rewrite_query(query, history)
    except Exception as exc:  # noqa: BLE001 —— 改写失败不阻塞
        log.warning("agent.route.rewrite_failed", error=str(exc))
    route = classify_route(query, rewritten)
    writer(
        {
            "event": "step",
            "data": {
                "step_no": 0,
                "node": "route",
                "status": "ok",
                "label": f"路由：{route}",
                "route": route,
                "rewritten_query": rewritten,
            },
        }
    )
    return {
        "rewritten": rewritten,
        "route": route,
        "messages": _history_messages(history) + [HumanMessage(content=rewritten)],
    }


async def general_chat_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """闲聊/通用问题：直接流式回答，不引用知识库"""
    writer = _writer()
    writer({"event": "step", "data": {"step_no": 0, "node": "general_chat", "status": "ok"}})
    llm = get_llm(streaming=True, temperature=0.5)
    answer: list[str] = []
    async for chunk in llm.astream(make_general_messages(state["query"], state.get("history"))):
        if chunk.content:
            answer.append(chunk.content)
            writer({"event": "token", "data": {"delta": chunk.content}})
    return {"answer": "".join(answer), "status": "ok", "contexts": []}


async def rag_fast_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """单跳知识问题：走原 RAG 快速路径（不经过 Agent 规划）"""
    writer = _writer()
    query = state.get("rewritten") or state["query"]
    try:
        contexts, relevant = await _search_contexts(query, 5)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.rag_fast.failed", error=str(exc))
        return {"contexts": [], "status": "error", "error": str(exc)[:200]}
    writer(
        {
            "event": "step",
            "data": {
                "step_no": 0,
                "node": "retrieval",
                "status": "ok" if relevant else "empty",
                "label": f"检索到 {len(contexts)} 条",
            },
        }
    )
    return {"contexts": contexts if relevant else [], "status": "ok" if relevant else "fallback"}


async def agent_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Agent 决策节点：LLM + 工具绑定，产出 tool_calls 或最终消息"""
    writer = _writer()
    settings = get_settings()
    writer(
        {
            "event": "step",
            "data": {
                "step_no": state.get("steps", 0),
                "node": "agent",
                "status": "ok",
                "label": "Agent 决策",
            },
        }
    )
    llm = get_llm(
        streaming=False,
        temperature=settings.agent_temperature,
        model=settings.agent_router_model_name,
    ).bind_tools(ALL_TOOLS)
    system = SystemMessage(
        content=AGENT_SYSTEM_PROMPT.format(max_steps=settings.agent_max_steps)
    )
    response = await llm.ainvoke([system, *state["messages"]])

    raw_calls = list(getattr(response, "tool_calls", None) or [])
    calls, fingerprints = filter_duplicate_calls(
        raw_calls, state.get("tool_fingerprints") or []
    )
    if len(calls) != len(raw_calls):
        log.info("agent.duplicate_calls_filtered", removed=len(raw_calls) - len(calls))
    if calls and state.get("steps", 0) >= settings.agent_max_steps:
        log.info("agent.max_steps_reached", steps=state.get("steps", 0))
        calls = []
    if len(calls) != len(raw_calls):
        response = AIMessage(
            content=response.content,
            tool_calls=calls,
            additional_kwargs=response.additional_kwargs,
        )

    for call in calls:
        writer(
            {
                "event": "tool_call",
                "data": {
                    "step_no": state.get("steps", 0) + 1,
                    "tool": call.get("name"),
                    "args_preview": preview(call.get("args", {}), 200),
                },
            }
        )

    usage = dict(getattr(response, "usage_metadata", None) or {})
    return {
        "messages": [response],
        "usage": {**state.get("usage", {}), **usage},
        "tool_fingerprints": fingerprints,
    }


def route_after_agent(state: AgentState) -> str:
    """有 tool_calls 且未超步数 → 执行工具；否则进入 finalize"""
    messages = state.get("messages") or []
    if not messages:
        return "finalize"
    last = messages[-1]
    if getattr(last, "tool_calls", None) and state.get("steps", 0) < get_settings().agent_max_steps:
        return "tools"
    return "finalize"


async def collect_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """收集 ToolMessage 的 artifact 到 contexts，并发出 tool_result 事件"""
    writer = _writer()
    messages = state.get("messages") or []
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    new_messages = tool_messages[state.get("tool_msg_count", 0):]

    contexts = list(state.get("contexts") or [])
    events = list(state.get("tool_events") or [])
    for msg in new_messages:
        artifact = msg.artifact if isinstance(msg.artifact, dict) else {}
        contexts.extend(artifact.get("contexts") or [])
        ok = not artifact.get("error")
        step_no = state.get("steps", 0) + 1
        summary = preview(msg.content, 200)
        events.append({"step_no": step_no, "tool": msg.name, "ok": ok, "summary": summary})
        writer(
            {
                "event": "tool_result",
                "data": {
                    "step_no": step_no,
                    "tool": msg.name,
                    "ok": ok,
                    "summary": summary,
                },
            }
        )

    return {
        "contexts": _dedupe(contexts),
        "tool_events": events,
        "tool_msg_count": len(tool_messages),
        "steps": state.get("steps", 0) + len(new_messages),
    }


async def finalize_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """基于工具产出的 contexts 流式生成带引用回答"""
    writer = _writer()
    contexts = state.get("contexts") or []
    if not contexts:
        # 工具失败但返回了可读的澄清/校验信息（如缺订单号、商品不存在）→ 直接转述
        events = state.get("tool_events") or []
        last = events[-1] if events else None
        if (
            last
            and not last.get("ok")
            and last.get("summary")
            and last["summary"] != EMPTY_RESULT_TEXT
        ):
            writer({"event": "token", "data": {"delta": last["summary"]}})
            return {"answer": last["summary"], "status": "ok"}
        writer({"event": "fallback", "data": {"reason": "no_relevant_doc"}})
        return {"answer": FALLBACK_TEXT, "status": "fallback"}

    query = state.get("rewritten") or state["query"]
    llm = get_llm(streaming=True)
    answer: list[str] = []
    usage: dict[str, int] = {}
    async for chunk in llm.astream(make_messages(query, contexts)):
        if chunk.content:
            answer.append(chunk.content)
            writer({"event": "token", "data": {"delta": chunk.content}})
        if getattr(chunk, "usage_metadata", None):
            usage = dict(chunk.usage_metadata)
    writer(
        {
            "event": "step",
            "data": {"step_no": state.get("steps", 0), "node": "finalize", "status": "ok"},
        }
    )
    return {
        "answer": "".join(answer),
        "status": "ok",
        "usage": {**state.get("usage", {}), **usage},
    }


async def verify_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """引用校验：统计有效 [n]，越界编号由 extract_citations 自动剔除"""
    writer = _writer()
    contexts = state.get("contexts") or []
    answer = state.get("answer") or ""
    cited = extract_citations(answer, len(contexts)) if answer else []
    writer(
        {
            "event": "step",
            "data": {
                "step_no": state.get("steps", 0),
                "node": "verify",
                "status": "ok",
                "label": f"引用 {len(cited)} 条",
            },
        }
    )
    return {"error": None}


_graph = None


def build_graph():
    """编译状态机（首次调用时构建，进程内复用）"""
    graph = StateGraph(AgentState)
    graph.add_node("route", route_node)
    graph.add_node("general_chat", general_chat_node)
    graph.add_node("rag_fast", rag_fast_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_node("collect", collect_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("verify", verify_node)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        lambda state: state.get("route"),
        {
            "chitchat": "general_chat",
            "out_of_scope": "general_chat",
            "kb_simple": "rag_fast",
            "business": "agent",
            "multi_hop": "agent",
        },
    )
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "finalize": "finalize"},
    )
    graph.add_edge("tools", "collect")
    graph.add_edge("collect", "agent")
    graph.add_edge("rag_fast", "finalize")
    graph.add_edge("finalize", "verify")
    graph.add_edge("verify", END)
    graph.add_edge("general_chat", END)
    return graph.compile()


def get_graph():
    """获取编译后的图单例"""
    global _graph
    if _graph is None:
        _graph = build_graph()
        log.info("agent.graph.compiled", tools=len(ALL_TOOLS))
    return _graph