"""分块策略单元测试（三类差异化分块）"""
from app.services.rag.chunking import (
    build_chunks,
    detect_type,
    split_faq,
    split_md_param_tables,
    split_param_rows,
    split_prose_text,
)
from app.services.rag.parsing import ParsedFile


def test_param_rows_one_chunk_per_product():
    """参数表：1 商品 = 1 chunk，序列化为「字段: 值」"""
    rows = [
        {"商品ID": "P001", "名称": "星河 X5", "价格": "3999"},
        {"商品ID": "P002", "名称": "星河 X5 Pro", "价格": "5299"},
    ]
    chunks = split_param_rows(rows)
    assert len(chunks) == 2
    assert chunks[0]["chunk_type"] == "param"
    assert "商品ID: P001" in chunks[0]["text"]
    assert "价格: 3999" in chunks[0]["text"]
    assert chunks[0]["meta"]["product_id"] == "P001"


def test_faq_pairs_bound_together():
    """FAQ：问答对绑定为 1 chunk（问题与答案不分离）"""
    text = "Q：退货谁承担运费？\nA：买家承担。\nQ：保修多久？\nA：整机一年。"
    chunks = split_faq(text)
    assert len(chunks) == 2
    # 问题和答案必须在同一块
    assert "退货谁承担运费" in chunks[0]["text"]
    assert "买家承担" in chunks[0]["text"]
    assert chunks[0]["chunk_type"] == "faq"


def test_prose_split_with_section_meta():
    """文案：按标题分节，meta 带标题面包屑，块大小 ≤ 512+overlap"""
    text = "# 商品详情\n## 外观\n" + "屏幕很好。" * 200 + "\n## 续航\n" + "电池很大。" * 200
    chunks = split_prose_text(text)
    assert len(chunks) >= 2
    assert any("外观" in (c["meta"].get("section") or "") for c in chunks)
    assert all(len(c["text"]) <= 512 + 64 + 20 for c in chunks)  # 上限含重叠余量


def test_md_param_table():
    """Markdown 表格：表头+数据行 → 键值 chunk"""
    text = "| 商品ID | 名称 |\n|---|---|\n| P001 | 星河 X5 |\n| P002 | 星河 X5 Pro |"
    chunks = split_md_param_tables(text)
    assert len(chunks) == 2
    assert "商品ID: P001" in chunks[0]["text"]


def test_detect_type():
    """auto 识别：表格文件→param；问答多→faq；其余→prose"""
    assert detect_type("任意", "csv") == "param"
    assert detect_type("Q：a\nA：b\nQ：c\nA：d\nQ：e\nA：f", "md") == "faq"
    assert detect_type("这是一段普通商品介绍文案。", "md") == "prose"


def test_build_chunks_assigns_ids_and_seq():
    """build_chunks 统一补全 id/seq/char_len"""
    parsed = ParsedFile(kind="table", rows=[{"商品ID": "P001", "名称": "测试"}])
    chunks = build_chunks(parsed, "auto", "csv")
    assert chunks[0]["seq"] == 0
    assert len(chunks[0]["id"]) == 36  # uuid
    assert chunks[0]["char_len"] == len(chunks[0]["text"])
