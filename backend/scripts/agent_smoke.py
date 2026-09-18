"""Agent 冒烟测试：预加载模型后跑一条问题，打印路由/工具/引用/答案。

用法（backend 目录）：
    python scripts/agent_smoke.py "对比星河 X5 和星河 X5 Pro 的价格"
"""
import asyncio
import sys
from pathlib import Path

# 允许直接 `python scripts/agent_smoke.py` 运行（把 backend/ 加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import engine
from app.services import embeddings, reranker


async def main(query: str) -> None:
    try:
        await asyncio.to_thread(embeddings.get_embedding_model)
        await asyncio.to_thread(reranker.get_reranker)
        from app.services.agent.runner import run_agent_stream

        events = []
        async for event in run_agent_stream(query):
            events.append(event)
        done = events[-1]["data"]
        print("ROUTE  :", done.get("route"))
        print("STATUS :", done.get("status"), "| steps:", done.get("steps"))
        tools = [
            (e["data"].get("tool"), e["data"].get("ok"))
            for e in events
            if e.get("event") == "tool_result"
        ]
        print("TOOLS  :", tools)
        print("CONTEXT:", len(done.get("contexts") or []), "| cited:", done.get("cited"))
        print("ANSWER :", (done.get("answer") or "").replace("\n", " ")[:300])
        print("EVENTS :", [e.get("event") for e in events])
    finally:
        await engine.dispose()


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "星河 X5 的电池容量是多少"
    asyncio.run(main(q))