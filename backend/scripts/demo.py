"""
Lite 模式一键演示。

无需 MySQL / GPU / API Key：
- SQLite 本地库（backend/data/demo.db，每次重建，保证可复现）
- BM25 单路检索（不加载 BGE-M3 / reranker）
- 确定性 Mock LLM（固定工具调用与引用）

用法：
    cd backend
    python scripts/demo.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DEMO_DB = BACKEND / "data" / "demo.db"
CATALOG_DIR = ROOT / "sample_data" / "demo_catalog"

# 必须在导入 app.* 之前设置：Settings 在模块导入时实例化
if DEMO_DB.exists():
    DEMO_DB.unlink()
DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DEMO_DB.as_posix()}"
os.environ["RETRIEVAL_MODE"] = "bm25"
os.environ["EMBEDDING_PROVIDER"] = "none"
os.environ["MOCK_LLM"] = "true"
os.environ["AGENT_ENABLED"] = "true"
os.environ.setdefault("SECRET_KEY", "demo-only-secret")

sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.config import get_settings  # noqa: E402
from app.db.base import AsyncSessionLocal, Base, engine  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.db.seed import seed_admin  # noqa: E402
from app.services.agent.catalog import refresh_catalog  # noqa: E402
from app.services.agent.runner import run_agent_stream  # noqa: E402
from app.services.bm25_index import bm25_index  # noqa: E402
from app.services.rag.ingest import UPLOAD_DIR, run_ingest  # noqa: E402

DEMO_QUESTIONS = [
    ("闲聊", "你好，你能做什么？"),
    ("单跳知识", "风语者 Air Pro 的续航时间是多少？"),
    ("多跳对比", "帮我比较一下星河 X5 和轻羽 14 的差别"),
    ("业务办理", "ORD-20260905-0001 的物流到哪了？"),
    ("售后政策", "支持七天无理由退货吗？"),
    ("库外拒答", "小米14 的电池容量是多少？"),
]


async def init_db() -> None:
    """建表 + 管理员种子"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_admin()


async def load_documents() -> int:
    """把 sample_data/demo_catalog 下的文件走一遍真实入库链路（分块 → chunks → BM25）"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in sorted(CATALOG_DIR.glob("*")):
        if src.suffix.lower() not in {".md", ".csv"}:
            continue
        doc_id = str(uuid.uuid4())
        stored = f"{doc_id}{src.suffix}"
        shutil.copyfile(src, UPLOAD_DIR / stored)
        async with AsyncSessionLocal() as session:
            session.add(
                Document(
                    id=doc_id,
                    filename=stored,
                    orig_name=src.name,
                    file_path=str(Path("data") / "uploads" / stored),
                    file_type=src.suffix.lstrip("."),
                    size=src.stat().st_size,
                    doc_type="auto",
                    status="uploaded",
                )
            )
            await session.commit()
        await run_ingest(doc_id)
        count += 1
    return count


async def ask(label: str, question: str) -> None:
    """跑一条问答并打印路由 / 工具轨迹 / 引用 / 答案"""
    done: dict = {}
    async for event in run_agent_stream(question):
        if event.get("event") == "done":
            done = event["data"]
    tools = ", ".join(e.get("tool", "?") for e in done.get("tool_events") or []) or "-"
    print(f"\n[{label}] {question}")
    print(f"  route={done.get('route')} status={done.get('status')} "
          f"steps={done.get('steps')} latency={done.get('latency_ms')}ms")
    print(f"  tools={tools} cited={done.get('cited')}")
    print(f"  answer={done.get('answer')}")


async def main() -> None:
    settings = get_settings()
    print("=" * 72)
    print("Agentic RAG Lite 演示（SQLite + BM25 + Mock LLM，无外部依赖）")
    print(f"DATABASE_URL={settings.database_url}")
    print(f"retrieval_mode={settings.retrieval_mode} mock_llm={settings.mock_llm}")
    print("=" * 72)

    await init_db()
    docs = await load_documents()
    await refresh_catalog()
    print(f"\n已入库 {docs} 个文件，BM25 索引 {bm25_index.size()} 个 chunk")

    for label, question in DEMO_QUESTIONS:
        await ask(label, question)

    print("\n" + "=" * 72)
    print(f"演示完成：{len(DEMO_QUESTIONS)} 条用例，数据库 {DEMO_DB}")
    print("=" * 72)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())