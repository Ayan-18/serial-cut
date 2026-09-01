"""runtime quality hardening

Revision ID: 0012_runtime_quality_hardening
Revises: 0011_job_stage_consistency
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_runtime_quality_hardening"
down_revision = "0011_job_stage_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("progress_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS transcript_search USING fts5("
        "text, content='transcript_segments', content_rowid='id', tokenize='unicode61')"
    )
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS candidate_search USING fts5("
        "title, description, moment_type, rationale, continuity_note, "
        "content='clip_candidates', content_rowid='id', tokenize='unicode61')"
    )
    _create_fts_triggers()
    op.execute("INSERT INTO transcript_search(transcript_search) VALUES('rebuild')")
    op.execute("INSERT INTO candidate_search(candidate_search) VALUES('rebuild')")


def downgrade() -> None:
    for trigger in (
        "transcript_search_ai", "transcript_search_ad", "transcript_search_au",
        "candidate_search_ai", "candidate_search_ad", "candidate_search_au",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("DROP TABLE IF EXISTS transcript_search")
    op.execute("DROP TABLE IF EXISTS candidate_search")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
        batch.drop_column("progress_message")


def _create_fts_triggers() -> None:
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS transcript_search_ai AFTER INSERT ON transcript_segments BEGIN "
        "INSERT INTO transcript_search(rowid, text) VALUES (new.id, new.text); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS transcript_search_ad AFTER DELETE ON transcript_segments BEGIN "
        "INSERT INTO transcript_search(transcript_search, rowid, text) VALUES ('delete', old.id, old.text); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS transcript_search_au AFTER UPDATE ON transcript_segments BEGIN "
        "INSERT INTO transcript_search(transcript_search, rowid, text) VALUES ('delete', old.id, old.text); "
        "INSERT INTO transcript_search(rowid, text) VALUES (new.id, new.text); END"
    )
    columns = "title, description, moment_type, rationale, continuity_note"
    new_values = "new.title, new.description, new.moment_type, new.rationale, new.continuity_note"
    old_values = "old.title, old.description, old.moment_type, old.rationale, old.continuity_note"
    op.execute(
        f"CREATE TRIGGER IF NOT EXISTS candidate_search_ai AFTER INSERT ON clip_candidates BEGIN "
        f"INSERT INTO candidate_search(rowid, {columns}) VALUES (new.id, {new_values}); END"
    )
    op.execute(
        f"CREATE TRIGGER IF NOT EXISTS candidate_search_ad AFTER DELETE ON clip_candidates BEGIN "
        f"INSERT INTO candidate_search(candidate_search, rowid, {columns}) "
        f"VALUES ('delete', old.id, {old_values}); END"
    )
    op.execute(
        f"CREATE TRIGGER IF NOT EXISTS candidate_search_au AFTER UPDATE ON clip_candidates BEGIN "
        f"INSERT INTO candidate_search(candidate_search, rowid, {columns}) "
        f"VALUES ('delete', old.id, {old_values}); "
        f"INSERT INTO candidate_search(rowid, {columns}) VALUES (new.id, {new_values}); END"
    )
