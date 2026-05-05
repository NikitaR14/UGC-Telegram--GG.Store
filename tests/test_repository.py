from __future__ import annotations

import pytest

from bot.db.models import PaymentMethod, VideoStatus
from bot.db.repository import DEFAULT_PAGE_SIZE, BotRepository


TEST_USER_ID = 1001
TEST_PAYOUT_AMOUNT = 1500.0
SECOND_USER_ID = 2002


async def create_pending_video(repository: BotRepository) -> int:
    """Создаёт пользователя и pending-заявку для тестовых сценариев."""

    await repository.upsert_user(TEST_USER_ID, "tester")
    video = await repository.create_video(
        user_id=TEST_USER_ID,
        url="https://youtube.com/shorts/example123",
        platform="youtube",
        title="Тестовое видео",
    )
    return video.video_id


async def create_pending_video_for_user(
    repository: BotRepository,
    user_id: int,
    index: int,
) -> int:
    """Создаёт pending-заявку для указанного пользователя."""

    await repository.upsert_user(user_id, f"user_{user_id}")
    video = await repository.create_video(
        user_id=user_id,
        url=f"https://youtube.com/shorts/video{index}",
        platform="youtube",
        title=f"Видео #{index}",
    )
    return video.video_id


@pytest.mark.asyncio
async def test_approve_video_updates_status_and_balance(
    repository: BotRepository,
) -> None:
    """Проверяет начисление баланса после одобрения заявки."""

    video_id = await create_pending_video(repository)

    approved_video = await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT)
    user = await repository.get_user(TEST_USER_ID)

    assert approved_video.status == VideoStatus.APPROVED.value
    assert approved_video.payout_amount == TEST_PAYOUT_AMOUNT
    assert user is not None
    assert user.balance == TEST_PAYOUT_AMOUNT
    assert user.total_withdrawn == 0.0


@pytest.mark.asyncio
async def test_reject_video_updates_status_and_reason(
    repository: BotRepository,
) -> None:
    """Проверяет сохранение причины отказа в отклонённой заявке."""

    video_id = await create_pending_video(repository)

    rejected_video = await repository.reject_video(video_id, "Не подошёл баннер")

    assert rejected_video.status == VideoStatus.REJECTED.value
    assert rejected_video.reject_reason == "Не подошёл баннер"


@pytest.mark.asyncio
async def test_mark_video_paid_creates_withdrawal_and_updates_user_totals(
    repository: BotRepository,
) -> None:
    """Проверяет полный happy-path выплаты по одобренной заявке."""

    video_id = await create_pending_video(repository)
    await repository.save_payment_details(
        TEST_USER_ID,
        PaymentMethod.CARD.value,
        "5555444433332222",
    )
    await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT)

    withdrawal = await repository.mark_video_paid(video_id)
    user = await repository.get_user(TEST_USER_ID)
    paid_video = await repository.get_video(video_id)
    payment_history_page = await repository.get_user_payment_history_page(TEST_USER_ID, page=1)

    assert withdrawal.amount == TEST_PAYOUT_AMOUNT
    assert withdrawal.method == PaymentMethod.CARD.value
    assert withdrawal.details_tail == "2222"
    assert len(payment_history_page.items) == 1
    assert payment_history_page.items[0].amount == TEST_PAYOUT_AMOUNT
    assert payment_history_page.items[0].method == PaymentMethod.CARD.value
    assert payment_history_page.items[0].details == "5555444433332222"
    assert user is not None
    assert user.balance == 0.0
    assert user.total_withdrawn == TEST_PAYOUT_AMOUNT
    assert paid_video is not None
    assert paid_video.status == VideoStatus.PAID.value


@pytest.mark.asyncio
async def test_mark_video_paid_requires_payment_details(
    repository: BotRepository,
) -> None:
    """Проверяет защиту от выплаты без привязанных реквизитов."""

    video_id = await create_pending_video(repository)
    await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT)

    with pytest.raises(ValueError, match="has no payment details"):
        await repository.mark_video_paid(video_id)

    user = await repository.get_user(TEST_USER_ID)
    video = await repository.get_video(video_id)

    assert user is not None
    assert user.balance == TEST_PAYOUT_AMOUNT
    assert user.total_withdrawn == 0.0
    assert video is not None
    assert video.status == VideoStatus.APPROVED.value


@pytest.mark.asyncio
async def test_approve_video_rejects_invalid_status_transition(
    repository: BotRepository,
) -> None:
    """Проверяет защиту от повторного одобрения уже обработанной заявки."""

    video_id = await create_pending_video(repository)
    await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT)

    with pytest.raises(ValueError, match="must be in status pending"):
        await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT)


@pytest.mark.asyncio
async def test_reject_video_rejects_invalid_status_transition(
    repository: BotRepository,
) -> None:
    """Проверяет защиту от отклонения уже одобренной заявки."""

    video_id = await create_pending_video(repository)
    await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT)

    with pytest.raises(ValueError, match="must be in status pending"):
        await repository.reject_video(video_id, "Поздний отказ")


