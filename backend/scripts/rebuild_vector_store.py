"""
向量库重建（运维工具）：MySQL chunks 是 source of truth，Chroma 可随时重建。

适用：Chroma 报 "Error loading hnsw index" / 索引与 chunks 不一致 / 演示前重置。

用法：python scripts/rebuild_vector_store.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import AsyncSessionLocal  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.services import vector_store  # noqa: E402
from app.services.rag.ingest import run_ingest  # noqa: E402
from sqlalchemy import select  # noqa: E402


def reset_chroma() -> None:
    """删除 collection；失败则整目录重建（向量是衍生数据，可安全删除）"""
    import chromadb

    try:
        client = chromadb.PersistentClient(path=str(vector_store.PERSIST_DIR))
        client.delete_collection(vector_store.COLLECTION)
        print("collection deleted")
    except Exception as exc:  # noqa: BLE001
        print(f"delete_collection failed ({exc}); removing persist dir")
        shutil.rmtree(vector_store.PERSIST_DIR, ignore_errors=True)
    vector_store._store = None


async def main() -> None:
    reset_chroma()
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document))).scalars().all()
    for doc in docs:
        print(f"reindex {doc.orig_name} ...", end=" ", flush=True)
        await run_ingest(doc.id)
        print("ok")
    print(f"rebuilt vectors for {len(docs)} documents, count={vector_store.count()}")


if __name__ == "__main__":
    asyncio.run(main())
