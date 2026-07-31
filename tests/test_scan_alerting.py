"""Tests for Dragonfly scan-loop alert state."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from bot.bot import Bot
from bot.constants import DragonflyConfig
from bot.dragonfly_services import (
    AlertingConfiguration,
    OpenGrepFinding,
    OpenGrepResult,
    Package,
    ScanStatus,
    Suppression,
)
from bot.exts.dragonfly import dragonfly


def configure_alerting_api(bot: Bot, threshold: int = 8) -> None:
    bot.dragonfly_services.get_alerting_configuration = AsyncMock(
        return_value=AlertingConfiguration(
            production_score_threshold=threshold,
            updated_at=datetime.now(tz=UTC),
            updated_by="test",
        )
    )


def test_opengrep_bot_polling_is_staging_only() -> None:
    config_type = type(DragonflyConfig)
    with pytest.raises(ValueError, match="staging Dragonfly API URL"):
        config_type(
            api_url="https://dragonfly.vipyrsec.com",
            opengrep_shadow_enabled=True,
        )

    config = config_type(
        api_url="https://dragonfly-staging.vipyrsec.com",
        opengrep_shadow_enabled=True,
    )

    assert config.opengrep_shadow_enabled


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


def opengrep_result(
    *,
    findings: list[OpenGrepFinding] | None = None,
    discord_message_id: int | None = None,
    discord_thread_id: int | None = None,
    published_chunks: int = 0,
) -> OpenGrepResult:
    return OpenGrepResult(
        scan_id=uuid.uuid4(),
        name="example-package",
        version="1.0.0",
        status=ScanStatus.FINISHED,
        commit="a" * 40,
        duration_ms=42,
        findings=findings or [],
        fail_reason=None,
        finished_at=datetime.now(tz=UTC),
        publication_id=uuid.uuid4(),
        discord_message_id=discord_message_id,
        discord_thread_id=discord_thread_id,
        published_chunks=published_chunks,
    )


def opengrep_finding(index: int = 0, *, message: str = "Behavioral evidence.") -> OpenGrepFinding:
    return OpenGrepFinding(
        rule_id=f"python-flow-example-{index}",
        path=f"src/module_{index}.py",
        start_line=3,
        end_line=7,
        message=message,
        severity="ERROR",
        evidence="flow",
        confidence="high",
        execution_context="import_time_same_file_call",
        inspector_url=f"https://inspector.example/src/module_{index}.py",
    )


def test_opengrep_thread_chunks_are_bounded_and_neutralize_mentions() -> None:
    findings = [
        opengrep_finding(
            index,
            message=f"evidence @{index} `" + ("x" * 1200),
        )
        for index in range(5)
    ]

    chunks = dragonfly.build_opengrep_thread_chunks(findings)

    assert len(chunks) > 1
    assert all(len(chunk) <= dragonfly.OPENGREP_THREAD_CHUNK_LIMIT for chunk in chunks)
    assert all("@\u200b" in chunk for chunk in chunks)
    assert all("`x" not in chunk for chunk in chunks)

    oversized_header = opengrep_finding()
    oversized_header.path = "p" * 5000
    rendered = dragonfly.build_opengrep_thread_chunks([oversized_header])
    assert len(rendered) == 1
    assert len(rendered[0]) == dragonfly.OPENGREP_THREAD_CHUNK_LIMIT


def test_publish_opengrep_result_acks_after_complete_thread() -> None:
    bot = cast("Bot", Mock())
    bot.dragonfly_services.checkpoint_opengrep_publication = AsyncMock()
    bot.dragonfly_services.acknowledge_opengrep_result = AsyncMock()
    thread = Mock(spec=discord.Thread)
    thread.id = 200
    thread.send = AsyncMock()
    message = Mock()
    message.id = 100
    message.create_thread = AsyncMock(return_value=thread)
    channel = Mock()
    channel.send = AsyncMock(return_value=message)
    result = opengrep_result(findings=[opengrep_finding(index) for index in range(3)])

    asyncio.run(
        dragonfly.publish_opengrep_result(
            bot,
            cast("discord.TextChannel", channel),
            result,
        )
    )

    channel.send.assert_awaited_once()
    summary = channel.send.await_args.kwargs["embed"]
    assert summary.title == "OpenGrep shadow: example-package @ 1.0.0"
    assert summary.description is not None
    assert "not a production verdict" in summary.description
    message.create_thread.assert_awaited_once()
    assert thread.send.await_count == 1
    assert bot.dragonfly_services.checkpoint_opengrep_publication.await_count == 3
    bot.dragonfly_services.acknowledge_opengrep_result.assert_awaited_once_with(result)


def test_publish_opengrep_result_does_not_ack_partial_thread() -> None:
    bot = cast("Bot", Mock())
    bot.dragonfly_services.checkpoint_opengrep_publication = AsyncMock()
    bot.dragonfly_services.acknowledge_opengrep_result = AsyncMock()
    thread = Mock(spec=discord.Thread)
    thread.id = 200
    thread.send = AsyncMock(side_effect=RuntimeError("Discord unavailable"))
    message = Mock()
    message.id = 100
    message.create_thread = AsyncMock(return_value=thread)
    channel = Mock()
    channel.send = AsyncMock(return_value=message)
    result = opengrep_result(findings=[opengrep_finding()])

    with pytest.raises(RuntimeError, match="Discord unavailable"):
        asyncio.run(
            dragonfly.publish_opengrep_result(
                bot,
                cast("discord.TextChannel", channel),
                result,
            )
        )

    bot.dragonfly_services.acknowledge_opengrep_result.assert_not_awaited()


def test_publish_opengrep_result_resumes_recorded_thread_progress() -> None:
    bot_mock = Mock()
    bot = cast("Bot", bot_mock)
    bot.dragonfly_services.checkpoint_opengrep_publication = AsyncMock()
    bot.dragonfly_services.acknowledge_opengrep_result = AsyncMock()
    thread = Mock(spec=discord.Thread)
    thread.send = AsyncMock()
    bot_mock.get_channel.return_value = thread
    channel = Mock()
    channel.fetch_message = AsyncMock()
    channel.send = AsyncMock()
    result = opengrep_result(
        findings=[opengrep_finding(index) for index in range(3)],
        discord_message_id=100,
        discord_thread_id=200,
        published_chunks=1,
    )

    asyncio.run(
        dragonfly.publish_opengrep_result(
            bot,
            cast("discord.TextChannel", channel),
            result,
        )
    )

    channel.send.assert_not_awaited()
    channel.fetch_message.assert_awaited_once_with(100)
    assert thread.send.await_count == 0
    bot.dragonfly_services.acknowledge_opengrep_result.assert_awaited_once_with(result)


def test_publish_opengrep_results_isolates_each_result_failure() -> None:
    bot = cast("Bot", Mock())
    channel = cast("discord.TextChannel", Mock())
    results = [opengrep_result(), opengrep_result()]

    with (
        patch.object(
            dragonfly,
            "publish_opengrep_result",
            AsyncMock(side_effect=[RuntimeError("first failed"), None]),
        ) as publish,
        patch.object(dragonfly.sentry_sdk, "capture_exception") as capture_exception,
    ):
        asyncio.run(dragonfly.publish_opengrep_results(bot, channel, results))

    assert publish.await_count == 2
    capture_exception.assert_called_once()


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


def test_all_rule_suppression_applies_only_to_matching_package_version() -> None:
    assert dragonfly.is_suppressed(package_result(rules=["one"]), [suppression()])
    assert not dragonfly.is_suppressed(
        package_result(version="2.0.0", rules=["one"]),
        [suppression()],
    )


def test_scoped_suppressions_apply_across_versions_and_combine() -> None:
    result = package_result(version="3.0.0", rules=["one", "two"])

    assert dragonfly.is_suppressed(
        result,
        [
            suppression(version="1.0.0", rules=["one"]),
            suppression(version="2.0.0", rules=["two"]),
        ],
    )
    assert not dragonfly.is_suppressed(result, [suppression(rules=["one"])])
    assert not dragonfly.is_suppressed(package_result(rules=[]), [suppression(rules=[])])


def test_scoped_suppression_does_not_apply_to_another_package() -> None:
    other_package = suppression(rules=["one"])
    other_package.package_name = "different-package"

    assert not dragonfly.is_suppressed(package_result(rules=["one"]), [other_package])


def test_suppression_rule_command_parser() -> None:
    assert dragonfly.parse_suppression_rules(None) is None
    assert dragonfly.parse_suppression_rules("all") is None
    assert dragonfly.parse_suppression_rules("none") == []
    assert dragonfly.parse_suppression_rules(" one, two ") == ["one", "two"]

    with pytest.raises(commands.BadArgument):
        dragonfly.parse_suppression_rules("one,")
    with pytest.raises(commands.BadArgument):
        dragonfly.parse_suppression_rules("one,one")


def test_suppressions_are_registered_as_slash_commands_only() -> None:
    group = dragonfly.Dragonfly.suppressions

    assert isinstance(group, app_commands.Group)
    assert group.name == "suppressions"
    assert {command.name for command in group.commands} == {
        "clear",
        "create",
        "delete",
        "list",
        "modify",
        "view",
    }
    assert all(command.checks for command in group.commands if isinstance(command, app_commands.Command))
    assert "suppressions" not in {command.name for command in dragonfly.Dragonfly.__cog_commands__}


def test_create_suppression_slash_command_defaults_to_all_rules() -> None:
    bot = cast("Bot", Mock())
    created = suppression()
    bot.dragonfly_services.create_suppression = AsyncMock(return_value=created)

    interaction = _invoke_suppression_command("create", bot, "Example_Package", "1.0.0")

    bot.dragonfly_services.create_suppression.assert_awaited_once_with(
        "Example_Package",
        "1.0.0",
        None,
    )
    interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
    sent_embed = interaction.followup.send.await_args.kwargs["embed"]
    assert sent_embed.title == "Suppression created"
    assert sent_embed.description == "**Package:** `example-package`\n**Version:** `1.0.0`"
    assert [(field.name, field.value) for field in sent_embed.fields[:3]] == [
        ("Scope", "All rules"),
        ("Rules", "Every current and future alert rule."),
        ("Suppression ID", f"`{created.suppression_id}`"),
    ]
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


def test_suppression_embeds_bound_large_rule_corpora_and_lists() -> None:
    rules = [f"false_positive_rule_{index:02d}" for index in range(30)]
    suppressions = [suppression(version=f"1.0.{index}", rules=rules) for index in range(11)]

    details = dragonfly.build_suppression_embed(
        suppressions[0],
        title="Suppression details",
    )
    pages = dragonfly.build_suppression_list_embeds("example-package", suppressions)

    assert details.title == "Suppression details"
    assert details.fields[0].value == "30 selected rules"
    assert details.fields[1].value is not None
    assert len(details.fields[1].value) <= 900
    assert len(pages) == 2
    assert [len(page.fields) for page in pages] == [8, 3]
    assert [page.footer.text for page in pages] == ["Page 1/2", "Page 2/2"]
    assert all(len(page) <= 6000 for page in pages)
    assert all(field.value is not None and len(field.value) <= 1024 for page in pages for field in page.fields)


def test_suppression_list_pages_stay_within_aggregate_embed_limit() -> None:
    suppressions = [
        suppression(version=f"{index}-{'v' * 500}", rules=[f"{rule}-{'r' * 500}" for rule in range(30)])
        for index in range(9)
    ]

    pages = dragonfly.build_suppression_list_embeds("p" * 500, suppressions)

    assert [len(page.fields) for page in pages] == [8, 1]
    assert all(len(page) <= 6000 for page in pages)


def test_list_suppressions_slash_command_sends_embed_pages() -> None:
    bot = cast("Bot", Mock())
    suppressions = [suppression(version=f"1.0.{index}", rules=["one", "two"]) for index in range(11)]
    bot.dragonfly_services.get_suppressions = AsyncMock(return_value=suppressions)

    interaction = _invoke_suppression_command("list", bot, "example-package")

    interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
    assert interaction.followup.send.await_count == 2
    sent_embeds = [call.kwargs["embed"] for call in interaction.followup.send.await_args_list]
    assert [embed.footer.text for embed in sent_embeds] == ["Page 1/2", "Page 2/2"]
    assert all(call.kwargs["ephemeral"] is True for call in interaction.followup.send.await_args_list)


def test_suppression_group_reports_deferred_service_failure() -> None:
    group = dragonfly.Dragonfly.suppressions
    command = group.get_command("list")
    assert isinstance(command, app_commands.Command)
    interaction_mock = Mock()
    interaction_mock.response.is_done.return_value = True
    interaction_mock.response.send_message = AsyncMock()
    interaction_mock.followup.send = AsyncMock()
    interaction = cast("discord.Interaction[Bot]", interaction_mock)
    error = app_commands.CommandInvokeError(command, TimeoutError("mainframe unavailable"))

    asyncio.run(dragonfly.SuppressionCommandGroup.on_error(group, interaction, error))

    interaction_mock.followup.send.assert_awaited_once_with(
        "Mainframe could not complete the suppression request. No changes were confirmed.",
        ephemeral=True,
    )
    interaction_mock.response.send_message.assert_not_awaited()


def test_view_suppression_slash_command_rejects_invalid_uuid() -> None:
    bot = cast("Bot", Mock())
    get_suppression = AsyncMock()
    bot.dragonfly_services.get_suppression = get_suppression

    interaction = _invoke_suppression_command("view", bot, "example-package", "1.0.0", "not-a-uuid")

    interaction.response.send_message.assert_awaited_once_with(
        "The suppression ID must be a valid UUID.",
        ephemeral=True,
    )
    interaction.response.defer.assert_not_awaited()
    get_suppression.assert_not_called()


def _invoke_suppression_command(command_name: str, bot: Bot, *args: str) -> Mock:
    """Invoke a decorated suppression application-command callback."""
    command = dragonfly.Dragonfly.suppressions.get_command(command_name)
    assert isinstance(command, app_commands.Command)
    callback = cast("Callable[..., Coroutine[Any, Any, None]]", command.callback)
    interaction_mock = Mock()
    interaction_mock.response.defer = AsyncMock()
    interaction_mock.response.send_message = AsyncMock()
    interaction_mock.followup.send = AsyncMock()
    interaction = cast("discord.Interaction[Bot]", interaction_mock)

    asyncio.run(callback(dragonfly.Dragonfly(bot), interaction, *args))
    return interaction_mock


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


@pytest.mark.parametrize(
    "rules",
    [
        [f"suspicious_rule_{index:03d}_{'x' * 100}" for index in range(100)],
        [
            "x"
            * (
                dragonfly.EMBED_DESCRIPTION_LIMIT
                - len(dragonfly.RULES_DESCRIPTION_PREFIX)
                - len(dragonfly.RULES_DESCRIPTION_SUFFIX)
                - len(", … (+10 more)")
            ),
            *[f"omitted_rule_{index}" for index in range(10)],
        ],
    ],
    ids=["many-rules", "omission-digit-boundary"],
)
def test_scan_iteration_advances_cursor_with_large_rule_set(rules: list[str]) -> None:
    bot = cast("Bot", Mock())
    configure_alerting_api(bot)
    result = package_result(rules=rules)
    bot.dragonfly_services.get_scanned_packages = AsyncMock(return_value=[result])
    bot.dragonfly_services.get_suppressions = AsyncMock(return_value=[])
    cog = dragonfly.Dragonfly(bot)
    previous_cursor = cog.since
    logs_channel_mock = Mock()
    logs_channel_mock.send = AsyncMock()
    logs_channel = cast("discord.abc.Messageable", logs_channel_mock)

    async def reject_oversized_alert(*_args: object, **kwargs: object) -> None:
        embed = cast("discord.Embed", kwargs["embed"])
        assert embed.description is not None
        assert len(embed.description) <= dragonfly.EMBED_DESCRIPTION_LIMIT

    alerts_channel_mock = Mock()
    alerts_channel_mock.send = AsyncMock(side_effect=reject_oversized_alert)
    alerts_channel = cast("discord.abc.Messageable", alerts_channel_mock)

    with patch.object(dragonfly, "AlertView", return_value=Mock()):
        asyncio.run(cog.run_scan_iteration(logs_channel=logs_channel, alerts_channel=alerts_channel))

    assert cog.since > previous_cursor
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
