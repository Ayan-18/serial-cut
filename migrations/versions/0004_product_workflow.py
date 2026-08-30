from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_product_workflow"
down_revision = "0003_stage3_candidate_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {table: {item["name"] for item in inspector.get_columns(table)} for table in ("transcript_segments", "clip_candidates", "exports")}
    if "speaker_label" not in columns["transcript_segments"]:
        op.add_column("transcript_segments", sa.Column("speaker_label", sa.String(length=64), nullable=True))
    if "crop_offset_x" not in columns["clip_candidates"]:
        op.add_column("clip_candidates", sa.Column("crop_offset_x", sa.Float(), nullable=False, server_default="0"))
    if "crop_scale" not in columns["clip_candidates"]:
        op.add_column("clip_candidates", sa.Column("crop_scale", sa.Float(), nullable=False, server_default="1"))
    if "thumbnail_path" not in columns["clip_candidates"]:
        op.add_column("clip_candidates", sa.Column("thumbnail_path", sa.Text(), nullable=True))
    if "include_subtitles" not in columns["exports"]:
        op.add_column("exports", sa.Column("include_subtitles", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "preset_name" not in columns["exports"]:
        op.add_column("exports", sa.Column("preset_name", sa.String(length=64), nullable=False, server_default="youtube_shorts"))
    if "status" not in columns["exports"]:
        op.add_column("exports", sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"))

    inspector = sa.inspect(bind)
    if "ix_exports_status" not in {item["name"] for item in inspector.get_indexes("exports")}:
        op.create_index(op.f("ix_exports_status"), "exports", ["status"], unique=False)
    if "candidate_subtitles" not in inspector.get_table_names():
        op.create_table(
            "candidate_subtitles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.Float(), nullable=False),
            sa.Column("end_time", sa.Float(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("speaker_label", sa.String(length=64), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["candidate_id"], ["clip_candidates.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(bind)
    if "ix_candidate_subtitles_candidate_id" not in {item["name"] for item in inspector.get_indexes("candidate_subtitles")}:
        op.create_index(op.f("ix_candidate_subtitles_candidate_id"), "candidate_subtitles", ["candidate_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_candidate_subtitles_candidate_id"), table_name="candidate_subtitles")
    op.drop_table("candidate_subtitles")
    op.drop_index(op.f("ix_exports_status"), table_name="exports")
    op.drop_column("exports", "status")
    op.drop_column("exports", "preset_name")
    op.drop_column("exports", "include_subtitles")
    op.drop_column("clip_candidates", "thumbnail_path")
    op.drop_column("clip_candidates", "crop_scale")
    op.drop_column("clip_candidates", "crop_offset_x")
    op.drop_column("transcript_segments", "speaker_label")
