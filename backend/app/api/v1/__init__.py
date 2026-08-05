from fastapi import APIRouter

from app.api.v1 import (
    auth,
    character_voice,
    harness,
    lenses,
    lore,
    memory,
    mentors,
    pipeline,
    projects,
    settings,
    shares,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(memory.router)
api_router.include_router(harness.router)
api_router.include_router(pipeline.router)
api_router.include_router(mentors.router)
api_router.include_router(lenses.router)
api_router.include_router(character_voice.router)
api_router.include_router(lore.router)
api_router.include_router(settings.router)
api_router.include_router(shares.router)
