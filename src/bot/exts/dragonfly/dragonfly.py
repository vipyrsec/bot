"""Download the most recent packages from PyPI and use Dragonfly to check them for malware"""

import logging
from datetime import datetime, timedelta, timezone
from logging import getLogger

import discord
from discord.ext import commands, tasks

from bot.bot import Bot
from bot.constants import DragonflyConfig, Roles, DragonflyAuthentication

from ._api import PackageScanResult, lookup_package_info

log = getLogger(__name__)
log.setLevel(logging.INFO)


class ReportView(discord.ui.View):
    """Report view"""
    def __init__(self,
                bot: Bot,
                payload: PackageScanResult
                ) -> None:
        self.bot = bot
        self.payload = payload
        super().__init__(timeout=None)
    
    @discord.ui.button(label='Report', style=discord.ButtonStyle.red)
    async def report(self, interaction: discord.Interaction, _) -> None:
        async with self.bot.http_session.post(url=f'{DragonflyConfig.api_url}/report', json=self.payload) as response:
            if response.status == 200:
                await interaction.response.send_message('Reported!', ephemeral=True)
            else:
                await interaction.response.send_message('Something went wrong lmao', ephemeral=True)


def _build_package_scan_result_embed(scan_result: PackageScanResult) -> discord.Embed:
    """Build the embed that shows the results of a package scan"""

    embed = discord.Embed(
        title=f"New Scan Result: {scan_result.name} v{scan_result.version}",
        description=f"```YARA rules matched: {', '.join(scan_result.rules) or 'None'}```",
        color=0xF70606,
    )

    embed.add_field(
        name="\u200B",
        value=f"[Inspector]({scan_result.inspector_url})",
        inline=True,
    )

    embed.add_field(
        name="\u200B",
        value=f"[PyPI](https://pypi.org/project/{scan_result.name}/{scan_result.version})",
        inline=True,
    )

    embed.set_footer(text="DragonFly V2")

    return embed


async def run(
    bot: Bot,
    *,
    log_channel: discord.abc.Messageable,
) -> None:
    """Script entrypoint"""
    since = datetime.now(tz=timezone.utc) - timedelta(seconds=DragonflyConfig.interval)
    scan_results = await lookup_package_info(bot, since=since)
    if scan_results:
        for result in scan_results:
            embed = _build_package_scan_result_embed(result)
            await log_channel.send(f"<@&{DragonflyConfig.alerts_role_id}"embed=embed, view=ReportView(bot, result))
    else:
        embed = discord.Embed(description="No packages scanned", color=discord.Colour.red())
        await log_channel.send(embed=embed)

class Dragonfly(commands.Cog):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        super().__init__()

    @tasks.loop(seconds=DragonflyConfig.interval)
    async def scan_loop(self) -> None:
        logs_channel = self.bot.get_channel(DragonflyConfig.logs_channel_id)
        assert isinstance(logs_channel, discord.abc.Messageable)

        await run(
            self.bot,
            log_channel=logs_channel,
        )

    @commands.command()
    async def start(self, ctx: commands.Context) -> None:
        if self.scan_loop.is_running():
            await ctx.send("Task is already running.")
        else:
            self.scan_loop.start()
            await ctx.send("Started task 2...")

    @commands.command()
    async def stop(self, ctx: commands.Context, force: bool = False) -> None:
        if self.scan_loop.is_running():
            if force:
                self.scan_loop.cancel()
                await ctx.send("Forcing shutdown...")
            else:
                self.scan_loop.stop()
                await ctx.send("Executing graceful shutdown...")
        else:
            await ctx.send("Task is not running.")

    @discord.app_commands.checks.has_role(Roles.vipyr_security)
    @discord.app_commands.command(name="lookup", description="Scans a package")
    async def lookup(self, interaction: discord.Interaction, name: str, version: str | None = None) -> None:
        scan_results = await lookup_package_info(self.bot, name=name, version=version)
        if scan_results:
            embed = _build_package_scan_result_embed(scan_results[0])
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No entries were found with the specified filters.")


async def setup(bot: Bot) -> None:
    await bot.add_cog(Dragonfly(bot))
