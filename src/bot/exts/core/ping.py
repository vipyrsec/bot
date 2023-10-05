"""Pinging the bot."""

from typing import Self

from discord import Embed
from discord.ext import commands

from bot.bot import Bot
from bot.constants import Colours


class Ping(commands.Cog):
    """Get info about the bot's ping and uptime."""

    def __init__(self: Self, bot: Bot) -> None:
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self: Self, ctx: commands.Context) -> None:
        """Ping the bot to see its latency and state."""
        embed = Embed(
            title=":ping_pong: Pong!",
            colour=Colours.bright_green,
            description=f"Gateway Latency: {round(self.bot.latency * 1000)}ms",
        )

        await ctx.send(embed=embed)


async def setup(bot: Bot) -> None:
    """Load the Ping cog."""
    await bot.add_cog(Ping(bot))
