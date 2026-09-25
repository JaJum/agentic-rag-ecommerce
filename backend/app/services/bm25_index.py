"""
BM25 进程内关键词索引（M3）：
jieba 分词（可挂商品自定义词典）+ rank_bm25。
全量重建式维护：启动/每次入库删除后从 chunks 表全量重建（万级规模毫秒~秒级）。
与 Chroma 向量检索在 M4 组成混合检索（RRF）。

Lite 模式（RETRIEVAL_MODE=bm25）下 BM25 是唯一检索路，
因此索引除 (id, text) 外还保留 meta，保证命中后能直接生成带来源的引用。
"""
import re
import threading
from pathlib import Path
from typing import Any

import jieba
from rank_bm25 import BM25Okapi

from app.core.logging import get_logger

log = get_logger(__name__)

# 商品自定义词典（可选，存在则加载，提升品牌/型号分词质量）
_USERDICT = Path(__file__).resolve().parents[2] / "data" / "userdict.txt"
if _USERDICT.exists():
    jieba.load_userdict(str(_USERDICT))

# 词/数字/中文混合 token
_TOKEN = re.compile(r"[\w一-龥]+")
# 简单停用词（常见虚词，避免干扰 BM25 打分）
_STOP = set(
    "的 了 和 是 在 有 我 他 她 它 这 那 些 个 不 都 就 也 与 及 或 把 被 让 给 对 向 "
    "从 到 很 啊 吧 呢 吗 嘛 么 什 怎 什么 怎么 请问 一下 哪里 多少 "
    "多久 多长 多长时间 怎么样 如何 是否 能否 可以 你们 你家 我们 帮我 麻烦 想问 咨询".split()
)

# 中文数字归一（「七天无理由」→「7天无理由」），避免数字写法差异导致 BM25 漏召回
_CN_NUM = str.maketrans("一二三四五六七八九", "123456789")


class Bm25Index:
    """线程安全的 BM25 索引（查询发生在事件循环线程，重建在任务线程）"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._bm25: BM25Okapi | None = None
        # chunk_id -> (原文, 元数据)，Lite 模式单路检索时直接取用
        self._docs: dict[str, tuple[str, dict]] = {}

    def rebuild(self, pairs: list[tuple]) -> None:
        """
        全量重建。
        pairs 兼容两种形态：(chunk_id, text) 或 (chunk_id, text, meta)。
        """
        docs: dict[str, tuple[str, dict]] = {}
        corpus: list[list[str]] = []
        ids: list[str] = []
        for item in pairs:
            cid, text = item[0], item[1]
            meta = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
            ids.append(cid)
            corpus.append(self.tokenize(text))
            docs[cid] = (text, meta)
        with self._lock:
            self._ids = ids
            self._docs = docs
            self._bm25 = BM25Okapi(corpus) if corpus else None
        log.info("bm25.rebuilt", size=len(ids))

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        """返回 [(chunk_id, score)]，过滤 0 分项"""
        with self._lock:
            if self._bm25 is None or not self._ids:
                return []
            scores = self._bm25.get_scores(self.tokenize(query))
        ranked = sorted(zip(self._ids, scores), key=lambda x: x[1], reverse=True)
        return [(cid, float(s)) for cid, s in ranked[:k] if s > 0]

    def get_doc(self, chunk_id: str) -> tuple[str, dict[str, Any]] | None:
        """取 chunk 原文与元数据（Lite 模式拼装检索结果用）"""
        with self._lock:
            return self._docs.get(chunk_id)

    def size(self) -> int:
        """索引文档数"""
        with self._lock:
            return len(self._ids)

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """jieba 分词 + 停用词/纯符号过滤"""
        return [
            t for t in jieba.lcut(text.translate(_CN_NUM))
            if _TOKEN.fullmatch(t) and t not in _STOP
        ]


# 全局单例
bm25_index = Bm25Index()