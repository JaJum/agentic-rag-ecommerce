"""
E-04 Agent 评测脚本。

指标：
- route_accuracy       路由准确率（规则+LLM 兜底）
- tool_selection       期望工具全部被调用（子集匹配）
- task_completion      路由 + 工具 + 关键词 + 拒答/禁用词 全部满足
- refusal_accuracy     库外问题正确拒答率
- avg_steps / P50 / P95 延迟

用法（backend/ 下）：
    python scripts/eval_agent.py                    # 全量 37 条
    python scripts/eval_agent.py --limit 10         # 冒烟
    python scripts/eval_agent.py --out ../docs/09-Agent评测报告.md
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import embeddings, reranker  # noqa: E402
from app.services.agent.runner import run_agent_stream  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "sample_data" / "agent_cases.jsonl"
CATALOG_CSV = ROOT / "sample_data" / "demo_catalog" / "商品参数表.csv"

REFUSAL_MARKERS = ["未找到", "无法", "不能", "抱歉", "不支持", "没有相关", "不提供"]
ROUTE_LABEL = {
    "chitchat": "闲聊", "kb_simple": "单跳知识", "business": "业务办理", "multi_hop": "多跳对比",
}


def load_cases(limit: int | None = None, types: set[str] | None = None) -> list[dict]:
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if types:
        cases = [c for c in cases if c["type"] in types]
    if limit:
        cases = cases[:limit]
    return cases


def dataset_version(cases: list[dict]) -> str:
    raw = json.dumps(cases, ensure_ascii=False, sort_keys=True).encode("utf-8")
    product_count = max(0, len(CATALOG_CSV.read_text(encoding="utf-8-sig").splitlines()) - 1)
    return f"cases-{len(cases)}/products-{product_count}/sha-{hashlib.sha256(raw).hexdigest()[:8]}"


def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()


def is_refusal(answer: str) -> bool:
    return any(m in (answer or "") for m in REFUSAL_MARKERS)


def evaluate_case(case: dict, events: list[dict]) -> dict:
    done = next((e["data"] for e in reversed(events) if e["event"] == "done"), {})
    tools_used = [e["data"].get("tool") for e in events if e["event"] == "tool_call"]
    answer = done.get("answer") or ""
    route = done.get("route")
    status = done.get("status")

    route_ok = route == case["route"]
    tools_ok = all(t in tools_used for t in case.get("tools", []))
    keyword_ok = all(_norm(k) in _norm(answer) for k in case.get("keywords", []))
    refused = status == "fallback" or is_refusal(answer)
    refusal_ok = refused if case.get("refusal") else not any(
        m in answer for m in case.get("must_not_contain", [])
    )
    forbidden_ok = not any(m in answer for m in case.get("must_not_contain", []))
    completion = route_ok and tools_ok and keyword_ok and refusal_ok and forbidden_ok

    return {
        "id": case["id"],
        "type": case["type"],
        "query": case["query"],
        "route": route,
        "expected_route": case["route"],
        "route_ok": route_ok,
        "tools_used": tools_used,
        "expected_tools": case.get("tools", []),
        "tools_ok": tools_ok,
        "keyword_ok": keyword_ok,
        "refused": refused,
        "refusal_ok": refusal_ok,
        "forbidden_ok": forbidden_ok,
        "completion": completion,
        "status": status,
        "steps": done.get("steps", 0),
        "latency_ms": done.get("latency_ms", 0),
        "answer": answer,
    }


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_report(results: list[dict], version: str, elapsed_s: float) -> str:
    n = len(results)
    route_acc = sum(r["route_ok"] for r in results) / n
    tool_acc = sum(r["tools_ok"] for r in results) / n
    task_acc = sum(r["completion"] for r in results) / n
    refusal_cases = [r for r in results if r["type"] == "refusal"]
    refusal_acc = (
        sum(r["refused"] for r in refusal_cases) / len(refusal_cases) if refusal_cases else 0
    )
    latencies = [r["latency_ms"] for r in results if r["latency_ms"]]
    p50 = int(statistics.median(latencies)) if latencies else 0
    p95 = int(sorted(latencies)[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))]) if latencies else 0
    avg_steps = statistics.mean([r["steps"] for r in results]) if results else 0

    by_type: dict[str, list[dict]] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)

    lines = [
        "# Agent 评测报告",
        "",
        f"- 数据集版本：`{version}`",
        f"- 评测时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 样本数：{n} 条；总耗时：{elapsed_s:.0f}s",
        "",
        "## 1. 总体指标",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 路由准确率 | {pct(route_acc)} |",
        f"| 工具选择准确率 | {pct(tool_acc)} |",
        f"| 任务完成率 | {pct(task_acc)} |",
        f"| 库外拒答正确率 | {pct(refusal_acc)}（{len(refusal_cases)} 条） |",
        f"| 平均工具步数 | {avg_steps:.2f} |",
        f"| P50 延迟 | {p50} ms |",
        f"| P95 延迟 | {p95} ms |",
        "",
        "## 2. 分类型指标",
        "",
        "| 类型 | 样本 | 路由准确 | 工具准确 | 任务完成 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for t, rows in by_type.items():
        lines.append(
            f"| {t} | {len(rows)} | {pct(sum(r['route_ok'] for r in rows) / len(rows))} "
            f"| {pct(sum(r['tools_ok'] for r in rows) / len(rows))} "
            f"| {pct(sum(r['completion'] for r in rows) / len(rows))} |"
        )

    lines += ["", "## 3. 失败案例", ""]
    failures = [r for r in results if not r["completion"]]
    if not failures:
        lines.append("无。")
    else:
        lines += [
            "| ID | 问题 | 期望路由 | 实际路由 | 期望工具 | 实际工具 | 原因 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in failures:
            reasons = []
            if not r["route_ok"]:
                reasons.append("路由")
            if not r["tools_ok"]:
                reasons.append("工具")
            if not r["keyword_ok"]:
                reasons.append("关键词")
            if not r["refusal_ok"]:
                reasons.append("拒答")
            if not r["forbidden_ok"]:
                reasons.append("禁用词")
            lines.append(
                f"| {r['id']} | {r['query'][:24]} | {ROUTE_LABEL.get(r['expected_route'], r['expected_route'])} "
                f"| {ROUTE_LABEL.get(r['route'], r['route'])} | {','.join(r['expected_tools']) or '-'} "
                f"| {','.join(t for t in r['tools_used'] if t) or '-'} | {'/'.join(reasons)} |"
            )

    lines += [
        "", "## 4. 说明与局限", "",
        "- 数据：`sample_data/demo_catalog`（72 商品）+ `sample_data/agent_cases.jsonl`",
        "- 复现：`cd backend && python scripts/eval_agent.py`",
        "- 局限 1：评测集为自建且规模有限（44 条），路由规则在评测迭代中修复过，存在过拟合风险",
        "- 局限 2：任务完成采用关键词/路由/工具子集匹配，非人工逐条评分",
        "- 局限 3：单一模型（qwen3.8-flash）、单次运行，未做多模型对比与方差统计",
        "",
    ]
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--types", default=None, help="逗号分隔：kb_simple,multi_hop,business,refusal,injection,chitchat")
    parser.add_argument("--out", default=str(ROOT / "docs" / "09-Agent评测报告.md"))
    args = parser.parse_args()

    types = set(args.types.split(",")) if args.types else None
    cases = load_cases(args.limit, types)
    version = dataset_version(cases)

    # 预热：BGE + reranker（首条用例不计入冷启动）
    await asyncio.to_thread(embeddings.get_embedding_model)
    await asyncio.to_thread(reranker.get_reranker)

    results: list[dict] = []
    started = time.perf_counter()
    for case in cases:
        events = [ev async for ev in run_agent_stream(case["query"], case.get("history"))]
        result = evaluate_case(case, events)
        results.append(result)
        mark = "OK " if result["completion"] else "FAIL"
        print(f"[{mark}] {result['id']} route={result['route']} tools={result['tools_used']} "
              f"{result['latency_ms']}ms", flush=True)

    elapsed = time.perf_counter() - started
    report = render_report(results, version, elapsed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    (out.parent / "agent_eval_results.json").write_text(
        json.dumps({"version": version, "elapsed_s": round(elapsed, 1), "results": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nreport -> {out}")
    n = len(results)
    print(f"route={sum(r['route_ok'] for r in results)}/{n} "
          f"tool={sum(r['tools_ok'] for r in results)}/{n} "
          f"task={sum(r['completion'] for r in results)}/{n}")


if __name__ == "__main__":
    asyncio.run(main())
