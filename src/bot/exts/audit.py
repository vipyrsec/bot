"""Cog for package audition"""


from .dragonfly._api import lookup_package_info
from .dragonfly._api import PackageScanResult

from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands
from discord.ext.commands import Cog, command, Context, Bot, Range


class Audit(Cog):
    """Cog for package audition"""
    def __init__(self,
                bot: Bot,
                ) -> None:
        self.bot = bot


    @commands.command()
    async def audit(self,
                    ctx: Context,
                    since: Range[int, 1, 48],
                    package_amount: Range[int, 1, 64] = 48
                    ) -> None:
        """Recalls for scanned packages within a given time frame and amount"""

        since = datetime.now(tz=timezone.utc) - timedelta(hours=since) 

        packages: list[PackageScanResult] = await lookup_package_info(bot=self.bot, since=since)
        packages = packages[:package_amount] if len(packages) > package_amount else packages
        
        
        embed = discord.Embed(title=f"Packages scanned in the last {hours} hours")
        description = f"Total packages scanned: {len(packages)}\n\n"

        for package in packages:
            description += f"[{package.name}@{package.version}]({package.inspector_url})\n"

        embed.description = description
        await ctx.send(embed=embed)
