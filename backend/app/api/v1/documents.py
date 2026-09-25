"""
知识库管理接口（仅 admin，需求 1/6）：
上传 → 后台异步入库；列表/详情/分块预览/重建索引/删除。
"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.exceptions import BizError
from app.db.base import get_db
from app.db.models import Chunk, Document, User, gen_uuid
from app.schemas.document import ChunkPageOut, DocumentOut
from app.services import tasks, vector_store
from app.services.cache import bump_index_version
from app.services.rag.ingest import UPLOAD_DIR
from app.utils.file_utils import stored_name, validate_upload

router = APIRouter(prefix="/documents", tags=["知识库管理"])


@router.post(
    "/upload",
    response_model=list[DocumentOut],
    status_code=status.HTTP_201_CREATED,
    summary="上传文档（多文件，异步入库）",
)
async def upload_documents(
    files: list[UploadFile] = File(..., description="支持 md/txt/pdf/docx/csv/xlsx"),
    doc_type: str = Form("auto", description="内容类型：auto/param/faq/prose"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """上传文档并触发后台入库任务（状态机：uploaded→…→completed/failed）"""
    if doc_type not in ("auto", "param", "faq", "prose"):
        raise BizError("doc_type 取值不合法", code="BAD_DOC_TYPE")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    created: list[Document] = []
    for f in files:
        content = await f.read()
        ext = validate_upload(f.filename, len(content))
        # 路径安全：原始文件名只做展示，存储名用 uuid（防穿越/中文路径问题）
        orig_name = Path(f.filename or "unnamed").name
        doc_id = gen_uuid()  # 先生成主键，供存储文件命名
        fname = stored_name(doc_id, ext)
        (UPLOAD_DIR / fname).write_bytes(content)
        doc = Document(
            id=doc_id,
            orig_name=orig_name,
            filename=fname,
            file_path=fname,
            file_type=ext.lstrip("."),
            size=len(content),
            doc_type=doc_type,
            status="uploaded",
            created_by=admin.id,
        )
        db.add(doc)
        created.append(doc)

    await db.commit()
    for doc in created:
        tasks.submit_ingest(doc.id)  # 异步入库，接口立即返回
    return created


@router.get("", response_model=list[DocumentOut], summary="文档列表")
async def list_documents(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """按上传时间倒序返回文档（含状态/进度/分块数）"""
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return result.scalars().all()


@router.get("/{doc_id}", response_model=DocumentOut, summary="文档详情")
async def get_document(
    doc_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """单文档详情（含失败原因）"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise BizError("文档不存在", code="DOC_NOT_FOUND", status_code=404)
    return doc


@router.get("/{doc_id}/chunks", response_model=ChunkPageOut, summary="分块预览")
async def preview_chunks(
    doc_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """分块预览（分页）：验证差异化分块效果"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise BizError("文档不存在", code="DOC_NOT_FOUND", status_code=404)
    total = (
        await db.execute(
            select(func.count(Chunk.id)).where(Chunk.doc_id == doc_id)
        )
    ).scalar() or 0
    result = await db.execute(
        select(Chunk)
        .where(Chunk.doc_id == doc_id)
        .order_by(Chunk.seq)
        .offset((page - 1) * size)
        .limit(size)
    )
    return ChunkPageOut(total=total, items=result.scalars().all())


@router.post("/{doc_id}/reindex", summary="重建索引（重跑入库链路）")
async def reindex_document(
    doc_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """重建该文档的分块/索引（幂等重建，M3 起含向量库重建）"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise BizError("文档不存在", code="DOC_NOT_FOUND", status_code=404)
    doc.status = "uploaded"
    doc.progress = 0
    doc.error_msg = None
    await db.commit()
    tasks.submit_ingest(doc.id)
    return {"message": "重建任务已提交"}


@router.post("/reindex-all", summary="全量重建（BM25+Chroma 对齐）")
async def reindex_all(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """全部文档重跑入库链路（自愈工具：修复向量库与 MySQL 不一致）"""
    result = await db.execute(select(Document.id))
    doc_ids = [row[0] for row in result.all()]
    for doc_id in doc_ids:
        doc = await db.get(Document, doc_id)
        doc.status = "uploaded"
        doc.progress = 0
        doc.error_msg = None
        tasks.submit_ingest(doc_id)  # 任务队列串行执行，天然限流
    await db.commit()
    return {"message": f"已提交 {len(doc_ids)} 个重建任务"}


@router.delete("/{doc_id}", summary="删除文档")
async def delete_document(
    doc_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除文档：向量 + 分块记录 + 存储文件 + 文档行"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise BizError("文档不存在", code="DOC_NOT_FOUND", status_code=404)
    # 固定删除顺序（方案）：向量 → MySQL 行 → 文件
    await asyncio.to_thread(vector_store.delete_by_doc, doc_id)
    await db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    file_path = UPLOAD_DIR / doc.filename
    if file_path.exists():
        file_path.unlink()
    await db.delete(doc)
    await db.commit()
    bump_index_version()  # 索引变化 → 问答缓存失效
    return {"message": "删除成功"}
