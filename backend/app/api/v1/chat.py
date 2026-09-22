"""
问答接口（M4 核心）：SSE 流式问答 + 引用溯源 + 反馈 + 导出 + 停止生成。
链路：上下文 → 查询改写 → 混合检索 → rerank → Prompt → 流式生成 → 引用解析 → 落库。
"""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.core.rate_limit import check_rate_limit
from app.db.base import AsyncSessionLocal, get_db
from app.db.models import (
    AgentRun,
    AgentStep,
    Feedback,
    Message,
    MessageCitation,
    QaLog,
    User,
)
from app.schemas.chat import ChatStreamRequest, FeedbackIn, SessionIdIn
from app.services import session_service
from app.services.agent.runner import run_agent_stream
from app.services.cache import bump_index_version, get_cache, qa_cache_key
from app.services.llm import get_llm
from app.services.rag.fallback import is_business_query, make_general_messages
from app.services.rag.generation import (
    FALLBACK_TEXT,
    extract_citations,
    make_messages,
)
from app.services.rag.retrieval import hybrid_search, is_relevant, rerank_top
from app.services.rag.rewrite import rewrite_query
from app.utils.sensitive import check_sensitive, clean_input

router = APIRouter(tags=["问答"])
log = get_logger(__name__)

# 停止生成：session_id → Event（POST /chat/stop 置位，流式循环检测）
_stop_events: dict[str, asyncio.Event] = {}

# LLM 并发信号量（方案⑬：限并发防 API 过载）
_llm_semaphore: asyncio.Semaphore | None = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    """惰性创建信号量（绑定当前事件循环）"""
    global _llm_semaphore
    if _llm_semaphore is None:
        from app.core.config import get_settings

        _llm_semaphore = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _llm_semaphore


