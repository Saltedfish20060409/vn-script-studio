from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.config import get_settings
from app.db import Base, engine
from app.models import (  # noqa: F401
    AgentSession,
    ChapterMemoryArchive,
    ChapterMemorySlice,
    LoreCraftCard,
    Project,
    Share,
    User,
    UserSettings,
)


async def _ensure_agent_session_schema(conn) -> None:
    """Dev-friendly migrate: multi-conversation per project."""
    # Drop legacy one-session-per-project uniqueness (constraint and/or index).
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'agent_sessions_project_id_key'
              ) THEN
                ALTER TABLE agent_sessions
                  DROP CONSTRAINT agent_sessions_project_id_key;
              END IF;
            END $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            DROP INDEX IF EXISTS agent_sessions_project_id_key
            """
        )
    )
    # Recreate as non-unique if a legacy unique index remains under this name
    await conn.execute(
        text(
            """
            DROP INDEX IF EXISTS ix_agent_sessions_project_id
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE IF EXISTS agent_sessions
              ADD COLUMN IF NOT EXISTS title VARCHAR(255) DEFAULT '新对话'
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE IF EXISTS agent_sessions
              ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_agent_sessions_project_id
              ON agent_sessions (project_id)
            """
        )
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_agent_session_schema(conn)
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
