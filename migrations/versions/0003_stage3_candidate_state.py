from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_stage3_candidate_state"
down_revision = "0002_stage2_episode_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clip_candidates",
        sa.Column("crop_mode", sa.String(length=64), nullable=False, server_default="blurred-background"),
    )
    op.add_column("clip_candidates", sa.Column("status", sa.String(length=32), nullable=False, server_default="new"))
    op.create_index(op.f("ix_clip_candidates_status"), "clip_candidates", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_clip_candidates_status"), table_name="clip_candidates")
    op.drop_column("clip_candidates", "status")
    op.drop_column("clip_candidates", "crop_mode")

