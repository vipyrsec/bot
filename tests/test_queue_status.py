import asyncio
import datetime as dt
from typing import cast
from unittest.mock import AsyncMock, Mock

from bot.dragonfly_services import DragonflyServices, QueueStatus
from bot.queue_status import build_queue_status_embed, fetch_cluster_queue_statuses


def snapshot() -> QueueStatus:
    sampled_at = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    return QueueStatus(
        queued=12,
        in_progress=2,
        retryable=1,
        total_backlog=13,
        oldest_queued_at=sampled_at - dt.timedelta(minutes=5),
        oldest_age_seconds=300,
        sampled_at=sampled_at,
    )


def test_fetch_cluster_queue_statuses_isolates_failures() -> None:
    production = cast("DragonflyServices", Mock())
    production.get_queue_status = AsyncMock(return_value=snapshot())
    staging = cast("DragonflyServices", Mock())
    staging.get_queue_status = AsyncMock(side_effect=RuntimeError("unavailable"))

    statuses = asyncio.run(
        fetch_cluster_queue_statuses(
            {
                "production": production,
                "staging": staging,
            }
        )
    )

    assert statuses["production"] == snapshot()
    assert isinstance(statuses["staging"], RuntimeError)


def test_build_queue_status_embed() -> None:
    now = dt.datetime(2026, 7, 25, 12, 1, tzinfo=dt.UTC)

    embed = build_queue_status_embed(
        {
            "production": snapshot(),
            "staging": RuntimeError("unavailable"),
        },
        now=now,
    )

    assert embed.title == "Dragonfly queue status"
    assert embed.timestamp == now
    assert embed.fields[0].name == "Production"
    production_value = embed.fields[0].value
    assert production_value is not None
    assert "Queued: **12**" in production_value
    assert "Backlog: **13**" in production_value
    assert embed.fields[1].name == "Staging"
    assert embed.fields[1].value == "Unavailable"


def test_build_queue_status_embed_handles_no_clusters() -> None:
    embed = build_queue_status_embed({})

    assert embed.description == "No Dragonfly clusters are configured."
