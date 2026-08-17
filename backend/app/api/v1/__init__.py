from fastapi import APIRouter

from app.api.v1 import (
    auth,
    character_voice,
    collab,
    consistency,
    harness,
    lenses,
    lore,
    memory,
    mentors,
    pipeline,
    projects,
    settings,
    shares,
    style_memory,
    usage,
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
api_router.include_router(usage.router)
api_router.include_router(collab.router)
api_router.include_router(consistency.router)
api_router.include_router(style_memory.router)
