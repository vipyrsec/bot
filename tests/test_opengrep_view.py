"""Publication safety, restart persistence, and private evidence navigation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest
from test_scan_alerting import configure_alerting_api, opengrep_finding, opengrep_result, package_result

from bot.constants import Roles
from bot.dragonfly_services import OpenGrepDetails, ScanStatus
from bot.exts.dragonfly import dragonfly
from bot.exts.dragonfly.opengrep_view import (
    FINDINGS_CUSTOM_ID,
    EvidencePages,
    FindingsView,
    evidence_pages,
    summary_embed,
)

if TYPE_CHECKING:
    from discord.types.components import ActionRow as ActionRowPayload


def test_all_findings_have_bounded_pages_and_inspector_links() -> None:
    result = OpenGrepDetails.model_validate(
        opengrep_result(
            findings=[opengrep_finding(i, message="@everyone " + "x" * 900) for i in range(500)]
        ).model_dump()
    )
    pages = evidence_pages(result)
    assert len(pages) > 1
    assert all(len(page) <= 1900 for page in pages)
    assert "@everyone" not in "".join(pages)
    for index in range(500):
        assert f"https://inspector.example/src/module_{index}.py#line.3" in "".join(pages)


@pytest.mark.parametrize("status", list(ScanStatus))
def test_summary_handles_every_status_and_bounds_failure(status: ScanStatus) -> None:
    result = opengrep_result().model_copy(update={"status": status, "fail_reason": "@everyone " + "x" * 5000})
    summary = summary_embed("example", "1+local", result)
    assert len(summary) < 1000
    assert summary.url == "https://pypi.org/project/example/1%2Blocal/"
    assert "@everyone" not in (summary.fields[0].value or "")
    assert ("Partial" if status is ScanStatus.FINISHED else status.value.capitalize()) in (summary.description or "")


def test_private_pagination_has_independent_cursors_and_owner_checks() -> None:
    async def run() -> None:
        result = OpenGrepDetails.model_validate(
            opengrep_result(findings=[opengrep_finding(i, message="x" * 800) for i in range(5)]).model_dump()
        )
        first, second = EvidencePages(result, 1), EvidencePages(result, 2)
        interaction = Mock(user=Mock(id=1))
        interaction.response.edit_message = AsyncMock()
        assert await first.interaction_check(interaction)
        assert not await second.interaction_check(interaction)
        assert first.previous.disabled
        await first.next.callback(interaction)
        assert first.index == 1
        assert second.index == 0
        assert not first.previous.disabled
        await first.previous.callback(interaction)
        assert first.index == 0
        assert interaction.response.edit_message.await_args is not None
        assert interaction.response.edit_message.await_args.kwargs["allowed_mentions"].everyone is False

    asyncio.run(run())


@pytest.mark.parametrize("state", ["complete", "absent", "unavailable", "unauthorized", "foreign_message"])
def test_findings_can_be_reopened_after_restart_without_leasing(state: str) -> None:
    async def run() -> None:
        result = OpenGrepDetails.model_validate(opengrep_result(findings=[opengrep_finding()]).model_dump())
        bot = Mock(user=Mock(id=5))
        bot.dragonfly_services.get_opengrep_details = AsyncMock(
            return_value=None if state == "absent" else result,
            side_effect=TimeoutError if state == "unavailable" else None,
        )
        user = Mock(spec=discord.Member, id=42, roles=[Mock(id=Roles.vipyr_security)])
        if state == "unauthorized":
            user.roles = []
        interaction = Mock(user=user)
        interaction.message = Mock(
            author=Mock(id=6 if state == "foreign_message" else 5),
            embeds=[summary_embed("example", "1+local", result)],
        )
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        # Reconstruct only the globally registered view, with no original state.
        view = FindingsView(bot)
        assert view.is_persistent()
        button = view.children[0]
        assert isinstance(button, discord.ui.Button)
        assert button.custom_id == FINDINGS_CUSTOM_ID
        await button.callback(interaction)
        if state in {"unauthorized", "foreign_message"}:
            bot.dragonfly_services.get_opengrep_details.assert_not_awaited()
            return
        bot.dragonfly_services.get_opengrep_details.assert_awaited_once_with("example", "1+local")
        interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
        assert interaction.followup.send.await_args is not None
        assert interaction.followup.send.await_args.kwargs["ephemeral"]
        if state == "complete":
            assert isinstance(interaction.followup.send.await_args.kwargs["view"], EvidencePages)

    asyncio.run(run())


@pytest.mark.parametrize("migrate", [False, True])
@pytest.mark.parametrize("fail_edit", [False, True])
def test_publication_edits_alert_preserves_actions_and_acknowledges_after_success(
    *, migrate: bool, fail_edit: bool
) -> None:
    async def run() -> None:
        bot = Mock()
        bot.dragonfly_services.heartbeat_opengrep_publication = AsyncMock()
        bot.dragonfly_services.acknowledge_opengrep_result = AsyncMock()
        bot.dragonfly_services.get_scanned_packages = AsyncMock(return_value=[package_result()])
        result = opengrep_result(findings=[opengrep_finding()], discord_alert_message_id=123)
        old_view = dragonfly.AlertView(bot, package_result())
        old_view.suppress.disabled = True
        if not migrate:
            old_view.add_item(FindingsView(bot).children[0])
        components = [discord.ActionRow(cast("ActionRowPayload", row)) for row in old_view.to_components()]
        original = discord.Embed(title="Original YARA verdict")
        message = Mock(embeds=[original, summary_embed(result.name, result.version, None)], components=components)
        message.edit = AsyncMock(side_effect=RuntimeError("Discord unavailable") if fail_edit else None)
        channel = Mock(fetch_message=AsyncMock(return_value=message), send=AsyncMock())
        if fail_edit:
            with pytest.raises(RuntimeError, match="Discord unavailable"):
                await dragonfly.publish_opengrep_result(bot, channel, result)
            bot.dragonfly_services.acknowledge_opengrep_result.assert_not_awaited()
            return
        await dragonfly.publish_opengrep_result(bot, channel, result)
        assert message.edit.await_args is not None
        kwargs = message.edit.await_args.kwargs
        assert len(kwargs["embeds"]) == 2
        assert kwargs["embeds"][0] is original
        assert "Complete" in kwargs["embeds"][1].description
        assert kwargs["allowed_mentions"].everyone is False
        if migrate:
            assert kwargs["view"].suppress.disabled
        else:
            assert "view" not in kwargs
        bot.dragonfly_services.acknowledge_opengrep_result.assert_awaited_once_with(result)
        channel.send.assert_not_awaited()
        message.create_thread.assert_not_called()

    asyncio.run(run())


def test_publication_retry_replaces_summary_instead_of_appending() -> None:
    async def run() -> None:
        bot = Mock()
        bot.dragonfly_services.heartbeat_opengrep_publication = AsyncMock()
        bot.dragonfly_services.acknowledge_opengrep_result = AsyncMock(side_effect=[TimeoutError, None])
        result = opengrep_result(discord_alert_message_id=123)
        view = FindingsView(bot)
        message = Mock(
            embeds=[discord.Embed(title="YARA")],
            components=[discord.ActionRow(cast("ActionRowPayload", row)) for row in view.to_components()],
        )

        async def edit(**kwargs: Any) -> None:
            message.embeds = kwargs["embeds"]

        message.edit = AsyncMock(side_effect=edit)
        channel = Mock(fetch_message=AsyncMock(return_value=message))
        with pytest.raises(TimeoutError):
            await dragonfly.publish_opengrep_result(bot, channel, result)
        await dragonfly.publish_opengrep_result(bot, channel, result)
        assert len(message.embeds) == 2

    asyncio.run(run())


@pytest.mark.parametrize("state", ["available", "partial", "absent", "error"])
def test_lookup_uses_viewer_without_threads(state: str) -> None:
    async def run() -> None:
        package = package_result()
        result = OpenGrepDetails.model_validate(opengrep_result().model_dump())
        if state == "partial":
            result.fail_reason = "One distribution timed out"
        bot = Mock()
        bot.dragonfly_services.get_scanned_packages = AsyncMock(return_value=[package])
        bot.dragonfly_services.get_package_opengrep = AsyncMock(
            return_value=None if state == "absent" else result,
            side_effect=TimeoutError if state == "error" else None,
        )
        configure_alerting_api(bot)
        bot.http_session.get.return_value = Mock(
            __aenter__=AsyncMock(return_value=Mock(ok=True)),
            __aexit__=AsyncMock(return_value=None),
        )
        interaction = Mock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        await dragonfly.Dragonfly.lookup.callback(Mock(bot=bot), interaction, package.name)
        bot.dragonfly_services.get_package_opengrep.assert_awaited_once_with(package)
        assert interaction.followup.send.await_args is not None
        sent = interaction.followup.send.await_args.kwargs
        assert len(sent["embeds"]) == (1 if state == "absent" else 2)
        interaction.channel.create_thread.assert_not_called()
        if state == "partial":
            assert "Partial" in sent["embeds"][1].description

    asyncio.run(run())


def test_publication_loop_claims_individually_and_bounds_each_iteration() -> None:
    async def run() -> None:
        channel = Mock(spec=discord.TextChannel)
        result = opengrep_result()
        bot = Mock()
        bot.get_channel.return_value = channel
        bot.dragonfly_services.get_opengrep_results = AsyncMock(return_value=[result])
        cog = dragonfly.Dragonfly(bot)
        with patch.object(dragonfly, "publish_opengrep_results", new_callable=AsyncMock) as publish:
            await dragonfly.Dragonfly.opengrep_shadow_loop.coro(cog)
            assert publish.await_count == 10
        assert bot.dragonfly_services.get_opengrep_results.await_count == 10

    asyncio.run(run())


@pytest.mark.parametrize("checkpoint_fails", [False, True])
def test_legacy_result_checkpoints_summary_before_acknowledgement(*, checkpoint_fails: bool) -> None:
    async def run() -> None:
        bot = Mock()
        bot.dragonfly_services.heartbeat_opengrep_publication = AsyncMock()
        bot.dragonfly_services.acknowledge_opengrep_result = AsyncMock()
        bot.dragonfly_services.checkpoint_opengrep_publication = AsyncMock(
            side_effect=TimeoutError if checkpoint_fails else None
        )
        message = Mock(id=123)
        channel = Mock(send=AsyncMock(return_value=message))
        result = opengrep_result()
        if checkpoint_fails:
            with pytest.raises(TimeoutError):
                await dragonfly.publish_opengrep_result(bot, channel, result)
            bot.dragonfly_services.acknowledge_opengrep_result.assert_not_awaited()
        else:
            await dragonfly.publish_opengrep_result(bot, channel, result)
            bot.dragonfly_services.acknowledge_opengrep_result.assert_awaited_once_with(result)
        assert channel.send.await_args is not None
        assert channel.send.await_args.kwargs["nonce"] == result.scan_id.hex[:24]
        bot.dragonfly_services.checkpoint_opengrep_publication.assert_awaited_once_with(
            result,
            discord_message_id=123,
            discord_thread_id=None,
            published_chunks=0,
        )
        message.create_thread.assert_not_called()

    asyncio.run(run())
