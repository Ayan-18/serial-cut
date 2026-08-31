from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_multimodal_character_identity"
down_revision = "0005_story_context_and_characters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("characters")}
    if "voice_profile_json" not in columns:
        op.add_column("characters", sa.Column("voice_profile_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("characters", "voice_profile_json")
