"""应用配置：全部来自环境变量，本地开发从 backend/.env 读取。"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/ 目录：配置文件按绝对路径定位，不受启动目录影响
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """环境相关的配置项，字段名即环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
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

    # NoDecode：pydantic-settings 默认把列表字段按 JSON 解析，这里改为自己按逗号切分
    cors_origins: Annotated[list[str], NoDecode] = []
    allowed_upload_extensions: Annotated[list[str], NoDecode] = [
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".xlsx",
        ".xls",
        ".docx",
        ".txt",
    ]

    # 认证与令牌（编写报告 7.1、8.1）
    jwt_secret: str = Field(
        default="dev-secret-change-me-please-use-32-bytes-or-more",
        validation_alias=AliasChoices("PULSE_JWT_SECRET", "JWT_SECRET"),
        description="JWT 签名密钥，生产环境必须由环境变量提供",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    max_login_attempts: int = 5
    lockout_duration_seconds: int = 300
    login_rate_limit_per_minute: int = 10
    session_timeout_seconds: int = 28800

    # 初始化数据用的管理员账号；口令留空时种子脚本会拒绝创建
    initial_admin_username: str = "admin"
    initial_admin_password: str = ""
    initial_admin_name: str = "系统管理员"

    # 工单号规则：前缀 + 年月日 + 三位序号（编写报告 14.1）
    maintenance_order_prefix: str = "WX"

    # 附件：存服务器目录，不入库；单文件大小与扩展名白名单（编写报告 5.5、7.4）
    attachment_dir: str = "data/attachments"
    upload_max_size_mb: int = 50

    # 维保提醒阈值（编写报告 8.1）
    maint_interval_hours: int = 500
    maint_interval_days: int = 90

    # 智能运维助手：生成层用 OpenAI 兼容协议，默认指向 DeepSeek。
    # Key 留空时接口不报错，自动降级为「只返回检索到的相似案例」。
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "LLM_API_KEY"),
        description="大模型 API Key；留空表示未配置，诊断接口降级为纯检索",
    )
    llm_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "LLM_BASE_URL"),
        description="OpenAI 兼容接口地址，换模型只改这里与模型名",
    )
    llm_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("DEEPSEEK_MODEL", "LLM_MODEL"),
        description="模型名",
    )
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # 检索：返回条数上限与是否把仿真案例计入语料（真实数据到位后可关掉仿真）
    ai_top_k: int = 5
    ai_include_synthetic: bool = True
    # 相关性重排：用对话模型过滤"字面撞词但语义无关"的候选（见 app/ai/rerank.py）
    ai_rerank: bool = True
    ai_rerank_min_score: int = 5

    # Agent 编排方式：langgraph = 显式状态图（默认）；loop = 手写循环（对照与兜底）
    ai_orchestrator: str = Field(
        default="langgraph",
        validation_alias=AliasChoices("AI_ORCHESTRATOR",),
        description="Agent 编排实现：langgraph 或 loop",
    )

    # 向量检索（见 app/ai/embedding.py）：
    #   none  = 只用 BM25（默认，零依赖）
    #   api   = 走 OpenAI 兼容的 /embeddings（通义 text-embedding-v4、智谱 embedding-3 都兼容）
    #   local = 本地 sentence-transformers 跑 BGE，语料不出内网
    embedding_provider: str = Field(
        default="none",
        validation_alias=AliasChoices("EMBEDDING_PROVIDER", "AI_EMBEDDING_PROVIDER"),
    )
    embedding_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("EMBEDDING_API_KEY", "DASHSCOPE_API_KEY"),
    )
    embedding_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("EMBEDDING_BASE_URL",),
    )
    embedding_model: str = Field(
        # 通义实验室的多语言统一向量模型，256~2560 维可自定义；
        # 同源的 text-embedding-v4 也兼容，换名字即可
        default="qwen3.7-text-embedding",
        validation_alias=AliasChoices("EMBEDDING_MODEL",),
    )
    embedding_dimensions: int | None = Field(
        default=None,
        validation_alias=AliasChoices("EMBEDDING_DIMENSIONS",),
    )
    embedding_device: str = Field(default="", validation_alias=AliasChoices("EMBEDDING_DEVICE",))
    embedding_timeout_seconds: float = 30.0

    # MCP Server：HTTP 传输默认要求访问令牌（stdio 用服务账号，见 app/mcp/auth.py）
    mcp_require_token: bool = True
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001

    @property
    def attachment_path(self) -> Path:
        return (BACKEND_DIR / self.attachment_dir).resolve()

    @field_validator("cors_origins", "allowed_upload_extensions", mode="before")
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