@router.post("/chat/stream", summary="SSE 流式问答")
async def chat_stream(
    body: ChatStreamRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    流式问答（SSE 事件：meta → citation* → token* → done | fallback | error）。
    session_id 为空时自动新建会话。
    """
    # 限流：每用户问答 10 次/分钟（M5）
    check_rate_limit(user.id, scope="chat")

    # 安全防护（M6）：输入清洗 + 敏感词 + prompt injection 拦截
    body.query = clean_input(body.query)
    check_sensitive(body.query)

    # 会话归属校验/创建（越权 → 404）
    if body.session_id:
        session = await session_service.get_user_session(db, user.id, body.session_id)
    else:
        session = await session_service.create_session(db, user.id)

    # 历史（改写用，取最近 6 条）
    history_rows = await session_service.list_messages(db, session.id)
    history = [{"role": m["role"], "content": m["content"]} for m in history_rows][-6:]

    # 先落用户消息（生成失败历史也不丢）
    user_msg = Message(id=_uuid(), session_id=session.id, role="user", content=body.query)
    db.add(user_msg)
    # 首问自动命名会话
    if session.title == "新会话":
        session.title = body.query[:30]
    await db.commit()

    stop_event = asyncio.Event()
    _stop_events[session.id] = stop_event

    async def event_gen():
        content = ""
        assistant_msg_id = _uuid()
        t_start = time.perf_counter()
        first_token_ms = None
        token_usage = None
        persisted = False
        try:
            # ⓪ 精确问答缓存：命中直接回放（方案⑧，重复问题零检索零 LLM）
            cache = get_cache()
            cache_key = qa_cache_key(body.query, history)
            cached = cache.get(cache_key)
            if cached:
                cached_msg_id = _uuid()
                yield _sse("meta", {
                    "message_id": cached_msg_id,
                    "session_id": session.id,
                    "rewritten_query": cached["rewritten_query"],
                    "retrieval_ms": 0,
                    "cache_hit": True,
                })
                for entry in cached["citations"]:
                    yield _sse("citation", entry)
                # 一次性回放完整回答（对用户表现为"秒回"）
                yield _sse("token", {"delta": cached["content"]})
                await _persist_message(session.id, cached_msg_id, "assistant",
                                       cached["content"], cached["rewritten_query"],
                                       cached["citations"], "complete", None)
                await _persist_citations(cached_msg_id, cached["citations"])
                latency_ms = int((time.perf_counter() - t_start) * 1000)
                await _persist_qa_log(user.id, session.id, body.query, cached["rewritten_query"],
                                      latency_ms, latency_ms, len(cached["citations"]), hit=1,
                                      route=cached.get("route") or "cache", tool_count=0)
                log.info("chat.cache_hit", user_id=user.id, latency_ms=latency_ms)
                yield _sse("done", {"message_id": cached_msg_id, "hit": True,
                                    "latency_ms": latency_ms, "cache_hit": True})
                return

            # ⓪-2 Agent 分支（M8）：LangGraph 编排；失败自动降级到原 RAG 链路
            if get_settings().agent_enabled:
                agent_content = ""
                agent_ctx: list[dict] = []
                agent_status = "ok"
                agent_route = None
                agent_steps = 0
                agent_rewritten = body.query
                agent_trace: list[dict] = []
                agent_usage: dict = {}
                agent_error = None
                try:
                    yield _sse("meta", {
                        "message_id": assistant_msg_id,
                        "session_id": session.id,
                        "agent_enabled": True,
                        "retrieval_ms": 0,
                    })
                    async for ev in run_agent_stream(
                        body.query,
                        history,
                        message_id=assistant_msg_id,
                        session_id=session.id,
                        user_id=user.id,
                    ):
                        name = ev.get("event")
                        data = ev.get("data") or {}
                        if name == "token":
                            delta = data.get("delta") or ""
                            if not delta:
                                continue
                            if first_token_ms is None:
                                first_token_ms = int((time.perf_counter() - t_start) * 1000)
                            agent_content += delta
                            content += delta
                            yield _sse("token", {"delta": delta})
                        elif name == "done":
                            agent_ctx = data.get("contexts") or []
                            agent_status = data.get("status") or "ok"
                            agent_route = data.get("route")
                            agent_steps = data.get("steps") or 0
                            agent_rewritten = data.get("rewritten_query") or body.query
                            agent_usage = data.get("usage") or {}
                            agent_error = data.get("error")
                            continue
                        else:
                            if name in ("step", "tool_call", "tool_result"):
                                agent_trace.append(_trace_entry(name, data))
                            yield _sse(name, data)

                    # 引用列表：编号与最终 Prompt 中的 [n] 一致
                    citations_meta = []
                    for i, c in enumerate(agent_ctx, start=1):
                        meta = c.get("meta") or {}
                        entry = {
                            "n": i,
                            "chunk_id": c.get("chunk_id", ""),
                            "doc_id": c.get("doc_id") or meta.get("doc_id"),
                            "doc_name": c.get("doc_name") or meta.get("doc_name", "未知来源"),
                            "chunk_type": c.get("chunk_type"),
                            "snippet": (c.get("text") or "")[:300],
                            "score": round(float(c.get("score", 0.0)), 4),
                            "cited": False,
                        }
                        citations_meta.append(entry)
                        yield _sse("citation", entry)

                    cited = set(extract_citations(agent_content, len(citations_meta)))
                    for entry in citations_meta:
                        entry["cited"] = entry["n"] in cited

                    # Agent 失败且无任何产出 → 先记录失败运行，再降级回原 RAG 链路
                    if agent_status in ("error", "timeout") and not agent_content:
                        await _persist_agent_run(
                            run_id=assistant_msg_id,
                            message_id=assistant_msg_id,
                            session_id=session.id,
                            user_id=user.id,
                            route=agent_route,
                            status=agent_status,
                            steps=agent_steps,
                            latency_ms=int((time.perf_counter() - t_start) * 1000),
                            first_token_ms=first_token_ms,
                            token_usage=(agent_usage or {}).get("total_tokens"),
                            error=agent_error,
                            trace=agent_trace,
                        )
                        raise RuntimeError(f"agent_{agent_status}")

                    latency_ms = int((time.perf_counter() - t_start) * 1000)
                    msg_status = {
                        "ok": "complete",
                        "fallback": "fallback",
                        "timeout": "partial",
                        "error": "error",
                    }.get(agent_status, "complete")
                    if stop_event.is_set():
                        msg_status = "partial"
                    if not agent_content:
                        agent_content = FALLBACK_TEXT
                        if msg_status == "complete":
                            msg_status = "fallback"
                        yield _sse("token", {"delta": agent_content})

                    await _persist_message(
                        session.id,
                        assistant_msg_id,
                        "assistant",
                        agent_content,
                        agent_rewritten,
                        citations_meta,
                        msg_status,
                        None,
                    )
                    persisted = True
                    await _persist_citations(assistant_msg_id, citations_meta)
                    await _persist_qa_log(
                        user.id,
                        session.id,
                        body.query,
                        agent_rewritten,
                        latency_ms,
                        first_token_ms,
                        len(citations_meta),
                        hit=1 if citations_meta else 0,
                        route=agent_route or "agent",
                        tool_count=agent_steps,
                    )
                    await _persist_agent_run(
                        run_id=assistant_msg_id,
                        message_id=assistant_msg_id,
                        session_id=session.id,
                        user_id=user.id,
                        route=agent_route,
                        status=agent_status,
                        steps=agent_steps,
                        latency_ms=latency_ms,
                        first_token_ms=first_token_ms,
                        token_usage=(agent_usage or {}).get("total_tokens"),
                        error=agent_error,
                        trace=agent_trace,
                    )
                    if msg_status == "complete":
                        cache.set(cache_key, {
                            "content": agent_content,
                            "citations": citations_meta,
                            "rewritten_query": agent_rewritten,
                            "route": agent_route or "agent",
                        })
                    log.info("chat.agent_done", route=agent_route, steps=agent_steps,
                             latency_ms=latency_ms, citations=len(citations_meta))
                    yield _sse("done", {
                        "message_id": assistant_msg_id,
                        "hit": bool(citations_meta),
                        "answer_source": "agent",
                        "route": agent_route,
                        "steps": agent_steps,
                        "latency_ms": latency_ms,
                        "first_token_ms": first_token_ms,
                    })
                    return
                except Exception as exc:  # noqa: BLE001
                    log.error("chat.agent_failed", error=str(exc), exc_info=True)
                    if content:
                        # 已经输出部分内容：不重跑，保存 partial
                        await _persist_message(session.id, assistant_msg_id, "assistant",
                                               content, None, [], "partial", None)
                        persisted = True
                        yield _sse("done", {
                            "message_id": assistant_msg_id,
                            "hit": False,
                            "answer_source": "agent_error",
                            "latency_ms": int((time.perf_counter() - t_start) * 1000),
                        })
                        return
                    # 未输出任何内容：清空状态，降级到原 RAG 链路
                    content = ""
                    first_token_ms = None
            # ① 查询改写（多轮指代消解，失败自动回退原问题）
            rewritten = await rewrite_query(body.query, history)

            # ② 混合检索 + rerank（同步重计算卸载到线程池，避免阻塞事件循环——M5 压测关键修复）
            t_ret = time.perf_counter()
            candidates = await asyncio.to_thread(hybrid_search, rewritten)
            t_rank = time.perf_counter()
            top = await asyncio.to_thread(rerank_top, rewritten, candidates)
            retrieval_ms = int((t_rank - t_ret) * 1000)
            rerank_ms = int((time.perf_counter() - t_rank) * 1000)

            # ③ 兜底判定：知识库未覆盖 → 智能兜底（业务问题严格拒答 / 闲聊走通用回答）
            if not is_relevant(top):
                is_business = is_business_query(body.query) or is_business_query(rewritten)

                # ③-a 业务问题（商品/参数/价格/售后）→ 严格拒答，不调用 LLM，防编造红线
                if is_business:
                    yield _sse("fallback", {"reason": "no_relevant_doc", "top_score": top[0]["rerank_score"] if top else None})
                    await _persist_qa_log(user.id, session.id, body.query, rewritten,
                                          int((time.perf_counter() - t_start) * 1000), None, 0, hit=0,
                                          route="rag", tool_count=0)
                    await _persist_message(session.id, assistant_msg_id, "assistant",
                                           FALLBACK_TEXT, rewritten, [], "fallback", None)
                    yield _sse("done", {"message_id": assistant_msg_id, "hit": False,
                                        "answer_source": "fallback",
                                        "latency_ms": int((time.perf_counter() - t_start) * 1000)})
                    return

                # ③-b 闲聊/通用问题 → 大模型直接回答（标注非知识库来源，无引用）
                yield _sse("meta", {
                    "message_id": assistant_msg_id,
                    "session_id": session.id,
                    "rewritten_query": rewritten,
                    "retrieval_ms": retrieval_ms,
                    "rerank_ms": rerank_ms,
                    "answer_source": "general",
                })
                llm = get_llm(streaming=True)
                stop_event.clear()
                t_llm = time.perf_counter()
                state: dict = {}
                async for kind, delta in _astream_llm(
                    llm, make_general_messages(body.query, history), stop_event, state
                ):
                    if kind == "reasoning":
                        yield _sse("reasoning", {"delta": delta})
                    else:
                        if first_token_ms is None:
                            first_token_ms = int((time.perf_counter() - t_start) * 1000)
                        content += delta
                        yield _sse("token", {"delta": delta})
                llm_ms = int((time.perf_counter() - t_llm) * 1000)
                token_usage = state.get("tokens")
                latency_ms = int((time.perf_counter() - t_start) * 1000)
                # 通用回答若触发"涉商业务不编造"红线（回复即兜底文案）→ 归类为拒答，来源标签更准确
                if content.strip().startswith("抱歉，知识库中未找到相关内容"):
                    status, answer_source = "fallback", "fallback"
                elif stop_event.is_set():
                    status, answer_source = "partial", "general"
                else:
                    status, answer_source = "general", "general"
                await _persist_message(session.id, assistant_msg_id, "assistant",
                                       content or FALLBACK_TEXT, rewritten, [], status, token_usage)
                persisted = True
                await _persist_qa_log(user.id, session.id, body.query, rewritten,
                                      latency_ms, first_token_ms, 0, hit=0,
                                      route="rag", tool_count=0)
                log.info("chat.general", llm_ms=llm_ms, latency_ms=latency_ms, source=answer_source)
                yield _sse("done", {"message_id": assistant_msg_id, "hit": False,
                                    "answer_source": answer_source, "latency_ms": latency_ms,
                                    "first_token_ms": first_token_ms, "llm_ms": llm_ms})
                return

            # ④ meta + citation 事件（先给引用面板数据）
            yield _sse("meta", {
                "message_id": assistant_msg_id,
                "session_id": session.id,
                "rewritten_query": rewritten,
                "retrieval_ms": retrieval_ms,
                "rerank_ms": rerank_ms,
            })
            citations_meta = []
            for i, c in enumerate(top, start=1):
                meta = c.get("meta", {})
                entry = {
                    "n": i,
                    "chunk_id": c["chunk_id"],
                    "doc_id": meta.get("doc_id"),
                    "doc_name": meta.get("doc_name", "未知来源"),
                    "chunk_type": meta.get("chunk_type"),
                    "snippet": c["text"][:300],
                    "score": round(c.get("rerank_score", 0.0), 4),
                    "cited": False,  # 生成结束后按实际引用回填
                }
                citations_meta.append(entry)
                yield _sse("citation", entry)

            # ⑤ 流式生成（信号量限并发；thinking 开启时 reasoning 走 reasoning 事件）
            llm = get_llm(streaming=True)
            messages = make_messages(body.query, top)
            stop_event.clear()
            t_llm = time.perf_counter()
            state = {}
            async for kind, delta in _astream_llm(llm, messages, stop_event, state):
                if kind == "reasoning":
                    yield _sse("reasoning", {"delta": delta})
                else:
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - t_start) * 1000)
                    content += delta
                    yield _sse("token", {"delta": delta})
            llm_ms = int((time.perf_counter() - t_llm) * 1000)
            token_usage = state.get("tokens")

            # ⑥ 引用解析与回填（[n] 越界剔除）
            cited = set(extract_citations(content, len(top)))
            for entry in citations_meta:
                entry["cited"] = entry["n"] in cited
            latency_ms = int((time.perf_counter() - t_start) * 1000)

            # ⑦ 落库：assistant 消息 + 引用快照 + 问答日志
            status = "partial" if stop_event.is_set() else "complete"
            await _persist_message(session.id, assistant_msg_id, "assistant",
                                   content or FALLBACK_TEXT, rewritten,
                                   citations_meta, status, token_usage)
            persisted = True
            await _persist_citations(assistant_msg_id, citations_meta)
            await _persist_qa_log(user.id, session.id, body.query, rewritten,
                                  latency_ms, first_token_ms, len(top), hit=1,
                                  route="rag", tool_count=0)
            # 写入问答缓存（仅完整生成，partial 不缓存）
            if status == "complete" and content:
                cache.set(cache_key, {
                    "content": content,
                    "citations": citations_meta,
                    "rewritten_query": rewritten,
                    "route": "rag",
                })
            log.info("chat.done", retrieval_ms=retrieval_ms, rerank_ms=rerank_ms,
                     llm_ms=llm_ms, first_token_ms=first_token_ms, latency_ms=latency_ms)
            yield _sse("done", {
                "message_id": assistant_msg_id,
                "hit": True,
                "latency_ms": latency_ms,
                "first_token_ms": first_token_ms,
                "llm_ms": llm_ms,
                "tokens": token_usage,
            })
        except Exception as exc:  # noqa: BLE001 —— SSE 内异常转 error 事件
            log.error("chat.stream_error", error=str(exc), exc_info=True)
            yield _sse("error", {"code": "LLM_ERROR", "message": "生成失败，请稍后重试"})
        finally:
            # 断连/中断兜底：已生成内容存为 partial（历史可看）
            if not persisted and content:
                await _persist_message(session.id, assistant_msg_id, "assistant",
                                       content, None, [], "partial", None)
            _stop_events.pop(session.id, None)

    return EventSourceResponse(event_gen(), ping=15)


@router.post("/chat/stop", summary="停止生成")
async def stop_generation(
    body: SessionIdIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """停止指定会话的流式生成（服务端置停止标记）"""
    await session_service.get_user_session(db, user.id, body.session_id)
    event = _stop_events.get(body.session_id)
    if event:
        event.set()
    return {"message": "已请求停止"}


@router.get("/chat/messages/{message_id}/citations", summary="回答的引用列表")
async def message_citations(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """某回答引用的知识库片段（含原文快照）"""
    await _check_message_owner(db, user.id, message_id)
    return await session_service.get_citations(db, message_id)


@router.post("/chat/messages/{message_id}/feedback", summary="点赞/点踩")
async def message_feedback(
    message_id: str,
    body: FeedbackIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """反馈（需求 8）：一条消息一条反馈，重复提交覆盖"""
    await _check_message_owner(db, user.id, message_id)
    if body.rating not in (1, -1):
        raise BizError("rating 只能是 1 或 -1", code="BAD_RATING")
    result = await db.execute(select(Feedback).where(Feedback.message_id == message_id))
    fb = result.scalar_one_or_none()
    if fb:
        fb.rating = body.rating
        fb.comment = body.comment
    else:
        db.add(Feedback(message_id=message_id, user_id=user.id,
                        rating=body.rating, comment=body.comment))
    await db.commit()
    return {"message": "反馈成功"}


@router.get("/chat/sessions/{session_id}/export", summary="导出对话（Markdown）")
async def export_session(
    session_id: str,
    format: str = Query("md", pattern="^(md)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """导出对话为 Markdown（需求 8 扩展）"""
    await session_service.get_user_session(db, user.id, session_id)
    rows = await session_service.list_messages(db, session_id)
    lines = ["# 对话导出\n"]
    for m in rows:
        role = "🧑 用户" if m["role"] == "user" else "🤖 助手"
        lines.append(f"## {role}\n\n{m['content']}\n")
        if m.get("citations"):
            lines.append("**引用来源：**")
            for c in m["citations"]:
                lines.append(f"- [{c['citation_no']}] {c.get('doc_name', '?')}（{c.get('snippet', '')[:60]}…）")
            lines.append("")
    return {"markdown": "\n".join(lines)}


@router.get("/chat/messages/{message_id}/trace", summary="查询消息的 Agent 执行轨迹")
async def get_message_trace(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """历史消息轨迹回放（F-04）：返回运行摘要与逐步轨迹，无轨迹时 enabled=false"""
    await _check_message_owner(db, user.id, message_id)
    run = (await db.execute(
        select(AgentRun).where(AgentRun.message_id == message_id)
    )).scalar_one_or_none()
    if run is None:
        return {"enabled": False, "steps": []}

    rows = (await db.execute(
        select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.id)
    )).scalars().all()
    return {
        "enabled": True,
        "run": {
            "id": run.id,
            "route": run.route,
            "status": run.status,
            "step_count": run.step_count,
            "latency_ms": run.latency_ms,
            "first_token_ms": run.first_token_ms,
            "token_usage": run.token_usage,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        },
        "steps": [
            {
                "step_no": r.step_no,
                "node": r.node,
                "tool_name": r.tool_name,
                "args_preview": r.args_preview,
                "result_preview": r.result_preview,
                "ok": r.ok,
            }
            for r in rows
        ],
    }


# ---------------- 内部工具 ----------------

def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


def _sse(event: str, data: dict) -> dict:
    """构造 SSE 事件（data 为 JSON 字符串）"""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def _astream_llm(llm, messages, stop_event: asyncio.Event, state: dict):
    """
    流式生成（信号量限并发）：产出 ("reasoning"|"token", delta) 二元组。
    usage 写入 state["tokens"]；stop_event 置位即中断生成。
    """
    async with _get_llm_semaphore():
        async for chunk in llm.astream(messages):
            if stop_event.is_set():
                break
            reasoning = (chunk.additional_kwargs or {}).get("reasoning_content")
            if reasoning:
                yield ("reasoning", reasoning)
            if chunk.content:
                yield ("token", chunk.content)
            if getattr(chunk, "usage_metadata", None):
                state["tokens"] = chunk.usage_metadata.get("total_tokens")


async def _persist_message(session_id, msg_id, role, content, rewritten,
                           citations, status, token_usage) -> None:
    """落库消息（独立会话，避免长流式期间占用请求会话）"""
    async with AsyncSessionLocal() as db:
        db.add(Message(
            id=msg_id, session_id=session_id, role=role, content=content,
            rewritten_query=rewritten, citations=citations,
            token_usage=token_usage, status=status,
        ))
        await session_service.touch_session(db, session_id)
        await db.commit()


async def _persist_citations(message_id: str, citations_meta: list[dict]) -> None:
    """落库引用快照（原文快照保证删文档后历史仍可展示）"""
    async with AsyncSessionLocal() as db:
        db.add_all([
            MessageCitation(
                message_id=message_id,
                chunk_id=e["chunk_id"],
                doc_id=e.get("doc_id"),
                citation_no=e["n"],
                snippet=e.get("snippet"),
                score=e.get("score"),
                cited=1 if e.get("cited") else 0,
            )
            for e in citations_meta
        ])
        await db.commit()


async def _persist_qa_log(user_id, session_id, query, rewritten,
                          latency_ms, first_token_ms, retrieval_count, hit,
                          route=None, tool_count=0) -> None:
    """落库问答日志（仪表盘/性能统计数据源）"""
    async with AsyncSessionLocal() as db:
        db.add(QaLog(
            user_id=user_id, session_id=session_id, query=query,
            rewritten_query=rewritten, latency_ms=latency_ms,
            first_token_ms=first_token_ms, retrieval_count=retrieval_count,
            hit=hit, route=route, tool_count=tool_count,
        ))
        await db.commit()


def _trace_entry(name: str, data: dict) -> dict:
    """把 SSE 事件归一为一条 AgentStep 轨迹（参数/结果均截断，避免敏感信息入库）"""
    if name == "tool_call":
        return {
            "node": "tool_call",
            "step_no": int(data.get("step_no") or 0),
            "tool_name": data.get("tool"),
            "args_preview": (data.get("args_preview") or "")[:500],
        }
    if name == "tool_result":
        return {
            "node": "tool_result",
            "step_no": int(data.get("step_no") or 0),
            "tool_name": data.get("tool"),
            "ok": 1 if data.get("ok") else 0,
            "result_preview": (data.get("summary") or "")[:500],
        }
    return {
        "node": data.get("node") or "step",
        "step_no": int(data.get("step_no") or 0),
        "ok": 1 if data.get("status") == "ok" else 0,
        "result_preview": (data.get("label") or "")[:500],
    }


async def _persist_agent_run(*, run_id, message_id, session_id, user_id, route, status,
                             steps, latency_ms, first_token_ms, token_usage,
                             error, trace) -> None:
    """落库 Agent 运行与轨迹（失败不阻塞主流程）"""
    try:
        tool_calls = [
            {k: t.get(k) for k in ("step_no", "node", "tool_name", "ok")}
            for t in trace
            if t.get("node") in ("tool_call", "tool_result")
        ]
        async with AsyncSessionLocal() as db:
            db.add(AgentRun(
                id=run_id, message_id=message_id, session_id=session_id, user_id=user_id,
                route=route, status=status or "ok", step_count=int(steps or 0),
                tool_calls=tool_calls, latency_ms=latency_ms,
                first_token_ms=first_token_ms, token_usage=token_usage,
                error=(error or None),
            ))
            db.add_all([
                AgentStep(
                    run_id=run_id,
                    step_no=int(t.get("step_no") if t.get("step_no") is not None else i),
                    node=t.get("node") or "step",
                    tool_name=t.get("tool_name"),
                    args_preview=t.get("args_preview"),
                    result_preview=t.get("result_preview"),
                    ok=t.get("ok"),
                )
                for i, t in enumerate(trace)
            ])
            await db.commit()
    except Exception as exc:  # noqa: BLE001 —— 轨迹落库失败不影响回答
        log.warning("chat.agent_trace_persist_failed", error=str(exc))


async def _check_message_owner(db: AsyncSession, user_id: int, message_id: str) -> Message:
    """校验消息归属（越权 → 404）"""
    msg = await db.get(Message, message_id)
    if msg is None:
        raise BizError("消息不存在", code="MESSAGE_NOT_FOUND", status_code=404)
    session = await db.get(_session_model(), msg.session_id)
    if session is None or session.user_id != user_id:
        raise BizError("消息不存在", code="MESSAGE_NOT_FOUND", status_code=404)
    return msg


def _session_model():
    from app.db.models import ChatSession

    return ChatSession
