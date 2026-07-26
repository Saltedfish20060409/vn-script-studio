from fastapi import APIRouter

from app.api.v1 import auth, projects, settings, shares

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(settings.router)
api_router.include_router(shares.router)
