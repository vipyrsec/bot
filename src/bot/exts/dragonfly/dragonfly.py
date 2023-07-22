"""Download the most recent packages from PyPI and use Dragonfly to check them for malware"""

import logging
from datetime import datetime, timedelta, timezone
from logging import getLogger

import discord
from discord.ext import commands, tasks

from bot.bot import Bot
from bot.constants import DragonflyConfig, Roles

from ._api import PackageScanResult, lookup_package_info

log = getLogger(__name__)
log.setLevel(logging.INFO)


class ConfirmReportModal(discord.ui.Modal):
    additional_information = discord.ui.TextInput(
        label="Additional information",
        placeholder="Additional information",
        required=False,
        style=discord.TextStyle.long,
    )

    inspector_url = discord.ui.TextInput(
        label="Inspector URL",
        placeholder="Inspector URL",
        required=False,
        style=discord.TextStyle.short,
    )

    def __init__(self, *, package: PackageScanResult, bot: Bot) -> None:
        self.package = package
        self.bot = bot

        # set dynamic properties here because we can't set dynamic class attributes
        self.title = self._build_modal_title()
        self.inspector_url.default = package.inspector_url

        super().__init__()

    def _build_modal_title(self) -> str:
        title = f"Confirm report for {self.package.name} v{self.package.version}"
        if len(title) >= 45:
            title = title[:42] + "..."

        return title

    async def on_submit(self, interaction: discord.Interaction):
        # discord.py returns empty string "" if not filled out, we want it to be `None`
        additional_information_override = self.additional_information.value or None
        inspector_url_override = self.inspector_url.value or None

        log.info(
            "User %s reported package %s@%s with additional_information '%s' and inspector_url '%s'",
            interaction.user,
            self.package.name,
            self.package.version,
            additional_information_override,
            inspector_url_override,
        )

        log_channel = interaction.client.get_channel(DragonflyConfig.logs_channel_id)
        if isinstance(log_channel, discord.abc.Messageable):
            await log_channel.send(
                f"User {interaction.user.mention} "
                f"reported package `{self.package.name}` "
                f"with additional_description `{additional_information_override}`"
                f"with inspector_url `{inspector_url_override}`"
            )

        url = f"{DragonflyConfig.api_url}/report"
        headers = {"Authorization": f"Bearer {self.bot.access_token}"}
        json = dict(
            name=self.package.name,
            version=self.package.version,
            inspector_url=inspector_url_override,
            additional_information=additional_information_override,
        )
        async with self.bot.http_session.post(url=url, json=json, headers=headers) as response:
            if response.status == 200:
                await interaction.response.send_message("Reported!", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error from upstream: {response.status}", ephemeral=True)


class ReportView(discord.ui.View):
    """Report view"""

    def __init__(self, bot: Bot, payload: PackageScanResult) -> None:
        self.bot = bot
        self.payload = payload
        super().__init__(timeout=None)

    @discord.ui.button(label="Report", style=discord.ButtonStyle.red)
    async def report(self, interaction: discord.Interaction, _) -> None:
        await interaction.response.send_modal(ConfirmReportModal(package=self.payload, bot=self.bot))


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


def _build_all_packages_scanned_embed(scan_results: list[PackageScanResult]) -> discord.Embed:
    """Build the embed that shows a list of all packages scanned"""

    desc = "\n".join(map(str, scan_results))
    embed = discord.Embed(title="Dragonfly Scan Logs", description=f"```{desc}```")

    embed.set_footer(text="Dragonfly V3")

    return embed


async def run(
    bot: Bot,
    *,
    alerts_channel: discord.abc.Messageable,
    logs_channel: discord.abc.Messageable,
    score: int,
) -> None:
    """Script entrypoint"""
    since = datetime.now(tz=timezone.utc) - timedelta(seconds=DragonflyConfig.interval)
    scan_results = await lookup_package_info(bot, since=since)
    for result in scan_results:
        if result.score >= score:
            embed = _build_package_scan_result_embed(result)
            await alerts_channel.send(
                f"<@&{DragonflyConfig.alerts_role_id}>", embed=embed, view=ReportView(bot, result)
            )

    if scan_results:
        log_embed = _build_all_packages_scanned_embed(scan_results)
        await logs_channel.send(embed=log_embed)
    else:
        embed = discord.Embed(description="No packages scanned", color=discord.Colour.red())
        await logs_channel.send(embed=embed)


class Dragonfly(commands.Cog):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.score_threshold = DragonflyConfig.threshold
        super().__init__()

    @tasks.loop(seconds=DragonflyConfig.interval)
    async def scan_loop(self) -> None:
        logs_channel = self.bot.get_channel(DragonflyConfig.logs_channel_id)
        assert isinstance(logs_channel, discord.abc.Messageable)

        alerts_channel = self.bot.get_channel(DragonflyConfig.alerts_channel_id)
        assert isinstance(alerts_channel, discord.abc.Messageable)

        await run(
            self.bot,
            logs_channel=logs_channel,
            alerts_channel=alerts_channel,
            score=self.score_threshold,
        )

    @commands.has_role(Roles.vipyr_security)
    @commands.command()
    async def start(self, ctx: commands.Context) -> None:
        if self.scan_loop.is_running():
            await ctx.send("Task is already running.")
        else:
            self.scan_loop.start()
            await ctx.send("Started task...")

    @commands.has_role(Roles.vipyr_security)
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

    @commands.group()
    async def threshold(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.threshold)

    @threshold.command()
    async def get(self, ctx: commands.Context) -> None:
        await ctx.send(f"The current threshold is set to `{self.score_threshold}`")

    @threshold.command()
    async def set(self, ctx: commands.Context, value: int) -> None:
        self.score_threshold = value
        await ctx.send(f"The current threshold has been set to `{value}`")


async def setup(bot: Bot) -> None:
    await bot.add_cog(Dragonfly(bot))
