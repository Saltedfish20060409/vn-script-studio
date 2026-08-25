import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


def _access_logger() -> logging.Logger:
    """返回自带 handler 的 vnss.access logger（幂等，可在多次 create_app 间复用）。

    为什么必须自带 handler：`app.main` 在模块导入时（`app = create_app()`）创建
    vnss.access，而 uvicorn 之后才执行自己的 dictConfig（默认
    disable_existing_loggers=True）——导入期创建的 logger 会被静默禁用，
    info() 全部丢弃（本仓库此前线上 40 分钟零访问日志即为实证）。显式挂上
    StreamHandler + INFO 级别 + 关闭 propagate，不再依赖 root/uvicorn 配置。
    """
    lg = logging.getLogger("vnss.access")
    if not lg.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    return lg


def _alembic_upgrade_sync() -> None:
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail fast on schema migration errors — a swallowed alembic failure
    # silently drifts the schema. 0001 is an idempotent baseline, so a fresh
    # DB also upgrades cleanly.
    await asyncio.to_thread(_alembic_upgrade_sync)
    # create_all stays as an idempotent backstop for tables created outside
    # alembic (e.g. legacy); it never drops or alters existing columns.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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

    @app.middleware("http")
    async def access_log_middleware(request, call_next):
        """结构化访问日志：每请求一行 JSON（method/path/status/耗时ms）。

        user_id 从 request.state 尽力取，取不到就省略（现有中间件不写 state）。
        """
        access_logger = _access_logger()
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            record = {
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "ms": elapsed_ms,
            }
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                record["user_id"] = str(user_id)
            access_logger.info(json.dumps(record, ensure_ascii=False))

    app.include_router(api_router)

    @app.get("/health")
    async def health():
        """Liveness for Cloudflare / uptime probes. Always 200 if the process is up."""
        return {"ok": True, "service": "vnss"}

    return app


app = create_app()
