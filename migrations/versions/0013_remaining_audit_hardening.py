"""remaining audit hardening

Revision ID: 0013_remaining_audit_hardening
Revises: 0012_runtime_quality_hardening
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_remaining_audit_hardening"
down_revision = "0012_runtime_quality_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("worker_id", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_jobs_worker_id", ["worker_id"], unique=False)
        batch.create_index("ix_jobs_lease_expires_at", ["lease_expires_at"], unique=False)

    with op.batch_alter_table("exports") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("render_fingerprint", sa.String(length=64), nullable=True))
        batch.create_index("ix_exports_render_fingerprint", ["render_fingerprint"], unique=False)

    with op.batch_alter_table("story_arc_exports") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("render_fingerprint", sa.String(length=64), nullable=True))
        batch.create_index("ix_story_arc_exports_render_fingerprint", ["render_fingerprint"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("story_arc_exports") as batch:
        batch.drop_index("ix_story_arc_exports_render_fingerprint")
        batch.drop_column("render_fingerprint")
        batch.drop_column("version")

    with op.batch_alter_table("exports") as batch:
        batch.drop_index("ix_exports_render_fingerprint")
        batch.drop_column("render_fingerprint")
        batch.drop_column("version")

    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_lease_expires_at")
        batch.drop_index("ix_jobs_worker_id")
        batch.drop_column("heartbeat_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("worker_id")
