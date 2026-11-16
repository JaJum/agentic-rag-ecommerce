"""引用解析单元测试（[n] 校验与归一化）"""
from app.services.rag.generation import build_context_block, extract_citations


def test_extract_single_citation():
    assert extract_citations("这款手机电池为 5000mAh [1]。", 5) == [1]


def test_extract_multiple_forms():
    """[1][2] 与 [1,2] 归一化为升序去重列表"""
    assert extract_citations("支持快充 [1][2] 和无线充 [2,3]。", 5) == [1, 2, 3]
    assert extract_citations("价格见 [3，1]。", 5) == [1, 3]


def test_extract_out_of_range_dropped():
    """越界编号剔除（LLM 防御性校验）"""
    assert extract_citations("编造的引用 [9] 和有效的 [2]。", 5) == [2]
    assert extract_citations("编号 [0] 也不合法。", 5) == []


def test_extract_no_citation():
    assert extract_citations("没有引用的回答。", 5) == []


def test_build_context_block_numbering():
    """<资料> 块编号与引用映射一一对应"""
    contexts = [
        {"text": "块A", "meta": {"doc_name": "a.md", "section": "S1"}},
        {"text": "块B", "meta": {"doc_name": "b.csv", "product_id": "P001"}},
    ]
    block = build_context_block(contexts)
    assert block.startswith("<资料>")
    assert block.endswith("</资料>")
    assert "[1] 来源：a.md（S1）" in block
    assert "[2] 来源：b.csv（P001）" in block
