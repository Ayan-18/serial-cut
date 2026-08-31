from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_video_workflow_tools"
down_revision = "0008_story_arc_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "video_scripts" not in tables:
        op.create_table(
            "video_scripts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("season_id", sa.Integer(), nullable=False),
            sa.Column("story_arc_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("style", sa.String(length=64), nullable=False, server_default="chronological"),
            sa.Column("script_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("structure_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["season_id"], ["seasons.id"]),
            sa.ForeignKeyConstraint(["story_arc_id"], ["story_arcs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "publishing_plans" not in tables:
        op.create_table(
            "publishing_plans",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("season_id", sa.Integer(), nullable=False),
            sa.Column("story_arc_id", sa.Integer(), nullable=True),
            sa.Column("story_arc_export_id", sa.Integer(), nullable=True),
            sa.Column("platform", sa.String(length=64), nullable=False, server_default="youtube_shorts"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("hashtags_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["season_id"], ["seasons.id"]),
            sa.ForeignKeyConstraint(["story_arc_id"], ["story_arcs.id"]),
            sa.ForeignKeyConstraint(["story_arc_export_id"], ["story_arc_exports.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, table, columns in [
        ("ix_video_scripts_season_id", "video_scripts", ["season_id"]),
        ("ix_video_scripts_story_arc_id", "video_scripts", ["story_arc_id"]),
        ("ix_video_scripts_status", "video_scripts", ["status"]),
        ("ix_publishing_plans_season_id", "publishing_plans", ["season_id"]),
        ("ix_publishing_plans_story_arc_id", "publishing_plans", ["story_arc_id"]),
        ("ix_publishing_plans_story_arc_export_id", "publishing_plans", ["story_arc_export_id"]),
        ("ix_publishing_plans_platform", "publishing_plans", ["platform"]),
        ("ix_publishing_plans_status", "publishing_plans", ["status"]),
    ]:
        _ensure_index(name, table, columns)


def downgrade() -> None:
    op.drop_table("publishing_plans")
    op.drop_table("video_scripts")


def _ensure_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(op.f(name), table_name, columns, unique=False)
