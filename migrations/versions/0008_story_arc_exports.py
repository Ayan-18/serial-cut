from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_story_arc_exports"
down_revision = "0007_story_arcs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "story_arc_exports" not in inspector.get_table_names():
        op.create_table(
            "story_arc_exports",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("story_arc_id", sa.Integer(), nullable=False),
            sa.Column("output_path", sa.Text(), nullable=False),
            sa.Column("metadata_path", sa.Text(), nullable=True),
            sa.Column("cover_path", sa.Text(), nullable=True),
            sa.Column("width", sa.Integer(), nullable=False, server_default="1080"),
            sa.Column("height", sa.Integer(), nullable=False, server_default="1920"),
            sa.Column("include_subtitles", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("preset_name", sa.String(length=64), nullable=False, server_default="youtube_shorts"),
            sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["story_arc_id"], ["story_arcs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("ix_story_arc_exports_story_arc_id", "story_arc_exports", ["story_arc_id"])
    _ensure_index("ix_story_arc_exports_status", "story_arc_exports", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_story_arc_exports_status"), table_name="story_arc_exports")
    op.drop_index(op.f("ix_story_arc_exports_story_arc_id"), table_name="story_arc_exports")
    op.drop_table("story_arc_exports")


def _ensure_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(op.f(name), table_name, columns, unique=False)
