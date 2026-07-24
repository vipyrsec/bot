"""Regression tests for defects exposed by strict type checking."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import discord
from aiohttp import ClientSession
from discord.ext import commands

from bot.bot import Bot
from bot.dragonfly_services import DragonflyServices
from bot.exts.core.error_handler import CommandErrorHandler
from bot.exts.dragonfly import threat_intel_feed
from bot.utils.messages import get_discord_message


def test_message_conversion_falls_back_to_original_text() -> None:
    """A failed Discord conversion must return the caller's original text."""
    ctx = cast("commands.Context[Bot]", Mock())
    convert = AsyncMock(side_effect=commands.BadArgument("invalid message reference"))

    with patch.object(commands.MessageConverter, "convert", convert):
        result = asyncio.run(get_discord_message(ctx, "not-a-message"))

    assert result == "not-a-message"
    convert.assert_awaited_once_with(ctx, "not-a-message")


def test_threat_intel_setup_starts_an_idle_watcher() -> None:
    """Extension setup must call is_running and start an idle watcher."""
    watcher = Mock()
    watcher.is_running.return_value = False
    cog = Mock(watcher=watcher)
    bot = cast("Bot", Mock())
    bot.add_cog = AsyncMock()

    with patch.object(threat_intel_feed, "ThreatIntelFeed", return_value=cog):
        asyncio.run(threat_intel_feed.setup(bot))

    watcher.is_running.assert_called_once_with()
    watcher.start.assert_called_once_with()
    bot.add_cog.assert_awaited_once_with(cog)


def test_invalid_command_input_resets_its_cooldown() -> None:
    """Rejected input must not consume the command cooldown."""
    command_mock = Mock()
    command = cast("commands.Command[Any, ..., Any]", command_mock)
    ctx = cast("commands.Context[Bot]", Mock())

    CommandErrorHandler.revert_cooldown_counter(command, ctx)

    command_mock.reset_cooldown.assert_called_once_with(ctx)


def test_bot_constructs_with_pydis_command_tree() -> None:
    """The bot must let pydis-core provide its command-tree implementation."""

    def command_prefix(_bot: Bot, _message: discord.Message) -> list[str]:
        return ["!"]

    async def construct_bot() -> None:
        async with ClientSession() as session:
            dragonfly_services = cast("DragonflyServices", Mock())
            bot = Bot(
                dragonfly_services=dragonfly_services,
                guild_id=1,
                allowed_roles=[],
                http_session=session,
                command_prefix=command_prefix,
                intents=discord.Intents.none(),
            )
            await bot.close()

    asyncio.run(construct_bot())
