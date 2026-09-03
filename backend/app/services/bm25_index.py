"""
BM25 进程内关键词索引（M3）：
jieba 分词（可挂商品自定义词典）+ rank_bm25。
全量重建式维护：启动/每次入库删除后从 MySQL chunks 全量重建（万级规模毫秒~秒级）。
与 Chroma 向量检索在 M4 组成混合检索（EnsembleRetriever/RRF）。
"""
import re
import threading
from pathlib import Path

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
    "从 到 很 啊 吧 呢 吗 嘛 么 什 怎 什么 怎么 请问 一下 哪里 多少".split()
)


class Bm25Index:
    """线程安全的 BM25 索引（查询发生在事件循环线程，重建在任务线程）"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._bm25: BM25Okapi | None = None

    def rebuild(self, pairs: list[tuple[str, str]]) -> None:
        """全量重建：pairs = [(chunk_id, text), ...]"""
        corpus = [self._tokenize(text) for _, text in pairs]
        with self._lock:
            self._ids = [cid for cid, _ in pairs]
            self._bm25 = BM25Okapi(corpus) if corpus else None
        log.info("bm25.rebuilt", size=len(pairs))

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        """返回 [(chunk_id, score)]，过滤 0 分项"""
        with self._lock:
            if self._bm25 is None or not self._ids:
                return []
            scores = self._bm25.get_scores(self._tokenize(query))
        ranked = sorted(zip(self._ids, scores), key=lambda x: x[1], reverse=True)
        return [(cid, float(s)) for cid, s in ranked[:k] if s > 0]

    def size(self) -> int:
        """索引文档数"""
        with self._lock:
            return len(self._ids)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """jieba 分词 + 停用词/纯符号过滤"""
        return [
            t for t in jieba.lcut(text)
            if _TOKEN.fullmatch(t) and t not in _STOP
        ]


# 全局单例
bm25_index = Bm25Index()
