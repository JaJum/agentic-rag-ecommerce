"""
数据模型：8 张核心表（MySQL 8 / InnoDB / utf8mb4）
- users / chat_sessions / messages      → 用户、会话、消息（多用户多会话 + 历史持久化）
- documents / chunks                    → 知识库文档与分块（chunks 为检索 source of truth）
- message_citations / feedback          → 引用溯源（原文快照）与用户反馈
- qa_logs                               → 问答日志（延迟/命中率/token 统计数据源）

约定：chunks 表是 BM25/重建索引的 source of truth，Chroma 向量库是可重建的衍生索引。
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.compat import BigInt as BigInteger
from app.db.compat import LongText as MEDIUMTEXT
from app.db.compat import Ts6 as DATETIME


def gen_uuid() -> str:
    """生成 36 位 uuid 字符串主键（业务表统一用 uuid）"""
    return str(uuid.uuid4())


class User(Base):
    """用户表：role 决定权限（admin 独享知识库管理）"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="登录名，唯一")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 密码哈希")
    role: Mapped[str] = mapped_column(Enum("admin", "user", name="user_role"), default="user", comment="角色")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), onupdate=datetime.now)


class ChatSession(Base):
    """会话表：每用户独立会话，软删保护历史可找回"""

    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_sessions_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="新会话", comment="会话标题（默认取首问截断）")
    created_at: Mapped[datetime] = mapped_column(DATETIME, default=datetime.now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DATETIME, default=datetime.now, server_default=func.now(), onupdate=datetime.now)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="软删标记")


class Message(Base):
    """消息表：对话正文 + 查询改写结果 + 引用快照（历史回放不依赖向量库）"""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Enum("user", "assistant", name="message_role"), nullable=False, comment="消息角色")
    content: Mapped[str] = mapped_column(MEDIUMTEXT, comment="正文（assistant 为含 [n] 引用的 Markdown）")
    rewritten_query: Mapped[Optional[str]] = mapped_column(String(512), comment="查询改写结果（仅 assistant）")
    citations: Mapped[Optional[Any]] = mapped_column(JSON, comment="引用快照列表（冗余便于回放）")
    token_usage: Mapped[Optional[int]] = mapped_column(Integer, comment="token 消耗")
    status: Mapped[str] = mapped_column(
        Enum("complete", "partial", "error", "general", "fallback", name="message_status"),
        default="complete",
        comment="complete=完整 partial=断连截断 error=失败 general=通用闲聊回答(非知识库) fallback=兜底拒答",
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME, default=datetime.now, server_default=func.now())


