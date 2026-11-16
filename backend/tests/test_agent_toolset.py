"""Agent 工具集单测：商品目录、参数查询、对比、订单、售后、转人工。"""
import pytest
from app.services.agent import tools as agent_tools
from app.services.agent.catalog import get_catalog, reset_catalog
from app.services.agent.tools import (
    _check_order_status_impl,
    _compare_products_impl,
    _escalate_to_human_impl,
    _get_after_sales_policy_impl,
    _get_product_spec_impl,
    make_context,
)

PRODUCTS = [
    {
        "chunk_id": "c1",
        "doc_id": "d1",
        "doc_name": "商品参数表.csv",
        "text": "商品ID: P001\n名称: 星河 X5 智能手机\n品牌: 星河\n价格: 3999\n颜色: 曜石黑\n屏幕尺寸: 6.7英寸\n电池容量: 5000mAh\n重量: 198g",
        "meta": {"product_id": "P001"},
    },
    {
        "chunk_id": "c2",
        "doc_id": "d1",
        "doc_name": "商品参数表.csv",
        "text": "商品ID: P002\n名称: 星河 X5 Pro 智能手机\n品牌: 星河\n价格: 5299\n颜色: 冰川银\n屏幕尺寸: 6.8英寸\n电池容量: 5500mAh\n重量: 205g",
        "meta": {"product_id": "P002"},
    },
    {
        "chunk_id": "c3",
        "doc_id": "d1",
        "doc_name": "商品参数表.csv",
        "text": "商品ID: P003\n名称: 风语者 TWS 无线耳机\n品牌: 风语者\n价格: 599\n颜色: 云雾白\n重量: 45g",
        "meta": {"product_id": "P003"},
    },
]


@pytest.fixture(autouse=True)
def _fresh_catalog():
    reset_catalog()
    get_catalog().rebuild(PRODUCTS)
    yield
    reset_catalog()


@pytest.mark.asyncio
async def test_product_spec_by_name_returns_source_context():
    content, artifact = await _get_product_spec_impl("星河 X5")
    assert "5000mAh" in content
    assert artifact["product_id"] == "P001"
    assert artifact["contexts"][0]["chunk_id"] == "c1"
    assert artifact["contexts"][0]["chunk_type"] == "param"


@pytest.mark.asyncio
async def test_product_spec_prefers_base_model_when_ambiguous():
    _, artifact = await _get_product_spec_impl("星河 X5")
    assert artifact["product_id"] == "P001"


@pytest.mark.asyncio
async def test_product_spec_field_filter():
    content, artifact = await _get_product_spec_impl("P001", ["价格"])
    assert "价格: 3999" in content
    assert "电池容量" not in content
    assert set(artifact["fields"]) == {"价格"}


@pytest.mark.asyncio
async def test_product_spec_not_found_lists_candidates():
    content, artifact = await _get_product_spec_impl("星河 X9")
    assert artifact["error"] == "product_not_found"
    assert "未找到商品" in content


@pytest.mark.asyncio
async def test_compare_products_builds_table():
    content, artifact = await _compare_products_impl(["星河 X5", "星河 X5 Pro"])
    assert "| 价格 |" in content
    assert "3999" in content and "5299" in content
    assert len(artifact["contexts"]) == 2
    assert artifact["products"] == ["星河 X5 智能手机", "星河 X5 Pro 智能手机"]


@pytest.mark.asyncio
async def test_compare_products_requires_two():
    _, artifact = await _compare_products_impl(["星河 X5"])
    assert artifact["error"] == "need_two_products"


@pytest.mark.asyncio
async def test_order_status_masks_phone():
    content, artifact = await _check_order_status_impl("ORD-20260905-0001")
    assert "已签收" in content
    assert "138****5678" in content
    assert "13812345678" not in content
    assert artifact["contexts"][0]["chunk_type"] == "order"


@pytest.mark.asyncio
async def test_order_status_rejects_invalid_id():
    _, artifact = await _check_order_status_impl("'; DROP TABLE orders--")
    assert artifact["error"] == "invalid_order_id"


@pytest.mark.asyncio
async def test_order_status_not_found():
    _, artifact = await _check_order_status_impl("ORD-20990101-9999")
    assert artifact["error"] == "order_not_found"


@pytest.mark.asyncio
async def test_after_sales_prefers_faq_filter(monkeypatch):
    captured = {}

    async def fake_search(query, k, chunk_types=None):
        captured["types"] = chunk_types
        return [
            make_context(
                {
                    "chunk_id": "faq1",
                    "text": "Q：保修期是多久？\nA：整机保修 1 年。",
                    "meta": {"doc_name": "售后FAQ.md", "chunk_type": "faq"},
                },
                "search_knowledge_base",
            )
        ], True

    monkeypatch.setattr(agent_tools, "_search_contexts", fake_search)
    content, artifact = await _get_after_sales_policy_impl("保修期多久")
    assert captured["types"] == {"faq"}
    assert "保修" in content
    assert artifact["contexts"][0]["source_tool"] == "get_after_sales_policy"


@pytest.mark.asyncio
async def test_escalate_to_human_simulated_by_default():
    content, artifact = await _escalate_to_human_impl("用户要求人工", "无法解决")
    assert artifact["ticket"]["ticket_id"].startswith("HD-")
    assert artifact["ticket"]["persisted"] is False
    assert "工单" in content


def test_all_tools_have_descriptions():
    assert len(agent_tools.ALL_TOOLS) == 6
    for item in agent_tools.ALL_TOOLS:
        assert item.description and len(item.description) > 10