"""Download the most recent packages from PyPI and use Dragonfly to check them for malware."""

import logging
from datetime import UTC, datetime, timedelta
from logging import getLogger
from typing import Self

import discord
import sentry_sdk
from discord.ext import commands, tasks

from bot.bot import Bot
from bot.constants import DragonflyConfig, Roles
from bot.exts.dragonfly._builders import build_all_packages_scanned_embed, build_package_scan_result_embed
from bot.exts.dragonfly._views import ReportView

log = getLogger(__name__)
log.setLevel(logging.INFO)


async def run(
    bot: Bot,
    *,
    since: datetime,
    alerts_channel: discord.abc.Messageable,
    logs_channel: discord.abc.Messageable,
    score: int,
) -> None:
    """Script entrypoint."""
    scans = await bot.dragonfly_services.get_scanned_packages_since(since)
    for scan in scans:
        if (scan.score or 0) >= score:
            embed = build_package_scan_result_embed(scan)
            await alerts_channel.send(
                f"<@&{DragonflyConfig.alerts_role_id}>",
                embed=embed,
                view=ReportView(bot, scan),
            )

    await logs_channel.send(embed=build_all_packages_scanned_embed(scans))


class Dragonfly(commands.Cog):
    """Cog for the Dragonfly scanner."""

    def __init__(self: Self, bot: Bot) -> None:
        """Initialize the Dragonfly cog."""
        self.bot = bot
        self.score_threshold = DragonflyConfig.threshold
        self.since = datetime.now(tz=UTC) - timedelta(seconds=DragonflyConfig.interval)
        super().__init__()

    @tasks.loop(seconds=DragonflyConfig.interval)
    async def scan_loop(self: Self) -> None:
        """Loop that runs the scan task."""
        logs_channel = self.bot.get_channel(DragonflyConfig.logs_channel_id)
        assert isinstance(logs_channel, discord.abc.Messageable)

        alerts_channel = self.bot.get_channel(DragonflyConfig.alerts_channel_id)
        assert isinstance(alerts_channel, discord.abc.Messageable)

        try:
            await run(
                self.bot,
                since=self.since,
                logs_channel=logs_channel,
                alerts_channel=alerts_channel,
                score=self.score_threshold,
            )
        except Exception as e:
            log.exception("An error occured in the scan loop task. Skipping run.")
            sentry_sdk.capture_exception(e)
        else:
            self.since = datetime.now(tz=UTC)

    @scan_loop.before_loop
    async def before_scan_loop(self: Self) -> None:
        """Wait until the bot is ready."""
        await self.bot.wait_until_ready()

    @commands.has_role(Roles.vipyr_security)
    @commands.command()
    async def start(self: Self, ctx: commands.Context) -> None:  # type: ignore[type-arg]
        """Start the scan task."""
        if self.scan_loop.is_running():
            await ctx.send("Task is already running")
        else:
            self.scan_loop.start()
            await ctx.send("Started task")

    @commands.has_role(Roles.vipyr_security)
    @commands.command()
    async def stop(self: Self, ctx: commands.Context, *, force: bool = False) -> None:
        """Stop the scan task."""
        if self.scan_loop.is_running():
            if force:
                self.scan_loop.cancel()
                await ctx.send("Forcing shutdown")
            else:
                self.scan_loop.stop()
                await ctx.send("Executing graceful shutdown")
        else:
            await ctx.send("Task is not running")

    @discord.app_commands.checks.has_role(Roles.vipyr_security)
    @discord.app_commands.command(name="lookup", description="Scans a package")
    async def lookup(self: Self, interaction: discord.Interaction, name: str, version: str) -> None:
        """Pull the scan results for a package."""
        scan = await self.bot.dragonfly_services.get_package(name=name, version=version)
        if scan:
            embed = build_package_scan_result_embed(scan)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No entries were found with the specified filters.")

    @commands.group()
    async def threshold(self: Self, ctx: commands.Context) -> None:  # type: ignore[type-arg]
        """Group of commands for managing the score threshold."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.threshold)

    @threshold.command()  # type: ignore[arg-type]
    async def get(self: Self, ctx: commands.Context) -> None:  # type: ignore[type-arg]
        """Get the score threshold."""
        await ctx.send(f"The current threshold is set to `{self.score_threshold}`")

    @threshold.command()  # type: ignore[arg-type]
    async def set(self: Self, ctx: commands.Context, value: int) -> None:  # type: ignore[type-arg]
        """Set the score threshold."""
        self.score_threshold = value
        await ctx.send(f"The current threshold has been set to `{value}`")


async def setup(bot: Bot) -> None:
    """Load the Dragonfly cog."""
    cog = Dragonfly(bot)
    task = cog.scan_loop
    if not task.is_running():
        task.start()
    await bot.add_cog(cog)
