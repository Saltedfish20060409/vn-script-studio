"""project_chapter_rows — chapters split out of the project blob (JSONB split, stage 1).

The projects.data blob keeps a mirror copy for backwards compatibility; the
table is the write path. Existing projects are backfilled on migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_project_chapter_rows"
down_revision = "0010_chunk_embeddings"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("project_chapter_rows"):
        op.create_table(
            "project_chapter_rows",
            sa.Column("id", sa.String(length=96), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(length=64),
                sa.ForeignKey("projects.id"),
                nullable=False,
            ),
            sa.Column("chapter_id", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("synopsis", sa.Text(), nullable=False, server_default=""),
            sa.Column("blocks", JSONB(), nullable=False, server_default="[]"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_project_chapter_rows_project_id",
            "project_chapter_rows",
            ["project_id"],
        )
        op.create_index(
            "ix_project_chapter_rows_chapter_id",
            "project_chapter_rows",
            ["chapter_id"],
        )

    # Backfill: copy chapters from projects.data into the new table.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, data->'chapters' AS chapters FROM projects "
            "WHERE jsonb_typeof(data->'chapters') = 'array'"
        )
    ).fetchall()
    for project_id, chapters in rows:
        if not chapters:
            continue
        for idx, ch in enumerate(chapters):
            if not isinstance(ch, dict) or not ch.get("id"):
                continue
            ch_id = ch["id"]
            # id = project_id:chapter_id — unique across projects
            bind.execute(
                sa.text(
                    """
                    INSERT INTO project_chapter_rows
                      (id, project_id, chapter_id, title, synopsis, blocks, sort_order, updated_at)
                    VALUES (:id, :pid, :cid, :title, :synopsis, CAST(:blocks AS jsonb), :ord, now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": f"{project_id}:{ch_id}",
                    "pid": project_id,
                    "cid": ch_id,
                    "title": ch.get("title") or "",
                    "synopsis": ch.get("synopsis") or "",
                    "blocks": _json_dumps(ch.get("blocks") or []),
                    "ord": idx,
                },
            )


def _json_dumps(value):
    import json

    return json.dumps(value, ensure_ascii=False)


def downgrade() -> None:
    op.drop_index("ix_project_chapter_rows_chapter_id", table_name="project_chapter_rows")
    op.drop_index("ix_project_chapter_rows_project_id", table_name="project_chapter_rows")
    op.drop_table("project_chapter_rows")
