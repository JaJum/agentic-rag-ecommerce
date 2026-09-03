"""API 路由汇总：统一挂在 /api/v1 前缀下"""
from fastapi import APIRouter

from app.api.v1 import admin, auth, chat, documents, health, sessions

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(documents.router)
api_router.include_router(sessions.router)
api_router.include_router(chat.router)
