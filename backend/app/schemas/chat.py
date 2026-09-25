"""会话/问答相关 Pydantic 模型"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """新建会话"""

    title: Optional[str] = Field(None, max_length=128, description="会话标题，默认取首问")


class SessionUpdate(BaseModel):
    """重命名会话"""

    title: str = Field(..., min_length=1, max_length=128)


class SessionOut(BaseModel):
    """会话信息出参"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CitationOut(BaseModel):
    """引用片段出参（含原文快照）"""

    citation_no: int
    chunk_id: str
    doc_id: Optional[str] = None
    doc_name: Optional[str] = None
    snippet: Optional[str] = None
    score: Optional[float] = None
    cited: bool = True


class MessageOut(BaseModel):
    """消息出参（含引用列表）"""

    id: str
    role: str
    content: str
    rewritten_query: Optional[str] = None
    citations: list[CitationOut] = []
    status: str = "complete"
    created_at: datetime


class ChatStreamRequest(BaseModel):
    """问答请求（SSE）"""

    session_id: Optional[str] = Field(None, description="会话 id；空则自动新建")
    query: str = Field(..., min_length=1, max_length=2000, description="用户问题")


class SessionIdIn(BaseModel):
    """仅含会话 id 的请求（停止生成等）"""

    session_id: str


class FeedbackIn(BaseModel):
    """反馈（点赞/点踩）"""

    rating: int = Field(..., description="1=赞 -1=踩")
    comment: Optional[str] = Field(None, max_length=512)
