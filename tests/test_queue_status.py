import asyncio
import datetime as dt
from collections.abc import Callable, Coroutine
from json import JSONDecodeError
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from discord.ext import commands

from bot.bot import Bot
from bot.dragonfly_services import QueueStatus
from bot.exts.dragonfly.dragonfly import Dragonfly
from bot.queue_status import build_queue_status_embed


def snapshot() -> QueueStatus:
    sampled_at = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    return QueueStatus(
        queued=12,
        in_progress=2,
        retryable=1,
        stranded=0,
        total_backlog=13,
        oldest_queued_at=sampled_at - dt.timedelta(minutes=5),
        oldest_age_seconds=300,
        sampled_at=sampled_at,
    )


def test_build_queue_status_embed() -> None:
    now = dt.datetime(2026, 7, 25, 12, 1, tzinfo=dt.UTC)

    embed = build_queue_status_embed(snapshot(), now=now)

    assert embed.title == "Dragonfly queue status"
    assert embed.timestamp == now
    assert embed.description is not None
    assert "Queued: **12**" in embed.description
    assert "Backlog: **13**" in embed.description


def test_build_queue_status_embed_handles_no_oldest_package() -> None:
    queue_snapshot = snapshot().model_copy(
        update={
            "oldest_queued_at": None,
            "oldest_age_seconds": None,
        }
    )

    embed = build_queue_status_embed(queue_snapshot)

    assert embed.description is not None
    assert "Oldest: **none**" in embed.description


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        JSONDecodeError("malformed", "", 0),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid encoding"),
    ],
)
def test_queue_status_command_reports_dependency_failure(error: Exception) -> None:
    bot = cast("Bot", Mock())
    bot.dragonfly_services.get_queue_status = AsyncMock(side_effect=error)
    cog = Dragonfly(bot)
    context_mock = Mock()
    context_mock.send = AsyncMock()
    context = cast("commands.Context[Bot]", context_mock)
    callback = cast(
        "Callable[[Dragonfly, commands.Context[Bot]], Coroutine[Any, Any, None]]",
        Dragonfly.queue_status.callback,
    )

    asyncio.run(callback(cog, context))

    context_mock.send.assert_awaited_once_with("Queue status is temporarily unavailable.")
