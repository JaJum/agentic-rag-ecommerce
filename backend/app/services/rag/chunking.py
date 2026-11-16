"""
差异化分块（入库链路第 3 步，核心设计）：
- 参数表（csv/xlsx/md 表格）：1 商品 = 1 chunk，行序列化为「字段: 值」，语义完整
- FAQ：问答对绑定为 1 chunk，防止答案与问题分离
- 详情文案：按 Markdown 标题分节 + 递归切分（512/64）
分块元数据（chunk_type/section/row/product_id）供检索过滤与引用展示。
"""
import re
import uuid as uuid_mod

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.services.rag.parsing import ParsedFile

# 分块参数
PROSE_SIZE, PROSE_OVERLAP = 512, 64   # 文案：块大小 / 重叠
FAQ_SIZE = 300                        # FAQ：单对上限
PARAM_MAX = 1500                      # 参数表单块上限（超长行二次切）

# Markdown 标题层级 → 元数据键
_MD_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]
# FAQ 问题行开头：Q:/问：/**问**
_FAQ_Q = re.compile(
    r"^\s*(?:Q\s*[:：]|问\s*[:：]|\*\*问\*\*\s*[:：]?)\s*", re.MULTILINE
)


def build_chunks(parsed: ParsedFile, doc_type: str, file_type: str) -> list[dict]:
    """
    按内容类型分发分块策略（doc_type=auto 时自动识别）。
    返回 chunk 字典列表：{id, seq, text, chunk_type, meta, char_len}
    """
    if parsed.kind == "table":
        raw = split_param_rows(parsed.rows)
    else:
        full_text = "\n\n".join(t for t, _ in parsed.pages)
        effective = doc_type if doc_type != "auto" else detect_type(full_text, file_type)
        if effective == "param":
            raw = split_md_param_tables(full_text) or split_prose(parsed)
        elif effective == "faq":
            raw = split_faq(full_text)
        else:
            raw = split_prose(parsed)

    # 统一编号与字段补全（seq 供引用与预览排序）
    for i, c in enumerate(raw):
        c["id"] = str(uuid_mod.uuid4())  # uuid 同时作为 Chroma 向量 id
        c["seq"] = i
        c["char_len"] = len(c["text"])
        c.setdefault("meta", {})
    return raw


def detect_type(text: str, file_type: str) -> str:
    """auto 模式识别：表格文件→param；问答行≥3→faq；其余→prose"""
    if file_type in ("csv", "xlsx"):
        return "param"
    if len(_FAQ_Q.findall(text)) >= 3:
        return "faq"
    return "prose"


# ---------------- 参数表：1 商品 = 1 chunk ----------------

def split_param_rows(rows: list[dict[str, str]]) -> list[dict]:
    """CSV/XLSX：每行商品序列化为「字段: 值」文本（比原始表格行更利于语义检索）"""
    chunks = []
    for i, row in enumerate(rows):
        lines = [f"{k}: {v}" for k, v in row.items() if v and str(v).strip()]
        if not lines:
            continue
        text = "\n".join(lines)
        product_id = (
            row.get("商品ID") or row.get("product_id") or row.get("SKU") or ""
        )
        chunks.append(
            {
                "text": text,
                "chunk_type": "param",
                "meta": {"row": i, "product_id": product_id},
            }
        )
    return _split_oversize(chunks)


def split_md_param_tables(text: str) -> list[dict]:
    """Markdown 表格：表头 + 每数据行 → 与 CSV 同构的键值 chunk"""
    chunks = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].strip().startswith("|"):
            i += 1
            continue
        # 收集连续的表格行块
        block = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            block.append(lines[i])
            i += 1
        chunks.extend(_md_block_to_rows(block))
    return _split_oversize(chunks)


def _md_block_to_rows(block: list[str]) -> list[dict]:
    """把一个 Markdown 表格块拆成逐行键值 chunk（跳过表头与分隔行）"""

    def parse_row(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    if len(block) < 3:  # 表头 + 分隔行 + 至少 1 数据行
        return []
    header = parse_row(block[0])
    chunks = []
    for idx, line in enumerate(block[2:]):
        if re.match(r"^[\s|:-]+$", line):  # 分隔行 |---|---|
            continue
        cells = parse_row(line)
        row = dict(zip(header, cells))
        lines_out = [f"{k}: {v}" for k, v in row.items() if v]
        if not lines_out:
            continue
        chunks.append(
            {
                "text": "\n".join(lines_out),
                "chunk_type": "param",
                "meta": {
                    "row": idx,
                    "product_id": row.get("商品ID") or row.get("product_id") or "",
                },
            }
        )
    return chunks


# ---------------- FAQ：问答对绑定 ----------------

def split_faq(text: str) -> list[dict]:
    """每个「问题+答案」为一个 chunk；超长对递归切并重复问题前缀"""
    matches = list(_FAQ_Q.finditer(text))
    if not matches:
        return split_prose_text(text)

    chunks = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=FAQ_SIZE, chunk_overlap=0, separators=["\n\n", "\n", "。", " "]
    )
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pair = text[start:end].strip()
        if not pair:
            continue
        question = pair.splitlines()[0].strip()
        if len(pair) <= FAQ_SIZE:
            chunks.append({"text": pair, "chunk_type": "faq", "meta": {"pair": i}})
        else:
            # 超长问答对：切答案，续块重复问题保证语义自含
            for j, part in enumerate(splitter.split_text(pair)):
                piece = part if j == 0 else f"{question}\n{part}"
                chunks.append({"text": piece, "chunk_type": "faq", "meta": {"pair": i}})
    return chunks


# ---------------- 详情文案：标题分节 + 递归切分 ----------------

def split_prose(parsed: ParsedFile) -> list[dict]:
    """逐页/节切分长文案，元数据带标题面包屑与页码"""
    chunks: list[dict] = []
    for text, page_meta in parsed.pages:
        if not text.strip():
            continue
        chunks.extend(split_prose_text(text, page_meta))
    return chunks


def split_prose_text(text: str, base_meta: dict | None = None) -> list[dict]:
    """Markdown 标题分节（保留 h1/h2/h3 面包屑）→ 递归切 512/64"""
    base = dict(base_meta or {})
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_MD_HEADERS, strip_headers=False
    )
    rc = RecursiveCharacterTextSplitter(
        chunk_size=PROSE_SIZE,
        chunk_overlap=PROSE_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", " "],
    )
    out = []
    for sec in md_splitter.split_text(text):
        meta = dict(base)
        crumbs = [sec.metadata[k] for k in ("h1", "h2", "h3") if sec.metadata.get(k)]
        if crumbs:
            meta["section"] = " / ".join(crumbs)
        for piece in rc.split_text(sec.page_content):
            if piece.strip():
                out.append({"text": piece, "chunk_type": "prose", "meta": meta})
    return out


# ---------------- 通用：超长块二次切 ----------------

def _split_oversize(chunks: list[dict]) -> list[dict]:
    """参数块超过 PARAM_MAX 时按行组二次切（极少触发）"""
    out = []
    splitter = RecursiveCharacterTextSplitter(chunk_size=PARAM_MAX, chunk_overlap=0)
    for c in chunks:
        if len(c["text"]) <= PARAM_MAX:
            out.append(c)
        else:
            for part in splitter.split_text(c["text"]):
                out.append({**c, "text": part})
    return out
