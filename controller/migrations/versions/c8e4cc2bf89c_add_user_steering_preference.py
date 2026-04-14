"""add_user_steering_preference

Revision ID: c8e4cc2bf89c
Revises: 8fd328614af0
Create Date: 2026-02-15 09:16:52.734638

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e4cc2bf89c"
down_revision: str | Sequence[str] | None = "8fd328614af0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_steering_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("preference_key", sa.String(), nullable=False),
        sa.Column("preference_value", sa.JSON(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_steering_preferences_user_id"),
        "user_steering_preferences",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_steering_preferences_preference_key"),
        "user_steering_preferences",
        ["preference_key"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_user_steering_preferences_preference_key"),
        table_name="user_steering_preferences",
    )
    op.drop_index(
        op.f("ix_user_steering_preferences_user_id"),
        table_name="user_steering_preferences",
    )
    op.drop_table("user_steering_preferences")
