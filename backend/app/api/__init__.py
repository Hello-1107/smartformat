"""API 路由聚合。"""

from fastapi import APIRouter

from app.api import auth, checks, content_reviews, documents, rules, workspaces

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(documents.router)
api_router.include_router(rules.router)
api_router.include_router(checks.router)
api_router.include_router(content_reviews.router)
