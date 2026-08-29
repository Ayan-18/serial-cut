from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_stage2_episode_artifacts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("proxy_path", sa.Text(), nullable=True))
    op.add_column("episodes", sa.Column("audio_path", sa.Text(), nullable=True))
    op.add_column("episodes", sa.Column("selected_audio_stream_index", sa.Integer(), nullable=True))
    op.add_column("episodes", sa.Column("selected_subtitle_stream_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "selected_subtitle_stream_index")
    op.drop_column("episodes", "selected_audio_stream_index")
    op.drop_column("episodes", "audio_path")
    op.drop_column("episodes", "proxy_path")

