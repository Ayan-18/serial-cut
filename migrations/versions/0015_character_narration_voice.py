"""character narration voice

Revision ID: 0015_character_narration_voice
Revises: 0014_candidate_edit_history
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_character_narration_voice"
down_revision = "0014_candidate_edit_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch:
        batch.add_column(sa.Column("narration_voice", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("characters") as batch:
        batch.drop_column("narration_voice")
