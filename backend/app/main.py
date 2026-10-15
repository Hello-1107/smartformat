"""FastAPI 应用入口。

启动：uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  确保所有模型被注册到 Base.metadata
from app.api import api_router
from app.database import Base, engine


def create_app() -> FastAPI:
    app = FastAPI(title="AI 协同办公 - 智能格式审查助手", version="0.1.0")

    # 演示环境放开跨域；生产环境应改为前端具体域名
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

# 演示优先：启动时自动建表（生产环境应使用 Alembic 迁移）
Base.metadata.create_all(bind=engine)
