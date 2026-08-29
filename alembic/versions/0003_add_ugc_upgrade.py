"""Добавляет подтверждение, метрики и общие заявки на вывод."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_add_ugc_upgrade"
down_revision = "0002_add_video_views_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Расширяет схему без изменения старых финансовых записей."""

    op.create_table(
        "withdrawal_requests",
        sa.Column("request_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("payment_details", sa.Text(), nullable=False),
        sa.Column("details_tail", sa.String(length=4), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(sa.Column("likes_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("comments_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("shares_count", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("payout_notified_at", sa.DateTime(timezone=True), nullable=True),
        )
        batch_op.add_column(
            sa.Column("active_withdrawal_request_id", sa.Integer(), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_videos_active_withdrawal_request",
            "withdrawal_requests",
            ["active_withdrawal_request_id"],
            ["request_id"],
        )
    op.create_table(
        "withdrawal_request_items",
        sa.Column("item_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["withdrawal_requests.request_id"]),
        sa.ForeignKeyConstraint(["video_id"], ["videos.video_id"]),
        sa.PrimaryKeyConstraint("item_id"),
        sa.UniqueConstraint("request_id", "video_id", name="uq_withdrawal_item_video"),
    )


def downgrade() -> None:
    """Удаляет новые таблицы и поля."""

    op.drop_table("withdrawal_request_items")
    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_constraint(
            "fk_videos_active_withdrawal_request",
            type_="foreignkey",
        )
        batch_op.drop_column("active_withdrawal_request_id")
        batch_op.drop_column("payout_notified_at")
        batch_op.drop_column("shares_count")
        batch_op.drop_column("comments_count")
        batch_op.drop_column("likes_count")
    op.drop_table("withdrawal_requests")
