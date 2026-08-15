from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.config import get_settings
from app.db import Base, engine
from app.models import (  # noqa: F401
    AgentSession,
    AnalysisInboxItem,
    ChapterMemoryArchive,
    ChapterMemorySlice,
    LoreCraftCard,
    Project,
    Share,
    User,
    UserSettings,
)

logger = logging.getLogger(__name__)


def _alembic_upgrade_sync() -> None:
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await asyncio.to_thread(_alembic_upgrade_sync)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alembic upgrade skipped/failed: %s", exc)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS agent_sessions
                  ADD COLUMN IF NOT EXISTS title VARCHAR(255) DEFAULT '新对话'
                """
            )
        )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="VN Script Studio API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


app = create_app()
