"""Shared gate + helpers for API/DB integration tests.

Design:
- The test suite must stay green on machines without a reachable PostgreSQL.
  ``DB_AVAILABLE`` is computed once at import time (short connect probe); every
  DB-backed test module uses ``pytestmark = pytest.mark.skipif(...)`` so the
  whole module is skipped gracefully when the test database is unreachable.
- The test database URL comes from ``DATABASE_URL_TEST`` and defaults to
  ``postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_test``.
- An isolated SQLAlchemy engine/session (NullPool) is created against that URL
  and injected into the FastAPI app via ``app.dependency_overrides[get_db]`` so
  requests never touch the development database configured in backend/.env.
- ``get_settings`` is also overridden so LLM-guarded endpoints see a fake API
  key and Moegirl is disabled (no network in tests).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# --------------------------------------------------------------------------
# Database URL + connectivity gate
# --------------------------------------------------------------------------

TEST_DB_URL = os.environ.get("DATABASE_URL_TEST") or (
    "postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_test"
)
_CONNECT_ARGS = {"timeout": 3}  # asyncpg connect timeout (seconds)


async def _probe_async(url: str) -> bool:
    engine = create_async_engine(url, connect_args=_CONNECT_ARGS, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _probe(url: str) -> bool:
    try:
        return asyncio.run(_probe_async(url))
    except Exception:
        return False


# Evaluated once at import; used by skipif markers at collection time.
DB_AVAILABLE = _probe(TEST_DB_URL)

engine = None  # type: ignore[var-annotated]
SessionLocal = None  # type: ignore[var-annotated]

if DB_AVAILABLE:
    # NullPool: every checkout opens/closes a fresh connection in the current
    # event loop, so tests may freely call asyncio.run() per test function.
    engine = create_async_engine(
        TEST_DB_URL, connect_args=_CONNECT_ARGS, poolclass=NullPool
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all() -> None:
    """Create the full schema on the test database (idempotent)."""
    import app.models  # noqa: F401  (registers every table on Base.metadata)
    from app.db import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def truncate_all() -> None:
    """Empty every table before a test (TRUNCATE ... CASCADE)."""
    import app.models  # noqa: F401
    from app.db import Base

    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    if not names:
        return
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency override → test database session."""
    async with SessionLocal() as session:
        yield session


# --------------------------------------------------------------------------
# Settings override (LLM guard passes, Moegirl offline, no env dependency)
# --------------------------------------------------------------------------

_TEST_SETTINGS = None


def test_settings():
    global _TEST_SETTINGS
    if _TEST_SETTINGS is None:
        from app.config import Settings

        _TEST_SETTINGS = Settings(
            database_url=TEST_DB_URL,
            deepseek_api_key="test-key",  # satisfies `if not creds["api_key"]` guards
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-chat",
            agent_craft_mode="auto",
            agent_self_review="auto",
            moegirl_enabled=False,  # lore endpoints never hit Moegirl network
            rate_limit_enabled=False,  # integration tests register many users
        )
    return _TEST_SETTINGS


def make_app():
    """Build the FastAPI app with the test DB + test settings injected."""
    from app.config import get_settings
    from app.db import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: test_settings()
    return app


def make_client(app):
    """httpx client over ASGI without a live server (works with asyncio.run)."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def register_headers(client, username: str = "tester", password: str = "secret123") -> dict:
    """Register a throwaway user and return Bearer auth headers."""
    r = await client.post(
        "/api/v1/auth/register", json={"username": username, "password": password}
    )
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
