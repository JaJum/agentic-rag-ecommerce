"""
bge-reranker-v2-m3 重排单例（M4）：
对混合检索候选打分重排，显著提升检索质量（企业级检索标志性组件）。
模型经 ModelScope 下载在本地（.env: RERANK_MODEL 路径）。
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
    """获取（或首次加载）CrossEncoder 重排模型"""
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
    """对 (query, text) 对批量打分（GPU 锁内串行推理，防并发抖动）"""
    if not texts:
        return []
    with _gpu_lock:
        return [float(s) for s in get_reranker().predict([(query, t) for t in texts])]
