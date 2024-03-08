"""Download the most recent packages from PyPI and use Dragonfly to check them for malware."""

import logging
from datetime import UTC, datetime, timedelta
from logging import getLogger
from typing import Self

import aiohttp
import discord
import sentry_sdk
from discord.ext import commands, tasks

from bot.bot import Bot
from bot.constants import Channels, DragonflyConfig, Roles
from bot.dragonfly_services import PackageScanResult

log = getLogger(__name__)
log.setLevel(logging.INFO)


def _build_package_report_log_embed(
    *,
    member: discord.User | discord.Member,
    package_name: str,
    package_version: str,
    description: str | None,
    inspector_url: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Package reported: {package_name} v{package_version}",
        color=discord.Colour.red(),
        description=description or "*No description provided*",
        timestamp=datetime.now(tz=UTC),
    )

    embed.set_author(name=member.name, icon_url=member.display_avatar.url)
    embed.add_field(name="Reported by", value=member.mention)
    embed.add_field(name="Inspector URL", value=f"[Inspector URL]({inspector_url})")

    return embed


class ConfirmReportModal(discord.ui.Modal):
    """Modal for confirming a report."""

    recipient = discord.ui.TextInput(  # type: ignore[var-annotated]
        label="Recipient",
        placeholder="Recipient's Email Address",
        required=False,
        default="security@pypi.org",
        style=discord.TextStyle.short,
    )

    additional_information = discord.ui.TextInput(  # type: ignore[var-annotated]
        label="Additional information",
        placeholder="Additional information",
        required=False,
        style=discord.TextStyle.long,
    )

    inspector_url = discord.ui.TextInput(  # type: ignore[var-annotated]
        label="Inspector URL",
        placeholder="Inspector URL",
        required=False,
        style=discord.TextStyle.short,
    )

    def __init__(self: Self, *, package: PackageScanResult, bot: Bot) -> None:
        """Initialize the modal."""
        self.package = package
        self.bot = bot

        # set dynamic properties here because we can't set dynamic class attributes
        self.title = self._build_modal_title()
        self.inspector_url.default = package.inspector_url

        super().__init__()

    async def on_error(self: Self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override, type-arg]
        """Handle errors that occur in the modal."""
        if isinstance(error, aiohttp.ClientResponseError):
            return await interaction.response.send_message(f"Error from upstream: {error.status}", ephemeral=True)

        await interaction.response.send_message("An unexpected error occured.", ephemeral=True)
        raise error

    def _build_modal_title(self: Self) -> str:
        """Build the modal title."""
        title = f"Confirm report for {self.package.name} v{self.package.version}"
        if len(title) >= 45:  # noqa: PLR2004
            title = title[:42] + "..."

        return title

    async def on_submit(self: Self, interaction: discord.Interaction) -> None:  # type: ignore[type-arg]
        """Submit the report."""
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

        log_channel = interaction.client.get_channel(Channels.reporting)
        if isinstance(log_channel, discord.abc.Messageable):
            embed = _build_package_report_log_embed(
                member=interaction.user,
                package_name=self.package.name,
                package_version=self.package.version,
                description=additional_information_override,
                inspector_url=inspector_url_override or self.package.inspector_url,
            )
            await log_channel.send(embed=embed)
        try:
            await self.bot.dragonfly_services.report_package(
                name=self.package.name,
                version=self.package.version,
                inspector_url=inspector_url_override,
                additional_information=additional_information_override,
                recipient=self.recipient.value,
            )

            await interaction.response.send_message("Reported!", ephemeral=True)
        except:
            await interaction.response.send_message("An unexpected error occured!", ephemeral=True)
            raise


class ReportView(discord.ui.View):
    """Report view."""

    def __init__(self: Self, bot: Bot, payload: PackageScanResult) -> None:
        self.bot = bot
        self.payload = payload
        super().__init__(timeout=None)

    @discord.ui.button(label="Report", style=discord.ButtonStyle.red)
    async def report(self: Self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[type-arg]
        """Report a package."""
        modal = ConfirmReportModal(package=self.payload, bot=self.bot)
        await interaction.response.send_modal(modal)

        timed_out = await modal.wait()
        if not timed_out:
            button.disabled = True
            await interaction.edit_original_response(view=self)


def _build_package_scan_result_embed(scan_result: PackageScanResult) -> discord.Embed:
    """Build the embed that shows the results of a package scan."""
    embed = discord.Embed(
        title=f"Malicious package found: {scan_result.name} @ {scan_result.version}",
        description=f"```YARA rules matched: {', '.join(scan_result.rules) or 'None'}```",
        color=0xF70606,
    )

    embed.add_field(
        name="\u200b",
        value=f"[Inspector]({scan_result.inspector_url})",
        inline=True,
    )

    embed.add_field(
        name="\u200b",
        value=f"[PyPI](https://pypi.org/project/{scan_result.name}/{scan_result.version})",
        inline=True,
    )

    return embed


def _build_all_packages_scanned_embed(scan_results: list[PackageScanResult]) -> discord.Embed:
    """Build the embed that shows a list of all packages scanned."""
    if scan_results:
        description = "\n".join(map(str, scan_results))
        return discord.Embed(description=f"```{description}```")
    return discord.Embed(description="_No packages scanned_")


async def run(
    bot: Bot,
    *,
    since: datetime,
    alerts_channel: discord.abc.Messageable,
    logs_channel: discord.abc.Messageable,
    score: int,
) -> None:
    """Script entrypoint."""
    scan_results = await bot.dragonfly_services.get_scanned_packages(since=since)
    for result in scan_results:
        if result.score >= score:
            embed = _build_package_scan_result_embed(result)
            await alerts_channel.send(
                f"<@&{DragonflyConfig.alerts_role_id}>",
                embed=embed,
                view=ReportView(bot, result),
            )

    await logs_channel.send(embed=_build_all_packages_scanned_embed(scan_results))


class Dragonfly(commands.Cog):
    """Cog for the Dragonfly scanner."""

    def __init__(self: Self, bot: Bot) -> None:
        """Initialize the Dragonfly cog."""
        self.bot = bot
        self.score_threshold = DragonflyConfig.threshold
        self.since = datetime.now(tz=UTC) - timedelta(seconds=DragonflyConfig.interval)
        super().__init__()

    @commands.hybrid_command(name="username")  # type: ignore [arg-type]
    async def get_username_command(self, ctx: commands.Context[Bot]) -> None:
        """Get the username of the currently logged in user to the PyPI Observation API."""
        async with ctx.bot.http_session.get(DragonflyConfig.reporter_url + "/echo") as res:
            json = await res.json()
            username = json["username"]

        await ctx.send(username)

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
    async def stop(self: Self, ctx: commands.Context, force: bool = False) -> None:  # type: ignore[type-arg] # noqa: FBT001,FBT002
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

    @discord.app_commands.checks.has_role(Roles.vipyr_security)  # type: ignore[arg-type]
    @discord.app_commands.command(name="lookup", description="Scans a package")
    async def lookup(self: Self, interaction: discord.Interaction, name: str, version: str | None = None) -> None:  # type: ignore[type-arg]
        """Pull the scan results for a package."""
        scan_results = await self.bot.dragonfly_services.get_scanned_packages(name=name, version=version)
        if scan_results:
            embed = _build_package_scan_result_embed(scan_results[0])
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
