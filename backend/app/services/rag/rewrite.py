"""
查询改写（M4）：多轮指代消解。
把「它续航多久」改写为「星河 X5 的电池续航参数」这类独立完整检索式，
提升多轮对话的检索命中率。改写失败/首轮无历史时回退原问题。
M5 优化：仅含指代词的问题才改写（启发式），独立问题零开销直通。
"""
import re

from app.core.logging import get_logger
from app.services.llm import get_llm

log = get_logger(__name__)

# 改写提示词：只产出检索式，不回答问题
_REWRITE_PROMPT = """你是检索查询改写助手。根据对话历史，把用户最新的问题改写成一个独立完整的检索式。
规则：
1. 消解指代（它/这款/刚才那个 → 具体商品名等）
2. 只输出改写后的检索式本身，不要解释、不要回答问题
3. 如果问题本身已独立完整，原样输出

对话历史：
{history}

最新问题：{query}
检索式："""


# 指代/省略嫌疑词：命中才需要改写（省一次 LLM 往返，降低首字延迟）
_PRONOUN_PATTERN = re.compile(r"(它|这|那|刚才|上面|前面|这款|那个|此|其)")


def _need_rewrite(query: str) -> bool:
    """启发式：问题含指代词才做改写，独立完整问题直接跳过"""
    return bool(_PRONOUN_PATTERN.search(query))


async def rewrite_query(query: str, history: list[dict]) -> str:
    """
    改写查询（qwen 免费模型 + 关 thinking）。
    history: [{"role": "user"/"assistant", "content": "..."}] 最近几轮
    """
    if not history or not _need_rewrite(query):  # 首轮/无指代 → 直接用原查询
        return query
    history_text = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in history)
    try:
        llm = get_llm(streaming=False, temperature=0.0)
        result = await llm.ainvoke(
            _REWRITE_PROMPT.format(history=history_text, query=query)
        )
        rewritten = (result.content or "").strip()
        # 空输出/超长输出回退原查询（防御性）
        if not rewritten or len(rewritten) > 500:
            return query
        log.info("rewrite.done", query=query, rewritten=rewritten)
        return rewritten
    except Exception as exc:  # noqa: BLE001 —— 改写失败不阻塞问答主链路
        log.warning("rewrite.failed", error=str(exc))
        return query
