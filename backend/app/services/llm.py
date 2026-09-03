"""
LLM 工厂（M4）：阿里云百炼 qwen3.8-flash（OpenAI 兼容，AsyncChatOpenAI）。
- 多模型分工：查询改写用 llm_rewrite_model，回答生成用 llm_model（.env 可配）
- enable_thinking 经 extra_body 透传（默认关闭保首字延迟）
"""
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_llm(model: str | None = None, streaming: bool = True, temperature: float | None = None):
    """
    构造 ChatOpenAI 客户端（轻量对象，按需创建即可）。
    model=None 时用生成模型；改写等轻任务传 llm_rewrite_model。
    """
    settings = get_settings()
    return ChatOpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.llm_base_url,
        model=model or settings.llm_model,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_retries=settings.llm_max_retries,
        timeout=settings.llm_request_timeout,
        streaming=streaming,
        # enable_thinking 透传给百炼（兼容模式扩展参数，显式传参避免告警）
        extra_body=settings.thinking_extra_body,
    )
