"""知识库接口：上传、粘贴、列表、详情、删除与概览。

上传与删除都是写操作，审计中间件会自动留痕（谁在什么时候传了什么、删了什么）。
解析失败不报 500，而是把文档以 failed 状态落库、把原因写进 error 字段，页面直接展示。
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeDocumentDetail,
    KnowledgeDocumentOut,
    KnowledgeStatsOut,
    KnowledgeTextCreate,
)
from app.services import knowledge as service

router = APIRouter(prefix="/knowledge", tags=["知识库"])


def _serialize(document: KnowledgeDocument, names: dict[int, str]) -> dict:
    data = KnowledgeDocumentOut.model_validate(document).model_dump(mode="json")
    data["created_by_name"] = names.get(document.created_by or 0)
    return data


def _user_names(db: Session, documents: list[KnowledgeDocument]) -> dict[int, str]:
    """一次查出本页涉及的创建人姓名，避免逐行查询。"""
    ids = {document.created_by for document in documents if document.created_by}
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.real_name).where(User.id.in_(ids))).all()
    return {user_id: real_name or "" for user_id, real_name in rows}


@router.get("/documents", response_model=ApiResponse, summary="知识库文档列表")
def list_documents(
    keyword: str | None = Query(default=None, description="按标题模糊搜索"),
    status: str | None = Query(default=None, description="解析状态：ready / failed"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("knowledge.view")),
) -> dict:
    items, total = service.list_documents(
        db, keyword=keyword, status=status, page=page, page_size=page_size
    )
    names = _user_names(db, items)
    return ok(
        {
            "items": [_serialize(item, names) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/stats", response_model=ApiResponse, summary="知识库概览")
def knowledge_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("knowledge.view")),
) -> dict:
    return ok(KnowledgeStatsOut.model_validate(service.stats(db)).model_dump(mode="json"))


@router.get("/documents/{document_id}", response_model=ApiResponse, summary="知识库文档详情")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("knowledge.view")),
) -> dict:
    document = service.get_document(db, document_id)
    chunks = service.list_chunks(db, document_id)
    data = KnowledgeDocumentDetail.model_validate(
        {
            **KnowledgeDocumentOut.model_validate(document).model_dump(),
            "chunks": [chunk for chunk in chunks],
        }
    ).model_dump(mode="json")
    data["created_by_name"] = _user_names(db, [document]).get(document.created_by or 0)
    return ok(data)


@router.post("/documents/text", response_model=ApiResponse, summary="粘贴文本入库")
def create_from_text(
    payload: KnowledgeTextCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("knowledge.upload")),
) -> dict:
    document = service.create_from_text(
        db, title=payload.title, content=payload.content, user=user
    )
    return ok(_serialize(document, {user.id: user.real_name or ""}))


@router.post("/documents/upload", response_model=ApiResponse, summary="上传文档入库")
async def upload_document(
    file: UploadFile = File(description="支持 txt / md / docx / pdf"),
    title: str | None = Form(default=None, description="标题，留空用文件名"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("knowledge.upload")),
) -> dict:
    content = await file.read()
    document = service.create_from_file(
        db,
        file_name=file.filename or "未命名文档",
        content=content,
        content_type=file.content_type,
        user=user,
        title=title,
    )
    return ok(_serialize(document, {user.id: user.real_name or ""}))


@router.delete("/documents/{document_id}", response_model=ApiResponse, summary="删除文档（软删除）")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("knowledge.delete")),
) -> dict:
    document = service.delete_document(db, document_id, user)
    return ok(_serialize(document, {user.id: user.real_name or ""}))
