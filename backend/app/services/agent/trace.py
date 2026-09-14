"""
Agent 执行轨迹工具（M8）：
- 参数/结果预览截断，避免上下文与日志膨胀
- 手机号 / 邮箱 / 身份证 / 订单号脱敏
- 轻量计时器，供 agent_steps 落库与 SSE 展示
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

# 11 位手机号：保留前 3 后 4
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
# 邮箱：保留前 3 位与域名
_EMAIL = re.compile(r"([\w.+-]{1,3})[\w.+-]*@([\w.-]+\.[A-Za-z]{2,})")
# 身份证：18 位，保留前 6 后 4
_ID_CARD = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")
# 订单号：形如 ORD-20261110-0001，保留前缀与末 2 位
_ORDER = re.compile(r"\b([A-Z]{2,4}-\d{4,10}-)\d*(\d{2})\b")


def mask_sensitive(text: str) -> str:
    """对常见 PII 做打码；用于 Trace 面板与日志，不改变业务数据"""
    if not text:
        return ""
    text = _PHONE.sub(r"\1****\2", text)
    text = _EMAIL.sub(r"\1***@\2", text)
    text = _ID_CARD.sub(r"\1********\2", text)
    text = _ORDER.sub(r"\1****\2", text)
    return text


def preview(value: Any, limit: int = 300) -> str:
    """把任意值转成单行可读预览并截断（默认 300 字）"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    text = mask_sensitive(" ".join(text.split()))
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


class Timer:
    """上下文计时器：with Timer() as t: ...; t.elapsed_ms"""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        self.elapsed_ms = 0
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)


@dataclass
class StepRecord:
    """单步轨迹记录（对应 agent_steps 一行 / SSE step 事件）"""

    step_no: int
    node: str
    status: str = "ok"
    tool: str = ""
    args_preview: str = ""
    result_preview: str = ""
    latency_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_event(self) -> dict[str, Any]:
        """转为 SSE/JSON 可序列化字典"""
        data: dict[str, Any] = {
            "step_no": self.step_no,
            "node": self.node,
            "status": self.status,
            "tool": self.tool,
            "latency_ms": self.latency_ms,
        }
        if self.args_preview:
            data["args_preview"] = self.args_preview
        if self.result_preview:
            data["result_preview"] = self.result_preview
        if self.extra:
            data.update(self.extra)
        return data