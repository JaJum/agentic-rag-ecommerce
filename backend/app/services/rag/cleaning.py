"""
文本清洗（入库链路第 2 步）：
去 HTML 标签、全角字母数字归一（保留中文标点）、去页眉页脚页码行、
空白归一、去连续重复行。
"""
import re

# HTML 标签
_HTML_TAG = re.compile(r"<[^>]+>")
# 页眉页脚/页码行：如「第 3 页」「Page 3」「- 3 -」「3/12」
_PAGE_LINE = re.compile(
    r"^\s*[-—=*_~]*\s*(第\s*\d+\s*页|page\s*\d+|\d+\s*/\s*\d+)\s*[-—=*_~]*\s*$",
    re.IGNORECASE,
)
# 连续 3 个以上空行
_BLANKS = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """清洗单段文本：归一化 → 去噪声行 → 去重复行"""
    # 1. 全角字母数字/空格 → 半角（保留中文标点如 ，：；不破坏原文观感）
    text = _halfwidth_alnum(text)
    # 2. HTML 标签替换为空格（保留标签间文本）
    text = _HTML_TAG.sub(" ", text)

    # 3. 逐行去噪：页码行剔除、行尾空白剔除、连续重复行只保留首行
    lines_out: list[str] = []
    prev = None
    for line in text.splitlines():
        line = line.rstrip()
        if _PAGE_LINE.match(line):
            continue
        if line.strip() and line.strip() == prev:
            continue  # 连续重复行（页眉常客）
        lines_out.append(line)
        prev = line.strip()

    # 4. 空白归一：压缩连续空行为一个
    return _BLANKS.sub("\n\n", "\n".join(lines_out)).strip()


def _halfwidth_alnum(text: str) -> str:
    """仅转换全角字母/数字/空格为半角；中文标点（，：；！？（））保持不变"""
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
            out.append(chr(code - 0xFEE0))  # 全角字母数字 → 半角
        elif code == 0x3000:
            out.append(" ")  # 全角空格 → 半角空格
        else:
            out.append(ch)
    return "".join(out)
