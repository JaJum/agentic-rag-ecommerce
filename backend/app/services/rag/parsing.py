"""
文档解析（入库链路第 1 步）：
md/txt → TextLoader；pdf → PyPDFLoader（逐页带页码）；docx → Docx2txtLoader；
csv/xlsx → pandas 结构化逐行（供参数表分块器整行键值化）。
解析器均为同步阻塞实现，调用方用 asyncio.to_thread 包裹。
"""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class ParsedFile:
    """解析结果：text 型按页给出 (文本, 元数据)；table 型给出结构化行"""

    kind: str  # "text"（md/txt/pdf/docx）| "table"（csv/xlsx）
    pages: list[tuple[str, dict]] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)


def parse_file(file_path: Path, file_type: str) -> ParsedFile:
    """按扩展名分发解析器（file_type 不含点，如 pdf）"""
    if file_type in ("csv", "xlsx"):
        return _parse_table(file_path, file_type)
    if file_type == "pdf":
        return _parse_pdf(file_path)
    if file_type == "docx":
        return _parse_docx(file_path)
    return _parse_text(file_path)  # md / txt


def _parse_text(path: Path) -> ParsedFile:
    """md/txt：UTF-8 读取全文"""
    from langchain_community.document_loaders import TextLoader

    docs = TextLoader(str(path), encoding="utf-8").load()
    return ParsedFile(kind="text", pages=[(d.page_content, {}) for d in docs])


def _parse_pdf(path: Path) -> ParsedFile:
    """pdf：逐页解析，metadata 带页码（引用溯源用）"""
    from langchain_community.document_loaders import PyPDFLoader

    docs = PyPDFLoader(str(path)).load()
    pages = [
        (d.page_content, {"page": d.metadata.get("page", i) + 1})
        for i, d in enumerate(docs)
    ]
    return ParsedFile(kind="text", pages=pages)


def _parse_docx(path: Path) -> ParsedFile:
    """docx：抽取正文文本"""
    from langchain_community.document_loaders import Docx2txtLoader

    docs = Docx2txtLoader(str(path)).load()
    return ParsedFile(kind="text", pages=[(d.page_content, {}) for d in docs])


def _parse_table(path: Path, file_type: str) -> ParsedFile:
    """csv/xlsx：转为「字段: 值」可序列化的结构化行，全部转字符串去 NaN"""
    if file_type == "csv":
        df = _read_csv(path)
    else:
        df = pd.read_excel(path, dtype=str).fillna("")
    rows = [
        {str(k).strip(): str(v).strip() for k, v in rec.items()}
        for rec in df.to_dict(orient="records")
    ]
    return ParsedFile(kind="table", rows=rows)


def _read_csv(path: Path) -> pd.DataFrame:
    """CSV 多编码兜底：utf-8-sig（Excel 导出）→ utf-8 → gbk（中文旧编码）"""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别的 CSV 编码：{path.name}")
