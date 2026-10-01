"""应用入口：装配配置、日志、异常处理与路由。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import dispose_engine

logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "dev-secret-change-me-please-use-32-bytes-or-more"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    if settings.app_env != "dev" and settings.jwt_secret == DEFAULT_JWT_SECRET:
        logger.warning("当前环境为 %s 却仍在使用默认 JWT 密钥，请通过 PULSE_JWT_SECRET 提供", settings.app_env)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("启动 %s %s（%s）", settings.app_name, settings.app_version, settings.app_env)
        yield
        dispose_engine()
        logger.info("已关闭")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
