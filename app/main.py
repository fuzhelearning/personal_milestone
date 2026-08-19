from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import AppError, app_error_handler
from app.routers import auth, gantt, goals, home, internal, jobs

# ensure models registered
from app import models  # noqa: F401


def create_app() -> FastAPI:
    settings = get_settings()
    docs_url = "/docs" if settings.enable_docs else None
    redoc_url = "/redoc" if settings.enable_docs else None
    openapi_url = "/openapi.json" if settings.enable_docs else None

    app = FastAPI(
        title="Personal Milestone API",
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.add_exception_handler(AppError, app_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "参数校验失败",
                "request_id": "",
                "details": {"errors": exc.errors()},
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(goals.router)
    app.include_router(jobs.router)
    app.include_router(home.router)
    app.include_router(gantt.router)
    app.include_router(internal.router)

    @app.on_event("startup")
    def _startup() -> None:
        cfg = get_settings()
        cfg.validate_for_runtime()
        # 表结构由 Alembic 管理：APP_ENV=... alembic upgrade head

    @app.get("/health")
    def health() -> dict:
        cfg = get_settings()
        return {
            "ok": True,
            "app_env": cfg.app_env,
            "llm_mode": cfg.llm_mode,
            "wechat_mock": cfg.wechat_mock,
        }

    return app


app = create_app()