@pytest.mark.asyncio
async def test_mark_video_paid_rejects_invalid_status_transition(
    repository: BotRepository,
) -> None:
    """Проверяет защиту от выплаты заявки не в статусе approved."""

    video_id = await create_pending_video(repository)
    await repository.save_payment_details(
        TEST_USER_ID,
        PaymentMethod.CARD.value,
        "5555444433332222",
    )

    with pytest.raises(ValueError, match="must be in status approved"):
        await repository.mark_video_paid(video_id)


@pytest.mark.asyncio
async def test_mark_video_paid_rejects_double_payment(
    repository: BotRepository,
) -> None:
    """Проверяет защиту от повторной выплаты по одной заявке."""

    video_id = await create_pending_video(repository)
    await repository.save_payment_details(
        TEST_USER_ID,
        PaymentMethod.CARD.value,
        "5555444433332222",
    )
    await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT)
    await repository.mark_video_paid(video_id)

    with pytest.raises(ValueError, match="must be in status approved"):
        await repository.mark_video_paid(video_id)


@pytest.mark.asyncio
async def test_get_user_videos_page_returns_expected_pagination(
    repository: BotRepository,
) -> None:
    """Проверяет пагинацию заявок пользователя по страницам."""

    for index in range(DEFAULT_PAGE_SIZE + 2):
        await create_pending_video_for_user(repository, TEST_USER_ID, index)

    first_page = await repository.get_user_videos_page(TEST_USER_ID, page=1)
    second_page = await repository.get_user_videos_page(TEST_USER_ID, page=2)

    assert first_page.page == 1
    assert first_page.total_pages == 2
    assert len(first_page.items) == DEFAULT_PAGE_SIZE
    assert second_page.page == 2
    assert second_page.total_pages == 2
    assert len(second_page.items) == 2


@pytest.mark.asyncio
async def test_get_user_withdrawals_page_returns_expected_pagination(
    repository: BotRepository,
) -> None:
    """Проверяет пагинацию истории выплат пользователя."""

    await repository.upsert_user(TEST_USER_ID, "tester")
    await repository.save_payment_details(
        TEST_USER_ID,
        PaymentMethod.CARD.value,
        "5555444433332222",
    )
    for index in range(DEFAULT_PAGE_SIZE + 1):
        video_id = await create_pending_video_for_user(repository, TEST_USER_ID, index)
        await repository.approve_video(video_id, TEST_PAYOUT_AMOUNT + index)
        await repository.mark_video_paid(video_id)

    first_page = await repository.get_user_withdrawals_page(TEST_USER_ID, page=1)
    second_page = await repository.get_user_withdrawals_page(TEST_USER_ID, page=2)

    assert first_page.page == 1
    assert first_page.total_pages == 2
    assert len(first_page.items) == DEFAULT_PAGE_SIZE
    assert second_page.page == 2
    assert second_page.total_pages == 2
    assert len(second_page.items) == 1


@pytest.mark.asyncio
async def test_get_admin_videos_page_filters_by_status(
    repository: BotRepository,
) -> None:
    """Проверяет, что админская пагинация возвращает заявки только нужного статуса."""

    approved_video_id = await create_pending_video(repository)
    rejected_video_id = await create_pending_video_for_user(repository, SECOND_USER_ID, 1)
    await repository.approve_video(approved_video_id, TEST_PAYOUT_AMOUNT)
    await repository.reject_video(rejected_video_id, "Нарушение требований")

    approved_page = await repository.get_admin_videos_page(
        VideoStatus.APPROVED.value,
        page=1,
    )
    rejected_page = await repository.get_admin_videos_page(
        VideoStatus.REJECTED.value,
        page=1,
    )

    assert len(approved_page.items) == 1
    assert approved_page.items[0].video_id == approved_video_id
    assert len(rejected_page.items) == 1
    assert rejected_page.items[0].video_id == rejected_video_id


@pytest.mark.asyncio
async def test_set_admin_session_updates_user_flag(
    repository: BotRepository,
) -> None:
    """Проверяет включение и выключение admin-сессии у пользователя."""

    await repository.upsert_user(TEST_USER_ID, "tester")

    await repository.set_admin_session(TEST_USER_ID, True)
    enabled_user = await repository.get_user(TEST_USER_ID)
    await repository.set_admin_session(TEST_USER_ID, False)
    disabled_user = await repository.get_user(TEST_USER_ID)

    assert enabled_user is not None
    assert enabled_user.is_admin_session is True
    assert disabled_user is not None
    assert disabled_user.is_admin_session is False


@pytest.mark.asyncio
async def test_set_admin_session_creates_missing_user(
    repository: BotRepository,
) -> None:
    """Проверяет, что admin-сессия может создать отсутствующего пользователя."""

    await repository.set_admin_session(SECOND_USER_ID, True)
    user = await repository.get_user(SECOND_USER_ID)

    assert user is not None
    assert user.is_admin_session is True
