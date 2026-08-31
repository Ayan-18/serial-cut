from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_job_stage_consistency"
down_revision = "0010_render_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job_stages" not in set(inspector.get_table_names()):
        op.create_table(
            "job_stages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False, server_default="queued"),
            sa.Column("started_at", sa.String(length=64), nullable=True),
            sa.Column("finished_at", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("artifact_path", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id", "name", name="uq_job_stage_name"),
        )
    _ensure_index("ix_job_stages_job_id", "job_stages", ["job_id"])


def downgrade() -> None:
    if "job_stages" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("job_stages")


def _ensure_index(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(op.f(name), table_name, columns, unique=False)
