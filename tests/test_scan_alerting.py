"""Tests for Dragonfly scan-loop alert state."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import discord

from bot.bot import Bot
from bot.dragonfly_services import Package
from bot.exts.dragonfly import dragonfly


def test_inactivity_threshold_is_inclusive() -> None:
    """The configured boundary must trigger exactly when it is reached."""
    now = datetime.now(tz=UTC)
    last_seen = now - timedelta(seconds=dragonfly.DragonflyConfig.inactivity_threshold)

    assert dragonfly.inactivity_threshold_reached(
        now=now,
        last_seen_package=last_seen,
        alert_fired=False,
    )
    assert not dragonfly.inactivity_threshold_reached(
        now=now,
        last_seen_package=last_seen,
        alert_fired=True,
    )


def test_scan_iteration_alerts_once_until_activity_resumes() -> None:
    """A continuous inactivity period must produce one alert and reset on activity."""
    bot = cast("Bot", Mock())
    cog = dragonfly.Dragonfly(bot)
    cog.last_seen_package = datetime.now(tz=UTC) - timedelta(seconds=dragonfly.DragonflyConfig.inactivity_threshold + 1)
    logs_channel = cast("discord.abc.Messageable", Mock())
    alerts_channel_mock = Mock()
    alerts_channel_mock.send = AsyncMock()
    alerts_channel = cast("discord.abc.Messageable", alerts_channel_mock)

    with patch.object(dragonfly, "run", AsyncMock(return_value=[])):
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))

    alerts_channel_mock.send.assert_awaited_once()
    assert cog.inactivity_alert_fired

    package_results = cast("list[Package]", [Mock()])
    with patch.object(dragonfly, "run", AsyncMock(return_value=package_results)):
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))

    assert not cog.inactivity_alert_fired


def test_scan_errors_alert_once_per_failure_period() -> None:
    """Repeated task errors must reach Sentry without spamming Discord."""
    bot = cast("Bot", Mock())
    cog = dragonfly.Dragonfly(bot)
    alerts_channel_mock = Mock()
    alerts_channel_mock.send = AsyncMock()
    alerts_channel = cast("discord.abc.Messageable", alerts_channel_mock)
    error = RuntimeError("test failure")

    with patch.object(dragonfly.sentry_sdk, "capture_exception") as capture_exception:
        asyncio.run(cog.handle_scan_error(error, alerts_channel))
        asyncio.run(cog.handle_scan_error(error, alerts_channel))

    assert capture_exception.call_count == 2
    alerts_channel_mock.send.assert_awaited_once()
