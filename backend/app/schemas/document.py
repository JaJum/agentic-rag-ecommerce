"""文档与分块的 Pydantic 模型（响应结构与 Swagger 文档）"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class DocumentOut(BaseModel):
    """文档信息出参（列表/详情共用）"""

    id: str
    orig_name: str
    file_type: str
    size: int
    doc_type: str
    status: str
    progress: int
    error_msg: Optional[str] = None
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ChunkOut(BaseModel):
    """分块预览出参"""

    id: str
    seq: int
    chunk_type: str
    text: str
    meta: Optional[dict[str, Any]] = None
    char_len: int

    model_config = {"from_attributes": True}


class ChunkPageOut(BaseModel):
    """分块分页出参"""

    total: int
    items: list[ChunkOut]
