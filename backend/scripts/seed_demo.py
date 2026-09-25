"""
E-02 演示数据一键入库。

把 sample_data/demo_catalog/ 下的 3 个文件登记为 Document 并复用正式入库链路
（解析→清洗→分块→BGE 向量化→BM25），保证与前端上传行为一致。

用法：
    python scripts/seed_demo.py            # 追加/覆盖同名演示文档
    python scripts/seed_demo.py --reset    # 先清空 documents/chunks 再灌
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import AsyncSessionLocal, Base, engine  # noqa: E402
from app.db.models import Chunk, Document, gen_uuid  # noqa: E402
from app.services import vector_store  # noqa: E402
from app.services.rag.ingest import UPLOAD_DIR, run_ingest  # noqa: E402
from app.utils.file_utils import stored_name  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "sample_data" / "demo_catalog"
FILES = [
    ("商品参数表.csv", "param"),
    ("商品详情文案.md", "prose"),
    ("售后FAQ.md", "faq"),
]


async def reset_documents() -> None:
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document))).scalars().all()
        for doc in docs:
            vector_store.delete_by_doc(doc.id)
        await db.execute(delete(Chunk))
        await db.execute(delete(Document))
        await db.commit()
    print(f"reset: removed {len(docs)} documents")


async def seed() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for name, doc_type in FILES:
        src = CATALOG_DIR / name
        if not src.exists():
            raise SystemExit(f"missing file: {src}（先运行 scripts/generate_catalog.py）")
        ext = src.suffix.lstrip(".")
        doc_id = gen_uuid()
        stored = stored_name(doc_id, ext)
        shutil.copyfile(src, UPLOAD_DIR / stored)
        async with AsyncSessionLocal() as db:
            db.add(Document(
                id=doc_id,
                orig_name=name,
                filename=stored,
                file_path=stored,
                file_type=ext,
                size=src.stat().st_size,
                doc_type=doc_type,
                status="uploaded",
            ))
            await db.commit()
        print(f"ingest {name} ({doc_type}) ...", end=" ", flush=True)
        await run_ingest(doc_id)
        async with AsyncSessionLocal() as db:
            doc = await db.get(Document, doc_id)
            print(f"{doc.status} chunks={doc.chunk_count}")
            if doc.status != "completed":
                raise SystemExit(f"ingest failed: {doc.error_msg}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="清空 documents/chunks 后重建")
    args = parser.parse_args()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if args.reset:
        await reset_documents()
    await seed()
    await engine.dispose()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
