"""应用配置：全部来自环境变量，本地开发从 backend/.env 读取。"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """环境相关的配置项，字段名即环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "某能源装备企业维保管理系统"
    app_version: str = "3.0.0"
    app_env: str = "dev"
    log_level: str = "INFO"

    api_prefix: str = "/api/v1"

    database_url: str = (
        "mysql+pymysql://pulse_dev:dev_pwd@127.0.0.1:3307/pulse_lifecycle_dev?charset=utf8mb4"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800
    db_echo: bool = False

    cors_origins: list[str] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        """允许写成逗号分隔的字符串，留空表示不启用跨域白名单。"""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """配置在进程内只解析一次。"""
    return Settings()
