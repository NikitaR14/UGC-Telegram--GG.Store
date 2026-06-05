from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

PAYOUT_RATE = 250
MIN_WITHDRAWAL = 300
WITHDRAWAL_DAYS = 3
DETAILS_TAIL_LENGTH = 4
DEFAULT_LAST_NOTIFIED_THRESHOLD = 0


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


class VideoStatus(StrEnum):
    """Допустимые статусы заявки на видео."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class PaymentMethod(StrEnum):
    """Поддерживаемые способы вывода средств."""

    CARD = "card"
    USDT = "usdt"
    GGSTORE = "ggstore"


class User(Base):
    """Пользователь Telegram-бота."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    total_withdrawn: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        server_default="0",
    )
    payment_method: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    payment_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_admin_session: Mapped[bool] = mapped_column(default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    videos: Mapped[list["Video"]] = relationship(back_populates="user")
    withdrawals: Mapped[list["Withdrawal"]] = relationship(back_populates="user")
    payment_history: Mapped[list["PaymentHistory"]] = relationship(back_populates="user")


class Video(Base):
    """Заявка пользователя на публикацию видео."""

    __tablename__ = "videos"

    video_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=VideoStatus.PENDING.value,
        server_default=VideoStatus.PENDING.value,
        nullable=False,
    )
    payout_amount: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        server_default="0",
        nullable=False,
    )
    views_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    last_notified_threshold: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_LAST_NOTIFIED_THRESHOLD,
        server_default=str(DEFAULT_LAST_NOTIFIED_THRESHOLD),
        nullable=False,
    )
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    views_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="videos")
    withdrawals: Mapped[list["Withdrawal"]] = relationship(back_populates="video")


class Withdrawal(Base):
    """Подтверждённая выплата по одобренной заявке."""

    __tablename__ = "withdrawals"

    withdrawal_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.video_id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    details_tail: Mapped[str] = mapped_column(String(DETAILS_TAIL_LENGTH), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="withdrawals")
    video: Mapped["Video"] = relationship(back_populates="withdrawals")


class PaymentHistory(Base):
    """История подтверждённых выплат пользователя."""

    __tablename__ = "payment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="payment_history")
