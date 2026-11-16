"""
混合检索与重排（企业级检索核心）：
BM25 关键词 ⊕ Chroma 向量语义 → RRF 融合 → bge-reranker 精排 → 阈值判定。
权重与阈值均可 .env 调节（可做消融实验）。

Lite 模式（RETRIEVAL_MODE=bm25）：只走 BM25，不加载向量模型与重排模型，
用 BM25 分数排序代替精排——牺牲部分语义召回，换取「无 GPU/无 Key 也能跑」。
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

    if settings.retrieval_mode == "bm25":
        return _bm25_search(query, k)

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


def _bm25_search(query: str, k: int) -> list[dict]:
    """
    Lite 模式：BM25 单路检索，直接从索引取原文与元数据。
    额外用「查询词覆盖率」做相关性代理：BM25 只要有一个词命中就有分，
    会把「小米14 电池容量」这种库外问题误判为命中，故要求覆盖率不低于阈值。
    """
    settings = get_settings()
    query_tokens = set(bm25_index.tokenize(query))
    hits = bm25_index.search(query, k=k)
    candidates: list[dict] = []
    for cid, score in hits:
        doc = bm25_index.get_doc(cid)
        if not doc:
            continue
        text, meta = doc
        doc_tokens = set(bm25_index.tokenize(text))
        coverage = len(query_tokens & doc_tokens) / len(query_tokens) if query_tokens else 0.0
        if coverage < settings.bm25_min_coverage:
            continue
        candidates.append(
            {
                "chunk_id": cid,
                "text": text,
                "meta": meta,
                "bm25_score": score,
                "rrf_score": score,  # 单路时直接以 BM25 分排序
                "coverage": round(coverage, 3),
            }
        )
    candidates.sort(key=lambda c: c["bm25_score"], reverse=True)
    log.info("retrieval.bm25_only", hits=len(hits), candidates=len(candidates))
    return candidates


def rerank_top(query: str, candidates: list[dict]) -> list[dict]:
    """
    精排：对融合候选打分重排，返回 top_n（附 rerank_score）。
    三种模式：bm25（Lite）/ rerank_provider=none（用 RRF 融合分）/ local·api（模型打分）。
    字段 rerank_score 在三种模式下语义保持一致，便于前端与引用校验统一处理。
    """
    settings = get_settings()
    top_n = settings.rerank_top_n
    if not candidates:
        return []
    if settings.retrieval_mode == "bm25":
        ranked = sorted(candidates, key=lambda c: c.get("bm25_score", 0.0), reverse=True)
        for c in ranked:
            c["rerank_score"] = c.get("bm25_score", 0.0)
        log.info("retrieval.bm25_rank", top_score=ranked[0]["rerank_score"] if ranked else None)
        return ranked[:top_n]

    if settings.rerank_provider == "none":
        # 无精排：直接用 RRF 融合分排序，分数尺度与精排不同，故另有阈值项
        ranked = sorted(candidates, key=lambda c: c.get("rrf_score", 0.0), reverse=True)
        for c in ranked:
            c["rerank_score"] = float(c.get("rrf_score", 0.0))
        log.info("retrieval.fusion_rank", top_score=ranked[0]["rerank_score"] if ranked else None)
        return ranked[:top_n]

    candidates = candidates[:10]
    scores = rerank_scores(query, [c["text"] for c in candidates])
    for c, s in zip(candidates, scores):
        c["rerank_score"] = s
    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
    top = candidates[:top_n]
    log.info("retrieval.rerank", top_score=top[0]["rerank_score"] if top else None)
    return top


def is_relevant(top: list[dict]) -> bool:
    """
    阈值判定：最高分低于阈值视为知识库未覆盖 → 兜底拒答。
    Lite 模式没有 reranker 的可比分数，BM25 已过滤 0 分项，故非空即视为相关。
    """
    settings = get_settings()
    if settings.retrieval_mode == "bm25":
        return bool(top)
    if settings.rerank_provider == "none":
        # 融合分与精排分数尺度不同，单独配置阈值（默认值未重标定）
        return bool(top) and top[0].get("rrf_score", 0.0) >= settings.rerank_threshold_fusion
    threshold = settings.rerank_threshold
    return bool(top) and top[0]["rerank_score"] >= threshold
