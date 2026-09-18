"""
Agent 流式执行入口（A-17）。

把 LangGraph 的 custom 事件映射为项目统一 SSE 事件：
step / tool_call / tool_result / token / fallback / done / error。

chat 层只负责持久化与转发，不关心图内部结构。
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.agent.graph import get_graph
from app.services.agent.state import initial_state
from app.services.rag.generation import extract_citations

log = get_logger(__name__)


async def run_agent_stream(
    query: str,
    history: list[dict] | None = None,
    message_id: str = "",
    session_id: str | None = None,
    user_id: int | None = None,
) -> AsyncIterator[dict]:
    """执行 Agent 并逐条产出 SSE 事件（最后一个事件固定为 done）"""
    settings = get_settings()
    graph = get_graph()
    state = initial_state(query, history)
    config = {
        "configurable": {"session_id": session_id, "user_id": user_id},
        # 最坏路径：route + 每步(agent/tools/collect) + agent + finalize + verify
        "recursion_limit": 3 * settings.agent_max_steps + 6,  # 含 END 收尾余量
    }

    final_state: dict = {}
    first_token_ms: int | None = None
    started = time.perf_counter()

    try:
        async with asyncio.timeout(settings.agent_timeout_s):
            async for mode, data in graph.astream(
                state, config, stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    event = data
                    if event.get("event") == "token" and first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    yield event
                elif mode == "values":
                    final_state = data
    except (asyncio.TimeoutError, TimeoutError):
        log.warning("agent.timeout", query=query, timeout_s=settings.agent_timeout_s)
        yield {"event": "error", "data": {"code": "AGENT_TIMEOUT", "message": "执行超时，请稍后重试"}}
        final_state = {**final_state, "status": "timeout"}
    except Exception as exc:  # noqa: BLE001 —— 统一转 error 事件，由上层决定降级
        log.error("agent.stream_failed", error=str(exc), exc_info=True)
        yield {"event": "error", "data": {"code": "AGENT_ERROR", "message": "Agent 执行失败"}}
        final_state = {**final_state, "status": "error", "error": str(exc)[:200]}

    contexts = final_state.get("contexts") or []
    answer = final_state.get("answer") or ""
    cited = extract_citations(answer, len(contexts)) if answer else []
    latency_ms = int((time.perf_counter() - started) * 1000)

    yield {
        "event": "done",
        "data": {
            "message_id": message_id,
            "route": final_state.get("route"),
            "status": final_state.get("status", "ok"),
            "steps": final_state.get("steps", 0),
            "tool_events": final_state.get("tool_events") or [],
            "contexts": contexts,
            "answer": answer,
            "cited": cited,
            "rewritten_query": final_state.get("rewritten") or query,
            "latency_ms": latency_ms,
            "first_token_ms": first_token_ms,
            "usage": final_state.get("usage") or {},
        },
    }