"""Добавляет поля мониторинга просмотров видео."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_add_video_views_tracking"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет просмотры и состояние уведомлений для видео."""

    op.add_column(
        "videos",
        sa.Column("views_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "videos",
        sa.Column("last_notified_threshold", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "videos",
        sa.Column("views_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Удаляет поля мониторинга просмотров."""

    op.drop_column("videos", "views_updated_at")
    op.drop_column("videos", "last_notified_threshold")
    op.drop_column("videos", "views_count")
