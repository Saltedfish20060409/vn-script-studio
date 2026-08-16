"""project_chunk_embeddings — optional pgvector semantic search index.

The table is only usable when the ``vector`` extension exists (deploy the
pgvector/pgvector image and CREATE EXTENSION vector). The migration creates the
extension when possible and otherwise no-ops the table creation so stock
PostgreSQL installs keep working (semantic search is optional).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_chunk_embeddings"
down_revision = "0009_project_comments"
branch_labels = None
depends_on = None


def _has_extension(name: str) -> bool:
    bind = op.get_bind()
    res = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_available_extensions WHERE name = :n "
            "UNION SELECT 1 FROM pg_extension WHERE extname = :n LIMIT 1"
        ),
        {"n": name},
    )
    return res.scalar() is not None


def upgrade() -> None:
    vector_ok = False
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        vector_ok = True
    except Exception:  # noqa: BLE001 — stock PG lacks the extension files
        # The failed statement aborts the transaction; roll back to a clean
        # state so the migration can complete without the table.
        try:
            op.get_bind().rollback()
        except Exception:  # noqa: BLE001
            pass
    if not vector_ok:
        return
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "project_chunk_embeddings" in insp.get_table_names():
        return
    op.create_table(
        "project_chunk_embeddings",
        sa.Column("id", sa.String(length=96), primary_key=True),
        sa.Column(
            "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_project_chunk_embeddings_project_id",
        "project_chunk_embeddings",
        ["project_id"],
    )
    # Convert the column to the pgvector type when possible.
    try:
        op.execute(
            "ALTER TABLE project_chunk_embeddings "
            "ALTER COLUMN embedding TYPE vector(1536)"
        )
    except Exception:  # noqa: BLE001 — vector type unavailable, keep float[]
        pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "project_chunk_embeddings" not in insp.get_table_names():
        return
    op.drop_index("ix_project_chunk_embeddings_project_id", table_name="project_chunk_embeddings")
    op.drop_table("project_chunk_embeddings")
