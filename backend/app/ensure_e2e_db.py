"""Ensure the e2e database exists (created once; tables are built by the app).

Usage:
    python -m app.ensure_e2e_db
    E2E_DATABASE_URL=postgresql+asyncpg://... python -m app.ensure_e2e_db

The app runs ``alembic upgrade head`` + ``create_all`` at startup, so a freshly
created empty database is fully migrated when uvicorn boots.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.environ.get(
    "E2E_DATABASE_URL",
    "postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_e2e",
)


async def _ensure() -> None:
    admin_url, _, dbname = URL.rpartition("/")
    if not dbname or admin_url.endswith("//"):
        raise SystemExit(f"cannot parse database URL: {URL!r}")
    engine = create_async_engine(f"{admin_url}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            )
            if res.scalar() is None:
                await conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_ensure())
    print(f"e2e database ready: {URL}")


if __name__ == "__main__":
    main()
