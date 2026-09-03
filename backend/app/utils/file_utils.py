"""
上传文件安全工具：类型白名单 / 大小上限 / uuid 存储名防路径穿越。
"""
from pathlib import Path

from app.core.exceptions import BizError

# 允许的文档类型（需求 1 支持的格式）
ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".csv", ".xlsx"}
# 单文件大小上限 50MB（企业级防护）
MAX_FILE_SIZE = 50 * 1024 * 1024


def validate_upload(filename: str | None, size: int) -> str:
    """校验扩展名与大小，返回小写扩展名（含点）；不合法抛 400"""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise BizError(
            f"不支持的文件类型：{ext or '未知'}（支持 {exts_str()}）",
            code="BAD_FILE_TYPE",
            status_code=400,
        )
    if size > MAX_FILE_SIZE:
        raise BizError(
            f"文件超过 {MAX_FILE_SIZE // (1024 * 1024)}MB 限制",
            code="FILE_TOO_LARGE",
            status_code=400,
        )
    return ext


def stored_name(doc_id: str, ext: str) -> str:
    """生成存储文件名：uuid + 扩展名（规避中文/空格/路径穿越问题）"""
    return f"{doc_id}{ext}"


def exts_str() -> str:
    """白名单展示文案"""
    return "/".join(sorted(e.lstrip(".") for e in ALLOWED_EXTENSIONS))
