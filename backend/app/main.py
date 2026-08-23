import asyncio
import logging
from contextlib import asynccontextmanager
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
    # Cross-worker SSE bridge (no-op without REDIS_URL).
    from app.services import event_bus

    await event_bus.start_redis_bridge()

    # Reap jobs left 'running' by a previous process crash.
    from app.core.jobs import reap_stale_jobs

    try:
        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await reap_stale_jobs(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stale job reaper skipped: %s", exc)

    try:
        yield
    finally:
        await event_bus.stop_redis_bridge()


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

    @app.middleware("http")
    async def usage_context_middleware(request, call_next):
        """Carry usage user id and browser-supplied X-LLM-* credentials."""
        from app.core.usage import set_usage_user

        user_id: str | None = None
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                try:
                    from jose import jwt as jose_jwt

                    payload = jose_jwt.decode(
                        token, settings.secret_key, algorithms=[settings.algorithm]
                    )
                    user_id = str(payload.get("sub") or "") or None
                except Exception:  # noqa: BLE001 - invalid token falls through
                    user_id = None
        set_usage_user(user_id)
        from app.core.llm_client_override import (
            parse_llm_headers,
            set_client_llm_override,
        )

        set_client_llm_override(parse_llm_headers(request.headers))
        try:
            return await call_next(request)
        finally:
            set_usage_user(None)
            set_client_llm_override(None)

    app.include_router(api_router)

    @app.get("/health")
    async def health():
        """Liveness for Cloudflare / uptime probes. Always 200 if the process is up."""
        return {"ok": True, "service": "vnss"}

    return app


app = create_app()
