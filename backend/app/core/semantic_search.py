"""Optional pgvector semantic search over project text chunks.

Design
------
- ``is_vector_available(db)``: true when the ``vector`` extension exists in the
  connected database. postgres:16-alpine does NOT ship pgvector; deploy the
  ``pgvector/pgvector:pg16`` image instead and ``CREATE EXTENSION vector``.
- ``embed_text(text) -> List[float]``: calls the configured embedding endpoint
  (``EMBEDDING_BASE_URL`` / ``EMBEDDING_API_KEY`` / ``EMBEDDING_MODEL``, OpenAI
  compatible). Returns None when not configured or on failure.
- ``index_project_chunks(db, project_id, chunks)``: upsert vector rows.
- ``semantic_search(db, project_id, query, limit)``: vector similarity search.

When any of these prerequisites is missing, callers fall back to the
zero-dependency heuristic ranker in ``app.core.retrieval`` — the app keeps
working on stock PostgreSQL.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DIMENSION = 1536  # text-embedding-3-small default; override via settings if needed


async def is_vector_available(db: AsyncSession) -> bool:
    try:
        res = await db.execute(
            text(
                "SELECT 1 FROM pg_available_extensions WHERE name = 'vector' "
                "UNION SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1"
            )
        )
        return res.scalar() is not None
    except Exception:  # noqa: BLE001
        return False


async def ensure_vector_extension(db: AsyncSession) -> bool:
    """Try to CREATE EXTENSION IF NOT EXISTS vector; return success."""
    try:
        await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("pgvector extension unavailable: %s", exc)
        return False


async def embed_texts(
    texts: List[str],
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[List[List[float]]]:
    """Embed a batch via an OpenAI-compatible embeddings endpoint.

    Returns None when the endpoint is not configured or the call fails —
    callers fall back to heuristic ranking.
    """
    base_url = (base_url or "").strip()
    api_key = (api_key or "").strip()
    model = (model or "text-embedding-3-small").strip()
    if not base_url or not api_key:
        return None
    import httpx

    url = base_url.rstrip("/") + "/embeddings"
    payload = {"model": model, "input": texts}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        rows = (data or {}).get("data") or []
        vectors = [list(r["embedding"]) for r in rows if "embedding" in r]
        return vectors if len(vectors) == len(texts) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding call failed: %s", exc)
        return None


def _embedding_settings() -> Tuple[str, str, str]:
    from app.config import get_settings

    s = get_settings()
    return (
        (s.embedding_base_url or "").strip(),
        (s.embedding_api_key or "").strip(),
        (s.embedding_model or "text-embedding-3-small").strip(),
    )


async def index_project_chunks(
    db: AsyncSession,
    project_id: str,
    chunks: List[Dict[str, str]],
) -> int:
    """Insert/upsert vector rows for (chunk_id → text). Returns rows written.

    chunk dict shape: {"id": str, "kind": "chapter|bible|lore", "text": str}.
    """
    if not chunks or not await is_vector_available(db):
        return 0
    base_url, api_key, model = _embedding_settings()
    if not base_url or not api_key:
        return 0
    vectors = await embed_texts([c["text"] for c in chunks], base_url=base_url, api_key=api_key, model=model)
    if vectors is None:
        return 0
    written = 0
    for chunk, vec in zip(chunks, vectors):
        vec_sql = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
        # Storage id namespaces by project: chunk ids like "bible:world" or
        # "ch:<chapterId>" are not globally unique, so prefix with project_id
        # to keep the (single) primary key from colliding across projects.
        storage_id = f"{project_id}:{chunk['id']}"
        try:
            await db.execute(
                text(
                    """
                    INSERT INTO project_chunk_embeddings
                      (id, project_id, kind, text, embedding, updated_at)
                    VALUES (:id, :pid, :kind, :txt, :emb::vector, now())
                    ON CONFLICT (id) DO UPDATE SET
                      kind = EXCLUDED.kind,
                      text = EXCLUDED.text,
                      embedding = EXCLUDED.embedding,
                      updated_at = now()
                    """
                ),
                {
                    "id": storage_id,
                    "pid": project_id,
                    "kind": chunk.get("kind", ""),
                    "txt": chunk["text"],
                    "emb": vec_sql,
                },
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("embedding row write failed: %s", exc)
    if written:
        await db.commit()
    return written


async def semantic_search(
    db: AsyncSession,
    project_id: str,
    query: str,
    limit: int = 8,
) -> Optional[List[Dict[str, Any]]]:
    """Vector similarity search over indexed chunks; None when unavailable."""
    if not await is_vector_available(db):
        return None
    base_url, api_key, model = _embedding_settings()
    if not base_url or not api_key:
        return None
    vectors = await embed_texts([query], base_url=base_url, api_key=api_key, model=model)
    if not vectors:
        return None
    vec_sql = "[" + ",".join(f"{v:.8f}" for v in vectors[0]) + "]"
    try:
        res = await db.execute(
            text(
                """
                SELECT id, kind, text, 1 - (embedding <=> :emb::vector) AS score
                FROM project_chunk_embeddings
                WHERE project_id = :pid
                ORDER BY embedding <=> :emb2::vector
                LIMIT :lim
                """
            ),
            {"emb": vec_sql, "pid": project_id, "emb2": vec_sql, "lim": limit},
        )
        rows = res.all()
        return [
            {"id": r[0], "kind": r[1], "text": r[2], "score": round(float(r[3]), 4)}
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("vector search failed: %s", exc)
        return None
