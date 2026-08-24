from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    # asyncpg: recycle before the server drops idle connections (default 5 workers
    # × 10 conns covers bursts; recycle 3600 keeps conns fresh).
    pool_size=10,
    max_overflow=10,
    pool_recycle=3600,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
