from __future__ import annotations

from html import escape

from bot.db import WithdrawalRequest, WithdrawalRequestStatus
from bot.services.notification import format_payment_method
from bot.services.video import shorten_video_title


def format_amount(value: float) -> str:
    """Форматирует денежную сумму без лишних нулей."""

    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def build_withdrawal_request_text(request: WithdrawalRequest) -> str:
    """Формирует подробную карточку общей заявки."""

    username = "без username"
    if request.user is not None and request.user.username:
        username = f"@{request.user.username}"
    lines = [
        f"💸 <b>Заявка на вывод #{request.request_id:05d}</b>",
        "",
        f"<b>Пользователь:</b> {username} (id: {request.user_id})",
        f"<b>Сумма:</b> {format_amount(request.total_amount)} ₽",
        f"<b>Способ:</b> {format_payment_method(request.method)}",
        f"<b>Реквизиты:</b> <code>{escape(request.payment_details)}</code>",
        f"<b>Статус:</b> {format_request_status(request.status)}",
        "",
        "<b>Ролики:</b>",
    ]
    for item in request.items[:25]:
        title = shorten_video_title(item.video.title or item.video.url)
        lines.append(
            f"• <a href=\"{item.video.url}\">{title}</a> — {format_amount(item.amount)} ₽",
        )
    if len(request.items) > 25:
        lines.append(f"… и ещё {len(request.items) - 25}")
    if request.reject_reason:
        lines.extend(["", f"<b>Причина отказа:</b> {escape(request.reject_reason)}"])
    return "\n".join(lines)


def format_request_status(status: str) -> str:
    """Возвращает понятную подпись статуса заявки."""

    labels = {
        WithdrawalRequestStatus.PENDING.value: "Ожидает оплаты",
        WithdrawalRequestStatus.PAID.value: "Оплачена",
        WithdrawalRequestStatus.REJECTED.value: "Отклонена",
    }
    return labels.get(status, status)
