import logging
from logging import getLogger

import discord
from discord.ext import commands

from bot.bot import Bot
from bot.constants import DragonflyConfig

log = getLogger(__name__)
log.setLevel(logging.INFO)


class StartupNotify(commands.Cog):
    """Cog that notifies a channel when the bot starts up."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    def _build_notify_embed(self) -> discord.Embed:
        embed = discord.Embed(description="Ready!")
        if user := self.bot.user:
            embed.set_author(name=user.name, icon_url=user.display_avatar.url)

        return embed

    @commands.Cog.listener()
    async def on_ready(self):
        channel = self.bot.get_channel(DragonflyConfig.logs_channel_id)
        if isinstance(channel, discord.abc.Messageable):
            await channel.send(embed=self._build_notify_embed())
            log.info("Successfully sent startup notification message")
        else:
            log.warning("Channel %s is not messageable, could not send startup message", channel)


async def setup(bot: Bot) -> None:
    """Load the Startup Notify cog."""
    await bot.add_cog(StartupNotify(bot))
