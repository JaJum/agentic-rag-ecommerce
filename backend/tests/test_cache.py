"""问答缓存 key 单测（A-20）：历史指纹 / 索引版本 / 归一化。"""
from app.services.cache import bump_index_version, qa_cache_key


def test_same_query_same_history_hits_same_key():
    h = [{"role": "user", "content": "星河 X5 多少钱"}]
    assert qa_cache_key("它电池多大", h) == qa_cache_key(" 它电池多大 ", h)


def test_history_changes_key():
    h1 = [{"role": "user", "content": "星河 X5 多少钱"}]
    h2 = [{"role": "user", "content": "X5 Pro 多少钱"}]
    assert qa_cache_key("它电池多大", h1) != qa_cache_key("它电池多大", h2)
    assert qa_cache_key("它电池多大") != qa_cache_key("它电池多大", h1)


def test_whitespace_and_case_normalized():
    assert qa_cache_key("iPhone 16 Pro") == qa_cache_key("iphone16pro")


def test_index_version_invalidates_key():
    before = qa_cache_key("星河 X5 多少钱")
    bump_index_version()
    after = qa_cache_key("星河 X5 多少钱")
    assert before != after
