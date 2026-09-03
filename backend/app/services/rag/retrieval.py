"""
混合检索与重排（M4，企业级检索核心）：
BM25 关键词 ⊕ Chroma 向量语义 → RRF 融合 → bge-reranker 精排 → 阈值判定。
权重与阈值均可 .env 调节（论文可做消融实验）。
"""
from app.core.config import get_settings
from app.core.logging import get_logger
from app.services import vector_store
from app.services.bm25_index import bm25_index
from app.services.reranker import rerank as rerank_scores

log = get_logger(__name__)

# RRF 常数（标准取值 60）
_RRF_K = 60


def hybrid_search(query: str) -> list[dict]:
    """
    双路检索 + RRF（Reciprocal Rank Fusion）融合。
    返回候选列表：[{chunk_id, text, meta, rrf_score}]，按融合分降序。
    """
    settings = get_settings()
    k = settings.retrieval_k

    # 双路各取 top-k
    bm25_hits = bm25_index.search(query, k=k)                    # [(chunk_id, score)]
    vec_hits = vector_store.search(query, k=k)                   # [(text, score, meta)]

    # RRF 融合：score = Σ 1/(60 + rank)，排名越靠前贡献越大
    fused: dict[str, dict] = {}
    for rank, (cid, score) in enumerate(bm25_hits):
        fused.setdefault(cid, {"chunk_id": cid, "text": "", "meta": {}, "rrf_score": 0.0})
        fused[cid]["rrf_score"] += 1.0 / (_RRF_K + rank + 1)
        fused[cid]["bm25_score"] = score

    for rank, (text, score, meta) in enumerate(vec_hits):
        cid = meta.get("chunk_id", "")
        if not cid:
            continue
        entry = fused.setdefault(cid, {"chunk_id": cid, "text": "", "meta": {}, "rrf_score": 0.0})
        entry["rrf_score"] += 1.0 / (_RRF_K + rank + 1)
        entry["text"] = text
        entry["meta"] = meta
        entry["vec_score"] = score

    # 只命中 BM25 的候选补全文本（从 meta 不足以还原 → 从 chunks 表取？为简化：
    # 向量路几乎必然覆盖同批块，text 为空的候选丢弃）
    candidates = [c for c in fused.values() if c["text"]]
    candidates.sort(key=lambda c: c["rrf_score"], reverse=True)
    log.info("retrieval.hybrid", bm25=len(bm25_hits), vector=len(vec_hits), fused=len(candidates))
    return candidates


def rerank_top(query: str, candidates: list[dict]) -> list[dict]:
    """
    bge-reranker 精排：对融合候选打分重排，返回 top_n（附 rerank_score）。
    性能（M5）：重排输入截断 top 10（RRF 已按融合分排序），降低 GPU 负载。
    """
    settings = get_settings()
    top_n = settings.rerank_top_n
    if not candidates:
        return []
    candidates = candidates[:10]
    scores = rerank_scores(query, [c["text"] for c in candidates])
    for c, s in zip(candidates, scores):
        c["rerank_score"] = s
    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
    top = candidates[:top_n]
    log.info("retrieval.rerank", top_score=top[0]["rerank_score"] if top else None)
    return top


def is_relevant(top: list[dict]) -> bool:
    """阈值判定：最高分低于阈值视为知识库未覆盖 → 兜底拒答"""
    threshold = get_settings().rerank_threshold
    return bool(top) and top[0]["rerank_score"] >= threshold
