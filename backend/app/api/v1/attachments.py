"""附件上传、下载与列表接口。"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.system import Attachment
from app.models.user import User
from app.schemas.system import AttachmentOut
from app.services import attachment as service

router = APIRouter(prefix="/attachments", tags=["附件"])


def _serialize(attachment: Attachment) -> dict:
    return AttachmentOut.model_validate(attachment).model_dump(mode="json")


@router.post("", response_model=ApiResponse, summary="上传附件")
async def upload_attachment(
    file: UploadFile = File(description="待上传文件"),
    object_type: str = Form(description="关联对象类型，如 maintenance_order"),
    object_id: int = Form(description="关联对象 ID"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("attachments.upload")),
) -> dict:
    content = await file.read()
    attachment = service.create_attachment(
        db,
        file_name=file.filename or "未命名文件",
        content=content,
        content_type=file.content_type,
        object_type=object_type,
        object_id=object_id,
        user=user,
    )
    return ok(_serialize(attachment))


@router.get("", response_model=ApiResponse, summary="附件列表")
def list_attachments(
    object_type: str | None = Query(default=None, description="按对象类型过滤"),
    object_id: int | None = Query(default=None, description="按对象 ID 过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("attachments.download")),
) -> dict:
    items, total = service.list_attachments(db, object_type, object_id, page, page_size)
    return ok(
        {
            "items": [_serialize(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{attachment_id}", summary="下载附件")
def download_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("attachments.download")),
) -> FileResponse:
    attachment = service.get_attachment(db, attachment_id)
    path = service.resolve_path(attachment)
    return FileResponse(
        path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.file_name,
    )
