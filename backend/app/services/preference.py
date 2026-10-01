"""用户界面偏好：列设置、每页条数与导航折叠状态，随账号保存。"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User, UserPreference
from app.schemas.preference import PreferencesOut, PreferencesUpdate


def _to_out(preference: UserPreference) -> PreferencesOut:
    columns: dict[str, list[str]] = {}
    if preference.table_columns:
        try:
            parsed = json.loads(preference.table_columns)
            if isinstance(parsed, dict):
                columns = {
                    str(key): [str(item) for item in value]
                    for key, value in parsed.items()
                    if isinstance(value, list)
                }
        except json.JSONDecodeError:
            columns = {}  # 数据异常时按默认列展示，不影响使用
    return PreferencesOut(
        page_size=preference.page_size,
        nav_collapsed=preference.nav_collapsed,
        table_columns=columns,
    )


def get_or_create(db: Session, user: User) -> PreferencesOut:
    preference = db.execute(
        select(UserPreference).where(UserPreference.user_id == user.id)
    ).scalar_one_or_none()
    if preference is None:
        preference = UserPreference(user_id=user.id, page_size=20, nav_collapsed=False)
        db.add(preference)
        db.flush()
    return _to_out(preference)


def update(db: Session, user: User, payload: PreferencesUpdate) -> PreferencesOut:
    preference = db.execute(
        select(UserPreference).where(UserPreference.user_id == user.id)
    ).scalar_one_or_none()
    if preference is None:
        preference = UserPreference(user_id=user.id, page_size=20, nav_collapsed=False)
        db.add(preference)
        db.flush()

    data = payload.model_dump(exclude_unset=True)
    if "page_size" in data and data["page_size"] is not None:
        preference.page_size = data["page_size"]
    if "nav_collapsed" in data and data["nav_collapsed"] is not None:
        preference.nav_collapsed = data["nav_collapsed"]
    if "table_columns" in data and data["table_columns"] is not None:
        preference.table_columns = json.dumps(data["table_columns"], ensure_ascii=False)
    db.flush()
    return _to_out(preference)
