"""Cog to log."""

import logging
from datetime import UTC, datetime
from typing import Self

import discord
from discord.ext.commands import Cog, Context

from bot.bot import Bot
from bot.constants import Channels, Roles

log = logging.getLogger(__name__)


class Log(Cog):
    """Logging for server events and staff actions."""

    def __init__(self: Self, bot: Bot) -> None:
        self.bot = bot

    async def send_log_message(  # noqa: PLR0913 -- Maybe refactor this?
        self: Self,
        icon_url: str | None,
        colour: discord.Colour | int,
        title: str | None,
        text: str,
        thumbnail: str | discord.Asset | None = None,
        channel_id: int = Channels.mod_log,
        ping_mods: bool = False,  # noqa: FBT001,FBT002
        files: list[discord.File] | None = None,
        content: str | None = None,
        additional_embeds: list[discord.Embed] | None = None,
        timestamp_override: datetime | None = None,
        footer: str | None = None,
    ) -> Context:
        """Generate log embed and send to logging channel."""
        # Truncate string directly here to avoid removing newlines
        embed = discord.Embed(description=text[:4093] + "..." if len(text) > 4096 else text)  # noqa: PLR2004

        if title and icon_url:
            embed.set_author(name=title, icon_url=icon_url)

        embed.colour = colour
        embed.timestamp = timestamp_override or datetime.now(tz=UTC)

        if footer:
            embed.set_footer(text=footer)

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        if ping_mods:
            content = f"<@&{Roles.moderators}> {content}" if content else f"<@&{Roles.moderators}>"

        # Truncate content to 2000 characters and append an ellipsis.
        if content and len(content) > 2000:  # noqa: PLR2004
            content = content[: 2000 - 3] + "..."

        channel = self.bot.get_channel(channel_id)
        log_message = await channel.send(content=content, embed=embed, files=files)

        if additional_embeds:
            for additional_embed in additional_embeds:
                await channel.send(embed=additional_embed)

        return await self.bot.get_context(log_message)  # Optionally return for use with antispam


async def setup(bot: Bot) -> None:
    """Load the Log cog."""
    await bot.add_cog(Log(bot))
