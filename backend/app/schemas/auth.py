"""认证相关的请求与响应模型。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, description="登录名")
    password: str = Field(min_length=1, max_length=128, description="密码")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, description="刷新令牌")


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, description="待撤销的刷新令牌")


class UserInfo(BaseModel):
    id: int
    username: str
    real_name: str | None = None
    department: str | None = None
    roles: list[str] = []
    permissions: list[str] = []


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="访问令牌有效期（秒）")
    user: UserInfo
