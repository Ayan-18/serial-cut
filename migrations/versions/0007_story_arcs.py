from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_story_arcs"
down_revision = "0006_multimodal_character_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "story_arcs" not in tables:
        op.create_table(
            "story_arcs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("season_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("arc_type", sa.String(length=64), nullable=False, server_default="custom"),
            sa.Column("output_format", sa.String(length=64), nullable=False, server_default="shorts_series"),
            sa.Column("target_character_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("total_duration_seconds", sa.Float(), nullable=False, server_default="0"),
            sa.Column("plan_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["season_id"], ["seasons.id"]),
            sa.ForeignKeyConstraint(["target_character_id"], ["characters.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "story_arc_segments" not in tables:
        op.create_table(
            "story_arc_segments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("story_arc_id", sa.Integer(), nullable=False),
            sa.Column("episode_id", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.Integer(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("start_time", sa.Float(), nullable=False),
            sa.Column("end_time", sa.Float(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("role", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["candidate_id"], ["clip_candidates.id"]),
            sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"]),
            sa.ForeignKeyConstraint(["story_arc_id"], ["story_arcs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("ix_story_arcs_season_id", "story_arcs", ["season_id"])
    _ensure_index("ix_story_arcs_status", "story_arcs", ["status"])
    _ensure_index("ix_story_arcs_target_character_id", "story_arcs", ["target_character_id"])
    _ensure_index("ix_story_arc_segments_story_arc_id", "story_arc_segments", ["story_arc_id"])
    _ensure_index("ix_story_arc_segments_episode_id", "story_arc_segments", ["episode_id"])
    _ensure_index("ix_story_arc_segments_candidate_id", "story_arc_segments", ["candidate_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_story_arc_segments_candidate_id"), table_name="story_arc_segments")
    op.drop_index(op.f("ix_story_arc_segments_episode_id"), table_name="story_arc_segments")
    op.drop_index(op.f("ix_story_arc_segments_story_arc_id"), table_name="story_arc_segments")
    op.drop_index(op.f("ix_story_arcs_target_character_id"), table_name="story_arcs")
    op.drop_index(op.f("ix_story_arcs_status"), table_name="story_arcs")
    op.drop_index(op.f("ix_story_arcs_season_id"), table_name="story_arcs")
    op.drop_table("story_arc_segments")
    op.drop_table("story_arcs")


def _ensure_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(op.f(name), table_name, columns, unique=False)
