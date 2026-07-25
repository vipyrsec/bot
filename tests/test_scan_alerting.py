"""Tests for Dragonfly scan-loop alert state."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

from bot.bot import Bot
from bot.dragonfly_services import AlertingConfiguration, Package
from bot.exts.dragonfly import dragonfly


def configure_alerting_api(bot: Bot, threshold: int = 8) -> None:
    bot.dragonfly_services.get_alerting_configuration = AsyncMock(
        return_value=AlertingConfiguration(
            production_score_threshold=threshold,
            updated_at=datetime.now(tz=UTC),
            updated_by="test",
        )
    )


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
    configure_alerting_api(bot)
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


def test_scan_iteration_uses_last_known_threshold_during_configuration_outage() -> None:
    """A configuration-only outage must not stop otherwise available scanning."""
    bot = cast("Bot", Mock())
    configuration = AlertingConfiguration(
        production_score_threshold=12,
        updated_at=datetime.now(tz=UTC),
        updated_by="test",
    )
    bot.dragonfly_services.get_alerting_configuration = AsyncMock(
        side_effect=[configuration, TimeoutError("configuration unavailable")]
    )
    cog = dragonfly.Dragonfly(bot)
    logs_channel = cast("discord.abc.Messageable", Mock())
    alerts_channel = cast("discord.abc.Messageable", Mock())

    with patch.object(dragonfly, "run", AsyncMock(return_value=[])) as run:
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))

    assert [call.kwargs["score"] for call in run.await_args_list] == [12, 12]


def test_scan_iteration_requires_an_initial_threshold() -> None:
    """The bot must not invent a threshold before Mainframe responds once."""
    bot = cast("Bot", Mock())
    bot.dragonfly_services.get_alerting_configuration = AsyncMock(side_effect=TimeoutError("configuration unavailable"))
    cog = dragonfly.Dragonfly(bot)
    logs_channel = cast("discord.abc.Messageable", Mock())
    alerts_channel = cast("discord.abc.Messageable", Mock())

    with pytest.raises(TimeoutError, match="configuration unavailable"):
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))


def test_scan_errors_alert_once_per_failure_period() -> None:
    """Repeated task errors must reach Sentry without spamming Discord."""
    bot = cast("Bot", Mock())
    configure_alerting_api(bot)
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


def test_inactivity_alert_failure_preserves_successful_scan_progress() -> None:
    """Alert delivery failures must not retain the cursor or become scan errors."""
    bot = cast("Bot", Mock())
    configure_alerting_api(bot)
    cog = dragonfly.Dragonfly(bot)
    previous_cursor = cog.since
    cog.last_seen_package = datetime.now(tz=UTC) - timedelta(seconds=dragonfly.DragonflyConfig.inactivity_threshold + 1)
    cog.scan_error_alert_fired = True
    logs_channel = cast("discord.abc.Messageable", Mock())
    alerts_channel_mock = Mock()
    alerts_channel_mock.send = AsyncMock(side_effect=RuntimeError("Discord unavailable"))
    alerts_channel = cast("discord.abc.Messageable", alerts_channel_mock)

    with (
        patch.object(dragonfly, "run", AsyncMock(return_value=[])),
        patch.object(dragonfly.sentry_sdk, "capture_exception") as capture_exception,
    ):
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))

    assert cog.since > previous_cursor
    assert not cog.scan_error_alert_fired
    assert not cog.inactivity_alert_fired
    capture_exception.assert_called_once()
