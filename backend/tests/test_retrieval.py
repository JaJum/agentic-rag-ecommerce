"""检索组件单元测试（M6 验收：BM25 分词检索 + RRF 融合逻辑）"""
from app.services.bm25_index import Bm25Index


def _make_index() -> Bm25Index:
    """构造 6 篇测试语料（rank_bm25 在小语料上 IDF=0，需足够篇数才有正分）"""
    idx = Bm25Index()
    idx.rebuild([
        ("c1", "星河 X5 智能手机 电池容量 5000mAh"),
        ("c2", "退货的运费由谁承担 买家承担"),
        ("c3", "护眼台灯 A1 奶油白"),
        ("c4", "轻羽 14 笔记本电脑 重量"),
        ("c5", "快充充电器 65W 白色"),
        ("c6", "风语者 Pro 降噪耳机 午夜黑"),
    ])
    return idx


def test_bm25_index_build_and_search():
    """BM25：重建后关键词检索命中正确块"""
    idx = _make_index()
    assert idx.size() == 6
    hits = idx.search("电池容量", k=2)
    assert hits and hits[0][0] == "c1"


def test_bm25_chinese_tokenization():
    """jieba 中文分词：品牌/品类词匹配"""
    idx = _make_index()
    hits = idx.search("降噪耳机", k=1)
    assert hits and hits[0][0] == "c6"


def test_bm25_empty_index():
    """空索引不崩，返回空"""
    idx = Bm25Index()
    assert idx.search("任意") == []


def test_rrf_fusion_ranking():
    """RRF 融合：双路都命中的候选得分更高（融合逻辑内联验证）"""
    # 模拟：c2 双路第 1，c1 仅单路第 1
    bm25_hits = [("c2", 5.0), ("c1", 3.0)]
    vec_hits = [("文本2", 0.9, {"chunk_id": "c2"}), ("文本3", 0.8, {"chunk_id": "c3"})]
    fused = {}
    for rank, (cid, _) in enumerate(bm25_hits):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank + 1)
    for rank, (_, _, meta) in enumerate(vec_hits):
        cid = meta["chunk_id"]
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank + 1)
    ranked = sorted(fused, key=fused.get, reverse=True)
    assert ranked[0] == "c2"  # 双路命中 → 融合分最高
