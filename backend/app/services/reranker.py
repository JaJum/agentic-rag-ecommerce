"""
Rerank 分发层：local=本地 bge-reranker-v2-m3，api=通用 /rerank 接口，none=跳过精排。
对融合候选重新打分，显著提升检索质量（企业级检索标志性组件）。
local 模式模型经 ModelScope 下载在本地（.env: RERANK_MODEL 路径）。
M5：GPU 推理加锁串行化——并发请求排队而非 CUDA 抖动，降低 P95 尾延迟。
"""
import threading

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.embeddings import resolve_device

log = get_logger(__name__)

_reranker = None  # 常驻单例
_gpu_lock = threading.Lock()  # GPU 推理串行化（防并发抖动）


def get_reranker():
    """获取（或首次加载）本地 CrossEncoder 重排模型"""
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        settings = get_settings()
        device = resolve_device(settings.device)
        log.info("reranker.loading", model=settings.rerank_model, device=device)
        _reranker = CrossEncoder(settings.rerank_model, device=device)
        log.info("reranker.ready")
    return _reranker


def rerank(query: str, texts: list[str]) -> list[float]:
    """按 RERANK_PROVIDER 分发打分，返回与 texts 等长的分数列表（阻塞调用，外层用 to_thread）"""
    if not texts:
        return []
    provider = get_settings().rerank_provider
    if provider == "none":
        # 调用方应跳过精排；此处保底返回 0 分，避免误把候选判成高相关
        return [0.0] * len(texts)
    if provider == "api":
        return _rerank_api(query, texts)
    with _gpu_lock:
        return [float(s) for s in get_reranker().predict([(query, t) for t in texts])]


def _rerank_api(query: str, texts: list[str]) -> list[float]:
    """
    通用 /rerank 协议（Jina / Cohere / SiliconFlow / 阿里云百炼 请求体一致）：
    POST {base}/rerank {model, query, documents, top_n} → results[{index, relevance_score}]
    """
    import httpx

    settings = get_settings()
    base = (settings.rerank_api_base or settings.llm_base_url).rstrip("/")
    key = settings.rerank_api_key or settings.resolved_llm_api_key
    resp = httpx.post(
        f"{base}/rerank",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": settings.rerank_api_model,
            "query": query,
            "documents": texts,
            "top_n": len(texts),
        },
        timeout=settings.agent_tool_timeout_s,
    )
    resp.raise_for_status()
    body = resp.json()
    scores = [0.0] * len(texts)
    for item in body.get("results") or body.get("data") or []:
        idx = item.get("index")
        if isinstance(idx, int) and 0 <= idx < len(scores):
            scores[idx] = float(item.get("relevance_score", item.get("score", 0.0)))
    return scores