class Document(Base):
    """
    文档表：入库状态机
    uploaded→parsing→cleaning→chunking→embedding→indexing→completed / failed（可重试）
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_status", "status"),
        Index("ix_documents_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    filename: Mapped[str] = mapped_column(String(255), comment="存储文件名（uuid 命名防路径问题）")
    orig_name: Mapped[str] = mapped_column(String(255), comment="用户上传的原始文件名")
    file_path: Mapped[str] = mapped_column(String(512), comment="存储相对路径（相对 data/uploads）")
    file_type: Mapped[str] = mapped_column(String(16), comment="md/txt/pdf/docx/csv/xlsx")
    size: Mapped[int] = mapped_column(BigInteger, comment="文件字节数")
    doc_type: Mapped[str] = mapped_column(
        Enum("auto", "param", "faq", "prose", name="doc_type"),
        default="auto",
        comment="内容类型，决定分块策略（auto=按内容自动识别）",
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "uploaded", "parsing", "cleaning", "chunking",
            "embedding", "indexing", "completed", "failed",
            name="doc_status",
        ),
        default="uploaded",
        comment="入库状态机当前状态",
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, comment="进度 0-100")
    error_msg: Mapped[Optional[str]] = mapped_column(String(512), comment="失败原因（failed 时）")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, comment="分块总数")
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, comment="上传者 user_id")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(), onupdate=datetime.now)


class Chunk(Base):
    """分块表：BM25 与重建索引的 source of truth；id 同时作为 Chroma 向量 id（幂等）"""

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_doc_seq", "doc_id", "seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid, comment="uuid，同 Chroma id")
    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, comment="文档内序号（从 0 开始）")
    text: Mapped[str] = mapped_column(MEDIUMTEXT, comment="分块原文")
    chunk_type: Mapped[str] = mapped_column(String(16), comment="param/faq/prose")
    meta: Mapped[Optional[Any]] = mapped_column("meta", JSON, comment="section/page/row/product_id 等元数据")
    char_len: Mapped[int] = mapped_column(Integer, default=0, comment="字符数")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())


class MessageCitation(Base):
    """引用表：回答引用的知识库片段（存原文快照，文档删除后历史引用仍可展示）"""

    __tablename__ = "message_citations"
    __table_args__ = (Index("ix_citations_message", "message_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(36), comment="来源分块 id（允许悬空：文档可能已删除）")
    doc_id: Mapped[Optional[str]] = mapped_column(String(36), comment="来源文档 id")
    citation_no: Mapped[int] = mapped_column(Integer, comment="引用编号 [n]，与回答中标注对应")
    snippet: Mapped[Optional[str]] = mapped_column(Text, comment="原文快照（核心：删文档不破坏历史）")
    score: Mapped[Optional[float]] = mapped_column(Float, comment="rerank 得分")
    cited: Mapped[int] = mapped_column(Integer, default=1, comment="1=回答引用 0=检索到但未引用")


class Feedback(Base):
    """反馈表：点赞/点踩，一条消息仅一条反馈"""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, comment="1=赞 / -1=踩")
    comment: Mapped[Optional[str]] = mapped_column(String(512), comment="可选补充意见")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())


class QaLog(Base):
    """问答日志：延迟/首 token/命中率/token 统计（管理端仪表盘数据源）"""

    __tablename__ = "qa_logs"
    __table_args__ = (
        Index("ix_qalogs_created", "created_at"),
        Index("ix_qalogs_user", "user_id"),
        Index("ix_qalogs_hit", "hit"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="提问用户")
    session_id: Mapped[Optional[str]] = mapped_column(String(36), comment="会话 id")
    query: Mapped[str] = mapped_column(String(512), comment="用户原始问题")
    rewritten_query: Mapped[Optional[str]] = mapped_column(String(512), comment="改写后的检索式")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, comment="端到端总耗时")
    first_token_ms: Mapped[Optional[int]] = mapped_column(Integer, comment="首 token 延迟（体感指标）")
    retrieval_count: Mapped[Optional[int]] = mapped_column(Integer, comment="命中分块数")
    tool_count: Mapped[Optional[int]] = mapped_column(Integer, comment="Agent 工具调用步数")
    route: Mapped[Optional[str]] = mapped_column(
        String(16), comment="路由/来源：chitchat|kb_simple|business|multi_hop|rag|cache"
    )
    hit: Mapped[Optional[int]] = mapped_column(Integer, comment="1=命中知识库 0=兜底拒答")
    token_usage: Mapped[Optional[int]] = mapped_column(Integer, comment="token 消耗")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())

class AgentRun(Base):
    """Agent 单次运行记录：路由、状态、步数、工具调用与耗时，供仪表盘与轨迹回放"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_created", "created_at"),
        Index("ix_agent_runs_session", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    message_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, comment="对应的 assistant 消息 id")
    session_id: Mapped[Optional[str]] = mapped_column(String(36), comment="会话 id")
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="提问用户")
    route: Mapped[Optional[str]] = mapped_column(String(16), comment="路由结果")
    status: Mapped[str] = mapped_column(String(16), default="ok", comment="ok|fallback|error|timeout")
    step_count: Mapped[int] = mapped_column(Integer, default=0, comment="工具执行步数")
    tool_calls: Mapped[Optional[Any]] = mapped_column(JSON, comment="工具调用摘要列表（已脱敏）")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, comment="端到端耗时")
    first_token_ms: Mapped[Optional[int]] = mapped_column(Integer, comment="首 token 延迟")
    token_usage: Mapped[Optional[int]] = mapped_column(Integer, comment="token 消耗")
    error: Mapped[Optional[str]] = mapped_column(String(500), comment="失败原因（截断）")
    created_at: Mapped[datetime] = mapped_column(DATETIME, default=datetime.now, server_default=func.now())


class AgentStep(Base):
    """Agent 执行轨迹单步：节点、工具、参数/结果摘要、耗时"""

    __tablename__ = "agent_steps"
    __table_args__ = (Index("ix_agent_steps_run", "run_id", "step_no"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), comment="agent_runs.id")
    step_no: Mapped[int] = mapped_column(Integer, default=0, comment="步序号")
    node: Mapped[str] = mapped_column(String(32), comment="route|agent|tool_call|tool_result|finalize|verify")
    tool_name: Mapped[Optional[str]] = mapped_column(String(64), comment="工具名")
    args_preview: Mapped[Optional[str]] = mapped_column(String(500), comment="参数摘要（脱敏截断）")
    result_preview: Mapped[Optional[str]] = mapped_column(String(500), comment="结果摘要（脱敏截断）")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, comment="该步耗时（可选）")
    ok: Mapped[Optional[int]] = mapped_column(Integer, comment="1=成功 0=失败")
    created_at: Mapped[datetime] = mapped_column(DATETIME, default=datetime.now, server_default=func.now())


class HandoffTicket(Base):
    """转人工工单（Agent 写工具，AGENT_ALLOW_WRITE_TOOLS=false 时只返回模拟工单号）"""

    __tablename__ = "handoff_tickets"
    __table_args__ = (Index("ix_handoff_status", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), comment="来源会话")
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="提问用户")
    reason: Mapped[str] = mapped_column(String(255), comment="转人工原因")
    summary: Mapped[str] = mapped_column(String(1000), comment="问题摘要（给人工客服）")
    status: Mapped[str] = mapped_column(
        Enum("open", "closed", name="handoff_status"), default="open", comment="工单状态"
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME, default=datetime.now, server_default=func.now())
