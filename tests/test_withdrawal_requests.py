from __future__ import annotations

import pytest

from bot.db import PaymentMethod, VideoStatus, WithdrawalRequestStatus

USER_ID = 501


async def create_approved_video(repository, index: int, amount: float) -> int:
    """Создаёт одобренный ролик с указанной суммой."""

    await repository.upsert_user(USER_ID, "withdrawal_user")
    video = await repository.create_video(
        USER_ID,
        f"https://youtube.com/shorts/{index}",
        "youtube",
        f"Ролик {index}",
    )
    await repository.confirm_video(video.video_id)
    await repository.update_video_views(video.video_id, 100_000)
    await repository.approve_video(video.video_id, amount)
    return video.video_id


@pytest.mark.asyncio
async def test_create_withdrawal_request_reserves_selected_videos(repository) -> None:
    """Проверяет общую сумму, снимок реквизитов и резервирование."""

    first_id = await create_approved_video(repository, 1, 250)
    second_id = await create_approved_video(repository, 2, 500)
    await repository.save_payment_details(USER_ID, PaymentMethod.CARD.value, "4111111111111234")

    request = await repository.create_withdrawal_request(USER_ID, [first_id, second_id])
    first = await repository.get_video(first_id)
    second = await repository.get_video(second_id)

    assert request.total_amount == 750
    assert request.details_tail == "1234"
    assert first is not None and first.active_withdrawal_request_id == request.request_id
    assert second is not None and second.active_withdrawal_request_id == request.request_id
    with pytest.raises(ValueError, match="not available"):
        await repository.create_withdrawal_request(USER_ID, [first_id, second_id])


@pytest.mark.asyncio
async def test_rejected_request_releases_videos(repository) -> None:
    """Проверяет возврат ролика в выбор после отказа."""

    video_id = await create_approved_video(repository, 1, 500)
    await repository.save_payment_details(USER_ID, PaymentMethod.USDT.value, "TExampleWallet1234")
    request = await repository.create_withdrawal_request(USER_ID, [video_id])

    rejected = await repository.reject_withdrawal_request(request.request_id, "Неверные реквизиты")
    video = await repository.get_video(video_id)
    repeated = await repository.create_withdrawal_request(USER_ID, [video_id])

    assert rejected.status == WithdrawalRequestStatus.REJECTED.value
    assert video is not None and video.active_withdrawal_request_id is None
    assert repeated.request_id != request.request_id


@pytest.mark.asyncio
async def test_paid_request_updates_all_videos_and_finances(repository) -> None:
    """Проверяет атомарную оплату общей заявки."""

    first_id = await create_approved_video(repository, 1, 300)
    second_id = await create_approved_video(repository, 2, 450)
    await repository.save_payment_details(USER_ID, PaymentMethod.GGSTORE.value, "account-7788")
    request = await repository.create_withdrawal_request(USER_ID, [first_id, second_id])

    paid = await repository.pay_withdrawal_request(request.request_id)
    user = await repository.get_user(USER_ID)
    first = await repository.get_video(first_id)
    second = await repository.get_video(second_id)
    history = await repository.get_user_payment_history_page(USER_ID, 1)
    withdrawals = await repository.get_user_withdrawals_page(USER_ID, 1)

    assert paid.status == WithdrawalRequestStatus.PAID.value
    assert paid.paid_at is not None
    assert user is not None and user.balance == 0
    assert user.total_withdrawn == 750
    assert first is not None and first.status == VideoStatus.PAID.value
    assert second is not None and second.status == VideoStatus.PAID.value
    assert len(history.items) == 1 and history.items[0].amount == 750
    assert len(withdrawals.items) == 2


@pytest.mark.asyncio
async def test_withdrawal_request_enforces_minimum_amount(repository) -> None:
    """Проверяет минимум вывода 300 рублей."""

    video_id = await create_approved_video(repository, 1, 250)
    await repository.save_payment_details(USER_ID, PaymentMethod.CARD.value, "4111111111111234")

    with pytest.raises(ValueError, match="below minimum"):
        await repository.create_withdrawal_request(USER_ID, [video_id])
