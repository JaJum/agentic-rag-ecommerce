"""Provider 可插拔测试：Embedding(local/api)、Rerank(local/api/none) 的分发与阈值。"""
import httpx
from app.core.config import get_settings
from app.services import embeddings, reranker
from app.services.rag import retrieval


def test_embedding_api_provider_builds_openai_client(monkeypatch):
    """provider=api 时构造 OpenAIEmbeddings，且必须关闭 tiktoken 切分（非 OpenAI 服务不接受 token 数组）"""
    from langchain_openai import OpenAIEmbeddings

    s = get_settings()
    monkeypatch.setattr(s, "embedding_provider", "api")
    monkeypatch.setattr(s, "embedding_api_model", "text-embedding-3-small")
    monkeypatch.setattr(s, "embedding_api_key", "sk-test")
    monkeypatch.setattr(s, "embedding_api_base", "")
    embeddings.reset_model()
    try:
        model = embeddings.get_embedding_model()
        assert isinstance(model, OpenAIEmbeddings)
        assert model.model == "text-embedding-3-small"
        assert model.check_embedding_ctx_length is False
        assert s.llm_base_url.rstrip("/") in model.openai_api_base
    finally:
        embeddings.reset_model()


def test_embedding_signature_tracks_provider(monkeypatch):
    """向量库守卫依赖签名：provider/模型一变，签名就要变"""
    s = get_settings()
    monkeypatch.setattr(s, "embedding_provider", "local")
    monkeypatch.setattr(s, "embedding_model", "BAAI/bge-m3")
    assert embeddings.embedding_signature() == "local:BAAI/bge-m3"

    monkeypatch.setattr(s, "embedding_provider", "api")
    monkeypatch.setattr(s, "embedding_api_model", "text-embedding-3-small")
    assert embeddings.embedding_signature() == "api:text-embedding-3-small"

    monkeypatch.setattr(s, "embedding_provider", "none")
    assert embeddings.embedding_signature() == "none"


def test_rerank_none_uses_fusion_score_and_threshold(monkeypatch):
    """provider=none：跳过模型按 RRF 排序，并用融合阈值判定相关性，不套用精排分数尺度"""
    s = get_settings()
    monkeypatch.setattr(s, "retrieval_mode", "hybrid")
    monkeypatch.setattr(s, "rerank_provider", "none")
    monkeypatch.setattr(s, "rerank_top_n", 2)
    monkeypatch.setattr(s, "rerank_threshold_fusion", 0.02)

    cands = [
        {"chunk_id": "a", "text": "A", "rrf_score": 0.01},
        {"chunk_id": "b", "text": "B", "rrf_score": 0.03},
    ]
    top = retrieval.rerank_top("q", cands)
    assert [c["chunk_id"] for c in top] == ["b", "a"]
    assert top[0]["rerank_score"] == 0.03
    assert retrieval.is_relevant(top) is True
    assert retrieval.is_relevant([{"chunk_id": "a", "rrf_score": 0.01}]) is False


def test_rerank_api_parses_results(monkeypatch):
    """provider=api：按通用 /rerank 协议把 results[index] 映射回原顺序"""
    s = get_settings()
    monkeypatch.setattr(s, "rerank_provider", "api")
    monkeypatch.setattr(s, "rerank_api_base", "https://example.com/v1")
    monkeypatch.setattr(s, "rerank_api_key", "sk-test")
    monkeypatch.setattr(s, "rerank_api_model", "bge-reranker")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
            ]}

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    scores = reranker.rerank("q", ["a", "b"])
    assert scores == [0.1, 0.9]
    assert captured["url"] == "https://example.com/v1/rerank"
    assert captured["body"]["documents"] == ["a", "b"]
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
