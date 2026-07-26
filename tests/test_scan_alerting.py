"""Tests for Dragonfly scan-loop alert state."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest
from discord.ext import commands

from bot.bot import Bot
from bot.dragonfly_services import AlertingConfiguration, Package, ScanStatus, Suppression
from bot.exts.dragonfly import dragonfly


def configure_alerting_api(bot: Bot, threshold: int = 8) -> None:
    bot.dragonfly_services.get_alerting_configuration = AsyncMock(
        return_value=AlertingConfiguration(
            production_score_threshold=threshold,
            updated_at=datetime.now(tz=UTC),
            updated_by="test",
        )
    )


def package_result(*, version: str = "1.0.0", rules: list[str] | None = None) -> Package:
    return Package(
        scan_id="scan-id",
        name="Example_Package",
        version=version,
        status=ScanStatus.FINISHED,
        score=10,
        inspector_url=None,
        rules=rules or [],
        queued_at=datetime.now(tz=UTC),
        queued_by="test",
        reported_at=None,
        reported_by=None,
        pending_at=None,
        pending_by=None,
        finished_at=datetime.now(tz=UTC),
        finished_by="test",
        commit_hash="commit",
    )


def suppression(*, version: str = "1.0.0", rules: list[str] | None = None) -> Suppression:
    now = datetime.now(tz=UTC)
    return Suppression(
        suppression_id=uuid.uuid4(),
        package_name="example-package",
        package_version=version,
        rules=rules,
        created_at=now,
        created_by="test",
        updated_at=now,
        updated_by="test",
    )


def test_all_rule_suppression_applies_to_matching_package_version() -> None:
    assert dragonfly.is_suppressed(package_result(rules=["one"]), [suppression()])
    assert not dragonfly.is_suppressed(
        package_result(version="2.0.0", rules=["one"]),
        [suppression()],
    )


def test_scoped_suppressions_combine_without_hiding_unsuppressed_rules() -> None:
    result = package_result(rules=["one", "two"])

    assert dragonfly.is_suppressed(
        result,
        [suppression(rules=["one"]), suppression(rules=["two"])],
    )
    assert not dragonfly.is_suppressed(result, [suppression(rules=["one"])])
    assert not dragonfly.is_suppressed(package_result(rules=[]), [suppression(rules=[])])


def test_suppression_rule_command_parser() -> None:
    assert dragonfly.parse_suppression_rules(None) is None
    assert dragonfly.parse_suppression_rules("all") is None
    assert dragonfly.parse_suppression_rules("none") == []
    assert dragonfly.parse_suppression_rules(" one, two ") == ["one", "two"]

    with pytest.raises(commands.BadArgument):
        dragonfly.parse_suppression_rules("one,")
    with pytest.raises(commands.BadArgument):
        dragonfly.parse_suppression_rules("one,one")


def test_alert_suppress_button_creates_current_rule_suppression() -> None:
    bot = cast("Bot", Mock())
    result = package_result(rules=[f"false_positive_{index}" for index in range(30)])
    created = suppression(rules=result.rules)
    bot.dragonfly_services.create_suppression = AsyncMock(return_value=created)
    view = dragonfly.AlertView(bot, result)
    interaction_mock = Mock()
    interaction_mock.response.defer = AsyncMock()
    interaction_mock.edit_original_response = AsyncMock()
    interaction_mock.followup.send = AsyncMock()
    interaction = cast("discord.Interaction[Bot]", interaction_mock)

    asyncio.run(view.suppress.callback(interaction))

    button_labels = [child.label for child in view.children if isinstance(child, discord.ui.Button)]
    assert button_labels == ["Report", "Suppress"]
    assert view.suppress.style is discord.ButtonStyle.primary
    assert view.suppress.disabled
    bot.dragonfly_services.create_suppression.assert_awaited_once_with(
        result.name,
        result.version,
        result.rules,
    )
    interaction_mock.response.defer.assert_awaited_once_with()
    interaction_mock.edit_original_response.assert_awaited_once_with(view=view)
    interaction_mock.followup.send.assert_awaited_once_with(
        f"Created suppression `{created.suppression_id}` for `Example_Package==1.0.0` "
        "covering 30 current matched rules.",
        ephemeral=True,
    )


def test_alert_suppress_button_preserves_alert_when_mainframe_fails() -> None:
    bot = cast("Bot", Mock())
    result = package_result(rules=["false_positive"])
    bot.dragonfly_services.create_suppression = AsyncMock(side_effect=TimeoutError("mainframe unavailable"))
    view = dragonfly.AlertView(bot, result)
    interaction_mock = Mock()
    interaction_mock.response.defer = AsyncMock()
    interaction_mock.edit_original_response = AsyncMock()
    interaction_mock.followup.send = AsyncMock()
    interaction = cast("discord.Interaction[Bot]", interaction_mock)

    asyncio.run(view.suppress.callback(interaction))

    assert not view.suppress.disabled
    interaction_mock.edit_original_response.assert_not_awaited()
    interaction_mock.followup.send.assert_awaited_once_with(
        "The suppression could not be created. The alert remains active.",
        ephemeral=True,
    )


def test_alert_suppress_button_preserves_empty_rule_corpus() -> None:
    bot = cast("Bot", Mock())
    result = package_result(rules=[])
    created = suppression(rules=[])
    bot.dragonfly_services.create_suppression = AsyncMock(return_value=created)
    view = dragonfly.AlertView(bot, result)
    interaction_mock = Mock()
    interaction_mock.response.defer = AsyncMock()
    interaction_mock.edit_original_response = AsyncMock()
    interaction_mock.followup.send = AsyncMock()
    interaction = cast("discord.Interaction[Bot]", interaction_mock)

    asyncio.run(view.suppress.callback(interaction))

    bot.dragonfly_services.create_suppression.assert_awaited_once_with(
        result.name,
        result.version,
        [],
    )
    interaction_mock.followup.send.assert_awaited_once_with(
        f"Created suppression `{created.suppression_id}` for `Example_Package==1.0.0` "
        "covering 0 current matched rules.",
        ephemeral=True,
    )


def test_run_omits_suppressed_alert_but_keeps_scan_log() -> None:
    bot = cast("Bot", Mock())
    result = package_result(rules=["false_positive"])
    bot.dragonfly_services.get_scanned_packages = AsyncMock(return_value=[result])
    bot.dragonfly_services.get_suppressions = AsyncMock(return_value=[suppression(rules=["false_positive"])])
    alerts_channel_mock = Mock()
    alerts_channel_mock.send = AsyncMock()
    alerts_channel = cast("discord.abc.Messageable", alerts_channel_mock)
    logs_channel_mock = Mock()
    logs_channel_mock.send = AsyncMock()
    logs_channel = cast("discord.abc.Messageable", logs_channel_mock)

    scan_results = asyncio.run(
        dragonfly.run(
            bot,
            since=datetime.now(tz=UTC),
            alerts_channel=alerts_channel,
            logs_channel=logs_channel,
            score=8,
        )
    )

    assert scan_results == [result]
    bot.dragonfly_services.get_suppressions.assert_awaited_once_with("Example_Package")
    alerts_channel_mock.send.assert_not_awaited()
    logs_channel_mock.send.assert_awaited_once()


def test_run_delivers_alert_when_suppressions_are_unavailable() -> None:
    bot = cast("Bot", Mock())
    result = package_result(rules=["suspicious"])
    bot.dragonfly_services.get_scanned_packages = AsyncMock(return_value=[result])
    bot.dragonfly_services.get_suppressions = AsyncMock(side_effect=TimeoutError("mainframe unavailable"))
    alerts_channel_mock = Mock()
    alerts_channel_mock.send = AsyncMock()
    alerts_channel = cast("discord.abc.Messageable", alerts_channel_mock)
    logs_channel_mock = Mock()
    logs_channel_mock.send = AsyncMock()
    logs_channel = cast("discord.abc.Messageable", logs_channel_mock)

    with patch.object(dragonfly, "AlertView", return_value=Mock()):
        asyncio.run(
            dragonfly.run(
                bot,
                since=datetime.now(tz=UTC),
                alerts_channel=alerts_channel,
                logs_channel=logs_channel,
                score=8,
            )
        )

    alerts_channel_mock.send.assert_awaited_once()
    logs_channel_mock.send.assert_awaited_once()


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


def test_scan_iteration_uses_bootstrap_threshold_during_startup_outage() -> None:
    """A startup configuration outage must not stop scanning."""
    bot = cast("Bot", Mock())
    bot.dragonfly_services.get_alerting_configuration = AsyncMock(side_effect=TimeoutError("configuration unavailable"))
    cog = dragonfly.Dragonfly(bot)
    logs_channel = cast("discord.abc.Messageable", Mock())
    alerts_channel = cast("discord.abc.Messageable", Mock())

    with patch.object(dragonfly, "run", AsyncMock(return_value=[])) as run:
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))

    run.assert_awaited_once()
    assert run.await_args_list[0].kwargs["score"] == dragonfly.DragonflyConfig.bootstrap_threshold


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
