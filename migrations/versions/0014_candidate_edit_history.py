"""candidate edit history

Revision ID: 0014_candidate_edit_history
Revises: 0013_remaining_audit_hardening
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_candidate_edit_history"
down_revision = "0013_remaining_audit_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_edit_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("clip_candidates.id"), nullable=False),
        sa.Column("edit_revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candidate_edit_snapshots_candidate_id",
        "candidate_edit_snapshots",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_edit_snapshots_candidate_id", table_name="candidate_edit_snapshots")
    op.drop_table("candidate_edit_snapshots")
