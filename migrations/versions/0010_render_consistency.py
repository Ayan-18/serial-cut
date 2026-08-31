from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_render_consistency"
down_revision = "0009_video_workflow_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _add_column("clip_candidates", sa.Column("edit_revision", sa.Integer(), nullable=False, server_default="0"))
    _add_column("exports", sa.Column("candidate_revision", sa.Integer(), nullable=False, server_default="0"))
    _add_column("story_arcs", sa.Column("edit_revision", sa.Integer(), nullable=False, server_default="0"))
    _add_column("story_arc_segments", sa.Column("candidate_revision", sa.Integer(), nullable=False, server_default="0"))
    _add_column("story_arc_segments", sa.Column("manually_edited", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column("story_arc_exports", sa.Column("arc_revision", sa.Integer(), nullable=False, server_default="0"))
    _add_column("story_arc_exports", sa.Column("transition_style", sa.String(length=32), nullable=False, server_default="cut"))
    _add_column("story_arc_exports", sa.Column("narration_included", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table, column in [
        ("story_arc_exports", "narration_included"),
        ("story_arc_exports", "transition_style"),
        ("story_arc_exports", "arc_revision"),
        ("story_arc_segments", "manually_edited"),
        ("story_arc_segments", "candidate_revision"),
        ("story_arcs", "edit_revision"),
        ("exports", "candidate_revision"),
        ("clip_candidates", "edit_revision"),
    ]:
        if _has_column(table, column):
            op.drop_column(table, column)


def _add_column(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {item["name"] for item in inspector.get_columns(table)}
