"""
文档入库链路编排与状态机：
uploaded → parsing → cleaning → chunking → embedding → indexing → completed
任一环节异常 → failed（记录 error_msg，可在界面重试）。
embedding：BGE-M3 批量向量化写入 Chroma；indexing：BM25 全量重建。
"""
import asyncio
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import Chunk, Document
from app.services import bm25_index, vector_store
from app.services.cache import bump_index_version
from app.services.rag.chunking import build_chunks
from app.services.rag.cleaning import clean_text
from app.services.rag.parsing import ParsedFile, parse_file

log = get_logger(__name__)

# 上传文件存储目录（backend/data/uploads）
UPLOAD_DIR = Path(__file__).resolve().parents[3] / "data" / "uploads"


async def run_ingest(doc_id: str) -> None:
    """后台任务入口：跑完整入库链路（单文档失败不影响其它文档）"""
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            log.warning("ingest.doc_missing", doc_id=doc_id)
            return
        try:
            # 1. 解析（同步阻塞解析器放到线程池）
            await _set_stage(session, doc, "parsing", 10)
            parsed: ParsedFile = await asyncio.to_thread(
                parse_file, UPLOAD_DIR / doc.filename, doc.file_type
            )

            # 2. 清洗（仅文本型；表格行已结构化）
            await _set_stage(session, doc, "cleaning", 30)
            if parsed.kind == "text":
                parsed.pages = [(clean_text(t), m) for t, m in parsed.pages]

            # 3. 差异化分块（参数表/FAQ/文案三策略）
            await _set_stage(session, doc, "chunking", 55)
            chunks = build_chunks(parsed, doc.doc_type, doc.file_type)

            # 4. 入库（幂等重建：先删旧分块再插新分块，reindex 复用同一流程）
            await session.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
            session.add_all(
                [
                    Chunk(
                        id=c["id"],
                        doc_id=doc.id,
                        seq=c["seq"],
                        text=c["text"],
                        chunk_type=c["chunk_type"],
                        meta=c["meta"],
                        char_len=c["char_len"],
                    )
                    for c in chunks
                ]
            )
            doc.chunk_count = len(chunks)

            # 5. 向量化：BGE-M3 批量 → Chroma（幂等：先删该文档旧向量再写）
            await _set_stage(session, doc, "embedding", 85)
            if get_settings().vector_enabled:
                ids = [c["id"] for c in chunks]
                texts = [c["text"] for c in chunks]
                metadatas = [_flat_meta(doc, c) for c in chunks]
                await asyncio.to_thread(vector_store.delete_by_doc, doc.id)
                await asyncio.to_thread(vector_store.add_chunks, ids, texts, metadatas)
            else:
                # Lite 模式：不写向量库，BM25 单路检索（chunks 表仍是 source of truth）
                log.info("ingest.embedding_skipped", doc_id=doc.id)

            # 6. 索引：BM25 全量重建（source of truth = MySQL chunks 表）
            await _set_stage(session, doc, "indexing", 95)
            await _rebuild_bm25(session)

            await _set_stage(session, doc, "completed", 100)
            bump_index_version()  # 索引变化 → 问答缓存 key 失效（M5）
            # 参数块变化 → 刷新 Agent 商品目录（失败不影响入库结果）
            try:
                from app.services.agent.catalog import refresh_catalog

                await refresh_catalog()
            except Exception as exc:  # noqa: BLE001
                log.warning("ingest.catalog_refresh_failed", error=str(exc))
            log.info("ingest.completed", doc_id=doc.id, chunks=len(chunks))
        except Exception as exc:  # noqa: BLE001 —— 兜底转 failed 状态
            await session.rollback()
            await _mark_failed(session, doc, str(exc)[:500])
            log.error("ingest.failed", doc_id=doc.id, error=str(exc))


async def _set_stage(session, doc: Document, status: str, progress: int) -> None:
    """推进状态机并落库（前端轮询读取）"""
    doc.status = status
    doc.progress = progress
    await session.commit()


async def _rebuild_bm25(session) -> None:
    """从 chunks 表全量重建 BM25（带 meta，Lite 模式单路检索可直接出引用）"""
    rows = (await session.execute(
        select(Chunk.id, Chunk.text, Chunk.chunk_type, Chunk.doc_id, Chunk.meta, Document.orig_name)
        .join(Document, Chunk.doc_id == Document.id)
    )).all()
    pairs = [
        (
            r.id,
            r.text,
            {
                "chunk_id": r.id,
                "doc_id": r.doc_id,
                "doc_name": r.orig_name,
                "chunk_type": r.chunk_type,
                **(r.meta or {}),
            },
        )
        for r in rows
    ]
    await asyncio.to_thread(bm25_index.bm25_index.rebuild, pairs)


def _flat_meta(doc: Document, chunk: dict) -> dict:
    """
    组装 Chroma 元数据：doc_id/doc_name/chunk_type + 分块元数据。
    Chroma 仅支持标量，过滤 None 值。
    """
    meta = {
        "chunk_id": chunk["id"],       # 供混合检索 RRF 融合定位
        "doc_id": doc.id,
        "doc_name": doc.orig_name,
        "chunk_type": chunk["chunk_type"],
    }
    for k, v in (chunk.get("meta") or {}).items():
        if v is not None:
            meta[k] = v
    return meta


async def _mark_failed(session, doc: Document, error_msg: str) -> None:
    """标记失败（可重试：reindex 会重跑链路）"""
    doc.status = "failed"
    doc.error_msg = error_msg
    await session.commit()
