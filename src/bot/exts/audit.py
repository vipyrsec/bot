"""Cog for package audition"""


from .dragonfly._api import lookup_package_info
from .dragonfly._api import PackageScanResult

from datetime import datetime, timedelta
import discord
from discord.ext import commands
from discord.ext.commands import Cog, command, Context, Bot



class Audit(Cog):
    """Cog for package audition"""
    def __init__(self,
                bot: Bot,
                ) -> None:
        self.bot = bot


    @commands.command()
    async def audit(self,
                    ctx: Context,
                    since: datetime | int,
                    package_amount: int = 50,
                    ) -> None:
        """Recalls for scanned packages within a given time frame and amount"""

        hours = since if 0 < since < 48 else 24
        since = datetime.now() - timedelta(hours=hours) 

        packages: list[PackageScanResult] = await lookup_package_info(bot=self.bot, since=since)
        packages = packages[:package_amount] if len(packages) > package_amount else packages
        
        
        embed = discord.Embed(title=f"Packages scanned in the last {hours} hours",
                              description=f"Total packages scanned: {len(packages)}",
                              )
        embed.set_footer(text=f"Requested by {ctx.author.display_name}",
                          icon_url=ctx.author.avatar_url,
                          )
        
        for package in packages:
            embed.add_field(name=f'{package.name}@{package.version}',
                            value=f'[Inspector URL]({package.inspector_url})',
                            )
            
        await ctx.send(embed=embed)