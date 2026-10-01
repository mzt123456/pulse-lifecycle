"""附件业务：校验、落盘与读取。文件本体存服务器目录，数据库只存元数据。"""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import BusinessError, ErrorCode
from app.core.timeutil import local_now
from app.models.system import Attachment
from app.models.user import User


def _check_extension(file_name: str, settings: Settings) -> str:
    suffix = Path(file_name).suffix.lower()
    allowed = {item.lower() for item in settings.allowed_upload_extensions}
    if not suffix or suffix not in allowed:
        raise BusinessError(
            ErrorCode.BUSINESS_RULE,
            f"不允许的文件类型：{suffix or '未知'}，允许上传 {'、'.join(sorted(allowed))}",
            422,
        )
    return suffix


def _check_size(content: bytes, settings: Settings) -> None:
    limit = settings.upload_max_size_mb * 1024 * 1024
    if len(content) > limit:
        raise BusinessError(
            ErrorCode.BUSINESS_RULE,
            f"文件大小 {len(content) / 1024 / 1024:.1f} MB 超过限制（最大 {settings.upload_max_size_mb} MB）",
            413,
        )


def create_attachment(
    db: Session,
    *,
    file_name: str,
    content: bytes,
    content_type: str | None,
    object_type: str,
    object_id: int,
    user: User,
    settings: Settings | None = None,
) -> Attachment:
    settings = settings or get_settings()
    suffix = _check_extension(file_name, settings)
    _check_size(content, settings)

    settings.attachment_path.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{suffix}"
    (settings.attachment_path / stored_name).write_bytes(content)

    attachment = Attachment(
        object_type=object_type,
        object_id=object_id,
        file_name=file_name,
        stored_name=stored_name,
        content_type=content_type,
        size_bytes=len(content),
        storage_path=stored_name,
        uploaded_by=user.id,
        uploaded_at=local_now(),
    )
    db.add(attachment)
    db.flush()
    return attachment


def get_attachment(db: Session, attachment_id: int) -> Attachment:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "附件不存在", 404)
    return attachment


def resolve_path(attachment: Attachment, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    path = settings.attachment_path / (attachment.storage_path or attachment.stored_name)
    if not path.exists():
        raise BusinessError(ErrorCode.NOT_FOUND, "附件文件已丢失，请联系管理员", 404)
    return path


def list_attachments(
    db: Session,
    object_type: str | None = None,
    object_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Attachment], int]:
    stmt = select(Attachment)
    if object_type:
        stmt = stmt.where(Attachment.object_type == object_type)
    if object_id is not None:
        stmt = stmt.where(Attachment.object_id == object_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.execute(
            stmt.order_by(Attachment.id.desc()).limit(page_size).offset((page - 1) * page_size)
        ).scalars()
    )
    return items, total
