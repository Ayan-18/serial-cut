from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_story_context_and_characters"
down_revision = "0004_product_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        table: {item["name"] for item in inspector.get_columns(table)}
        for table in ("seasons", "episodes", "clip_candidates")
    }
    if "story_context" not in columns["seasons"]:
        op.add_column("seasons", sa.Column("story_context", sa.Text(), nullable=False, server_default=""))
    episode_columns = columns["episodes"]
    if "story_summary" not in episode_columns:
        op.add_column("episodes", sa.Column("story_summary", sa.Text(), nullable=False, server_default=""))
    if "required_events_json" not in episode_columns:
        op.add_column(
            "episodes",
            sa.Column("required_events_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
    if "excluded_events_json" not in episode_columns:
        op.add_column(
            "episodes",
            sa.Column("excluded_events_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
    if "spoilers_allowed" not in episode_columns:
        op.add_column(
            "episodes",
            sa.Column("spoilers_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "candidate_mode" not in episode_columns:
        op.add_column(
            "episodes",
            sa.Column("candidate_mode", sa.String(length=32), nullable=False, server_default="highlights"),
        )
    candidate_columns = columns["clip_candidates"]
    if "story_order" not in candidate_columns:
        op.add_column("clip_candidates", sa.Column("story_order", sa.Integer(), nullable=True))
    if "story_role" not in candidate_columns:
        op.add_column("clip_candidates", sa.Column("story_role", sa.String(length=64), nullable=True))
    if "continuity_note" not in candidate_columns:
        op.add_column("clip_candidates", sa.Column("continuity_note", sa.Text(), nullable=True))
    if "crop_keyframes_json" not in candidate_columns:
        op.add_column(
            "clip_candidates",
            sa.Column("crop_keyframes_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )

    if "characters" not in inspector.get_table_names():
        op.create_table(
            "characters",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("season_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("aliases_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("photos_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("color", sa.String(length=16), nullable=False, server_default="#b9ddff"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["season_id"], ["seasons.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("season_id", "name", name="uq_character_season_name"),
        )
    inspector = sa.inspect(bind)
    if "ix_characters_season_id" not in {item["name"] for item in inspector.get_indexes("characters")}:
        op.create_index(op.f("ix_characters_season_id"), "characters", ["season_id"], unique=False)
    if "speaker_identities" not in inspector.get_table_names():
        op.create_table(
            "speaker_identities",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("episode_id", sa.Integer(), nullable=False),
            sa.Column("source_label", sa.String(length=64), nullable=False),
            sa.Column("character_id", sa.Integer(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("method", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
            sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("episode_id", "source_label", name="uq_speaker_identity_episode_label"),
        )
    inspector = sa.inspect(bind)
    speaker_indexes = {item["name"] for item in inspector.get_indexes("speaker_identities")}
    if "ix_speaker_identities_episode_id" not in speaker_indexes:
        op.create_index(
            op.f("ix_speaker_identities_episode_id"), "speaker_identities", ["episode_id"], unique=False
        )
    if "ix_speaker_identities_character_id" not in speaker_indexes:
        op.create_index(
            op.f("ix_speaker_identities_character_id"), "speaker_identities", ["character_id"], unique=False
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_speaker_identities_character_id"), table_name="speaker_identities")
    op.drop_index(op.f("ix_speaker_identities_episode_id"), table_name="speaker_identities")
    op.drop_table("speaker_identities")
    op.drop_index(op.f("ix_characters_season_id"), table_name="characters")
    op.drop_table("characters")
    op.drop_column("clip_candidates", "crop_keyframes_json")
    op.drop_column("clip_candidates", "continuity_note")
    op.drop_column("clip_candidates", "story_role")
    op.drop_column("clip_candidates", "story_order")
    op.drop_column("episodes", "candidate_mode")
    op.drop_column("episodes", "spoilers_allowed")
    op.drop_column("episodes", "excluded_events_json")
    op.drop_column("episodes", "required_events_json")
    op.drop_column("episodes", "story_summary")
    op.drop_column("seasons", "story_context")
