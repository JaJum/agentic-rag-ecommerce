"""
Chroma 向量库封装：
内嵌持久化（backend/data/chroma），collection 名 kb。
一致性约定：MySQL chunks 表是 source of truth，Chroma 是可重建的衍生索引；
删除顺序固定：向量 → MySQL 行 → 文件。
Chroma 的 Rust 客户端非线程安全——所有集合操作在锁内串行执行（查询仅 ~20ms，代价可忽略）。
"""
import threading
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

# Chroma 操作全局锁（Rust 绑定非线程安全，压测实测并发崩溃）
_chroma_lock = threading.Lock()

# Chroma 持久化目录（本文件位于 backend/app/services/，parents[2] = backend/）
PERSIST_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"
COLLECTION = "kb_chunks"  # chromadb 要求 collection 名 ≥3 字符

_store = None  # 常驻单例
_SIG_FILE = PERSIST_DIR / ".embedding_signature"  # 建库时使用的 Embedding 标识


def _guard_embedding_change() -> None:
    """
    换 Embedding 模型后，旧向量与查询向量不在同一空间（维度甚至不同），
    查询会直接抛 InvalidDimensionException。这里在启动时对比标识并给出明确提示。
    """
    from app.services.embeddings import embedding_signature

    sig = embedding_signature()
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    old = _SIG_FILE.read_text(encoding="utf-8").strip() if _SIG_FILE.exists() else ""
    if old and old != sig:
        log.warning(
            "vector_store.embedding_changed",
            old=old,
            new=sig,
            hint="Embedding 已变更，请重建向量库：cd backend && python scripts/rebuild_vector_store.py",
        )
    _SIG_FILE.write_text(sig, encoding="utf-8")


def get_vector_store():
    """获取（或首次创建）Chroma 向量库单例（含 Embedding 函数）"""
    global _store
    if _store is None:
        from langchain_chroma import Chroma

        from app.services.embeddings import get_embedding_model

        _guard_embedding_change()
        _store = Chroma(
            collection_name=COLLECTION,
            embedding_function=get_embedding_model(),
            persist_directory=str(PERSIST_DIR),
        )
        log.info("vector_store.ready", dir=str(PERSIST_DIR), collection=COLLECTION)
    return _store


def add_chunks(ids: list[str], texts: list[str], metadatas: list[dict]) -> None:
    """
    写入分块向量（幂等：先删同 id 再写，供 reindex 复用）。
    同步阻塞（内部批量 embedding），调用方用 asyncio.to_thread 包裹。
    """
    with _chroma_lock:
        vs = get_vector_store()
        vs.delete(ids=ids)  # 幂等：覆盖旧向量
        vs.add_texts(texts=texts, metadatas=metadatas, ids=ids)
    log.info("vector_store.added", count=len(ids))


def delete_by_doc(doc_id: str) -> None:
    """按文档删除全部向量（删除文档/重建前调用）"""
    with _chroma_lock:
        get_vector_store().delete(where={"doc_id": doc_id})
    log.info("vector_store.deleted_by_doc", doc_id=doc_id)


def count() -> int:
    """当前向量总数（监控用）"""
    with _chroma_lock:
        return get_vector_store()._collection.count()


def search(query: str, k: int = 5) -> list[tuple[str, float, dict]]:
    """相似度检索（混合检索的向量路）"""
    with _chroma_lock:
        results = get_vector_store().similarity_search_with_relevance_scores(query, k=k)
    return [(d.page_content, float(s), d.metadata) for d, s in results]
