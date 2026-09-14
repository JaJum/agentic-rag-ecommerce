"""
Agent 共享状态契约（LangGraph StateGraph）。

约定：
- contexts 只允许由工具产出，节点不得凭空追加，保证引用可溯源。
- tool_events 只存脱敏后的预览，供 SSE / agent_steps 落库。
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# 路由类型：决定走通用回答 / 原 RAG 快速路径 / Agent
Route = Literal["chitchat", "kb_simple", "business", "multi_hop", "out_of_scope"]

# 单次运行结果状态
AgentStatus = Literal["ok", "fallback", "error", "timeout"]


class AgentState(TypedDict, total=False):
    """LangGraph 节点之间传递的共享状态（扁平、可序列化）"""

    messages: Annotated[list[AnyMessage], add_messages]  # Agent 内部消息（含 tool 调用）
    query: str                 # 用户原始问题
    rewritten: str             # 指代消解后的检索式
    route: Route               # 路由结果
    steps: int                 # 已执行的工具步数
    contexts: list[dict[str, Any]]      # 工具产出的知识块（最终引用来源）
    tool_events: list[dict[str, Any]]   # 执行轨迹（脱敏）
    answer: str                # 最终答案
    status: AgentStatus        # 运行状态
    error: str | None          # 失败原因
    usage: dict[str, int]      # token 用量


def initial_state(query: str, history: list[dict] | None = None) -> AgentState:
    """构造一次运行的初始状态（history 为最近几轮 user/assistant）"""
    return AgentState(
        messages=[],
        query=query,
        rewritten=query,
        route="kb_simple",
        steps=0,
        contexts=[],
        tool_events=[],
        answer="",
        status="ok",
        error=None,
        usage={},
    )