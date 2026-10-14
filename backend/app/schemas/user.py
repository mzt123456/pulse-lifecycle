"""用户、角色与权限点的请求与响应模型（编写报告 3.1 用户与权限模块）。"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DateTimeStr


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    module: str
    action: str
    description: str | None = None


class RoleOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_builtin: bool
    permission_ids: list[int] = Field(default_factory=list)
    user_count: int = Field(default=0, description="关联账号数，删除前给前端提示")


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="角色名称")
    description: str | None = Field(default=None, max_length=255)
    permission_ids: list[int] = Field(default_factory=list, description="勾选的权限点")


class RoleUpdate(BaseModel):
    """内置角色只允许改说明与权限点，名称与删除都不开放。"""

    description: str | None = Field(default=None, max_length=255)
    permission_ids: list[int] | None = None


class UserOut(BaseModel):
    id: int
    username: str
    real_name: str | None = None
    phone: str | None = None
    department: str | None = None
    is_active: bool
    roles: list[str] = Field(default_factory=list)
    role_ids: list[int] = Field(default_factory=list)
    last_login_at: DateTimeStr | None = None
    created_at: DateTimeStr


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
        description="登录名，只允许字母、数字与 _ . -",
    )
    password: str = Field(min_length=8, max_length=128, description="初始口令，至少 8 位")
    real_name: str = Field(min_length=1, max_length=64, description="姓名")
    phone: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=64, description="岗位或部门")
    role_ids: list[int] = Field(min_length=1, description="至少分配一个角色")


class UserUpdate(BaseModel):
    real_name: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=64)
    is_active: bool | None = Field(default=None, description="停用后无法登录，刷新令牌同时撤销")
    role_ids: list[int] | None = Field(default=None, description="传了就整体替换该用户的角色")


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128, description="新口令，至少 8 位")
