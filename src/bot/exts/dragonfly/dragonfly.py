"""Download the most recent packages from PyPI and use Dragonfly to check them for malware."""

import logging
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from logging import getLogger
from typing import Self

import aiohttp
import discord
import sentry_sdk
from discord.ext import commands, tasks

from bot import constants
from bot.bot import Bot
from bot.constants import Channels, DragonflyConfig, Roles
from bot.dragonfly_services import DragonflyServices, Package, PackageReport

log = getLogger(__name__)
log.setLevel(logging.INFO)


def _build_modal_title(name: str, version: str) -> str:
    """Build the modal title."""
    title = f"Confirm report for {name} v{version}"
    if len(title) >= 45:  # noqa: PLR2004
        title = title[:42] + "..."

    return title


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


async def handle_submit(
    *,
    report: PackageReport,
    interaction: discord.Interaction,
    dragonfly_services: DragonflyServices,
) -> None:
    """Handle modal submit."""
    log.info(
        "User %s reported package %s@%s with additional_information '%s' and inspector_url '%s'",
        interaction.user,
        report.name,
        report.version,
        report.additional_information,
        report.inspector_url,
    )

    log_channel = interaction.client.get_channel(Channels.reporting)
    if isinstance(log_channel, discord.abc.Messageable):
        embed = _build_package_report_log_embed(
            member=interaction.user,
            package_name=report.name,
            package_version=report.version,
            description=report.additional_information,
            inspector_url=report.inspector_url or "",
        )

        await log_channel.send(embed=embed)

    await dragonfly_services.report_package(report)

    await interaction.response.send_message("Reported!", ephemeral=True)


class ConfirmEmailReportModal(discord.ui.Modal):
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

    def __init__(self: Self, *, package: Package, bot: Bot) -> None:
        """Initialize the modal."""
        self.package = package
        self.bot = bot

        # set dynamic properties here because we can't set dynamic class attributes
        self.title = _build_modal_title(package.name, package.version)
        self.inspector_url.default = package.inspector_url

        super().__init__()

    async def on_error(self: Self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override, type-arg]
        """Handle errors that occur in the modal."""
        if isinstance(error, aiohttp.ClientResponseError):
            message = (
                f"Error from upstream: {error.status}\n"
                f"```{error.message}```\n"
                f"Retry using Observation API instead?"
            )
            view = ReportMethodSwitchConfirmationView(previous_modal=self)
            return await interaction.response.send_message(message, view=view, ephemeral=True)

        await interaction.response.send_message("An unexpected error occured.", ephemeral=True)
        raise error

    async def on_submit(self: Self, interaction: discord.Interaction) -> None:
        """Modal submit callback."""
        report = PackageReport(
            name=self.package.name,
            version=self.package.version,
            inspector_url=self.inspector_url.value or None,
            additional_information=self.additional_information.value or None,
            recipient=self.recipient.value or None,
            use_email=True,
        )

        await handle_submit(report=report, interaction=interaction, dragonfly_services=self.bot.dragonfly_services)


class ConfirmReportModal(discord.ui.Modal):
    """Modal for confirming a report through the Observations API."""

    additional_information = discord.ui.TextInput(
        label="Additional information",
        placeholder="Additional information",
        required=True,
        style=discord.TextStyle.long,
    )

    inspector_url = discord.ui.TextInput(
        label="Inspector URL",
        placeholder="Inspector URL",
        required=False,
        style=discord.TextStyle.short,
    )

    def __init__(self: Self, *, package: Package, bot: Bot) -> None:
        """Initialize the modal."""
        self.package = package
        self.bot = bot

        # set dynamic properties here because we can't set dynamic class attributes
        self.title = _build_modal_title(package.name, package.version)
        self.inspector_url.default = package.inspector_url
        self.recipient = None

        super().__init__()

    async def on_error(self: Self, interaction: discord.Interaction, error: Exception) -> None:
        """Handle errors that occur in the modal."""
        if isinstance(error, aiohttp.ClientResponseError):
            message = f"Error from upstream: {error.status}\n```{error.message}```\nRetry using email instead?"
            view = ReportMethodSwitchConfirmationView(previous_modal=self)
            return await interaction.response.send_message(message, view=view, ephemeral=True)

        await interaction.response.send_message("An unexpected error occured.", ephemeral=True)
        raise error

    async def on_submit(self: Self, interaction: discord.Interaction) -> None:
        """Modal submit callback."""
        report = PackageReport(
            name=self.package.name,
            version=self.package.version,
            inspector_url=self.inspector_url.value or None,
            additional_information=self.additional_information.value,
            recipient=None,
            use_email=False,
        )

        await handle_submit(report=report, interaction=interaction, dragonfly_services=self.bot.dragonfly_services)


class ReportMethodSwitchConfirmationView(discord.ui.View):
    """Prompt user if they want to switch reporting methods (email/API).

    View sent when reporting via the Observation API fails, and we want to ask the
    user if they want to switch to another method of sending reports.
    """

    def __init__(self: Self, previous_modal: ConfirmReportModal | ConfirmEmailReportModal) -> None:
        super().__init__()
        self.previous_modal = previous_modal
        self.package = previous_modal.package
        self.bot = previous_modal.bot

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self: Self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Confirm button callback."""
        if isinstance(self.previous_modal, ConfirmReportModal):
            modal = ConfirmEmailReportModal(package=self.package, bot=self.bot)
        else:
            modal = ConfirmReportModal(package=self.package, bot=self.bot)

        await interaction.response.send_modal(modal)

        self.disable_all()
        await interaction.edit_original_response(view=self)

    @discord.ui.button(label="No, retry the operation", style=discord.ButtonStyle.red)
    async def cancel(self: Self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Cancel button callback."""
        modal = type(self.previous_modal)(package=self.package, bot=self.bot)

        await interaction.response.send_modal(modal)

        self.disable_all()
        await interaction.edit_original_response(view=self)

    def disable_all(self: Self) -> None:
        """Disable both confirm and cancel buttons."""
        self.confirm.disabled = True
        self.cancel.disabled = True


class ReportView(discord.ui.View):
    """Report view."""

    def __init__(self: Self, bot: Bot, payload: Package) -> None:
        self.bot = bot
        self.payload = payload
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check that only those with the 'Vipyr Security' role can use this view."""
        if isinstance(interaction.user, discord.Member):
            return constants.Roles.vipyr_security in {role.id for role in interaction.user.roles}

        await interaction.response.send_message(
            f"No permissions: <@&{constants.Roles.vipyr_internal}> is required",
            ephemeral=True,
        )

        return False

    @discord.ui.button(label="Report", style=discord.ButtonStyle.red)
    async def report(self: Self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[type-arg]
        """Report a package."""
        modal = ConfirmReportModal(package=self.payload, bot=self.bot)
        await interaction.response.send_modal(modal)

        timed_out = await modal.wait()
        if not timed_out:
            button.disabled = True
            await interaction.edit_original_response(view=self)


def _build_package_scan_result_embed(scan_result: Package) -> discord.Embed:
    """Build the embed that shows the results of a package scan."""
    condition = (scan_result.score or 0) >= DragonflyConfig.threshold
    title, color = ("Malicious", 0xF70606) if condition else ("Benign", 0x4CBB17)

    embed = discord.Embed(
        title=f"{title} package found: {scan_result.name} @ {scan_result.version}",
        description=f"```YARA rules matched: {', '.join(scan_result.rules) or 'None'}```",
        color=color,
        timestamp=scan_result.queued_at,
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


def _build_all_packages_scanned_embed(scan_results: list[Package]) -> discord.Embed:
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
    @commands.hybrid_command()
    async def queue(self: Self, ctx: commands.Context, name: str, version: str) -> None:
        """Add a package to the Dragonfly scan queue."""
        try:
            await self.bot.dragonfly_services.queue_package(name=name, version=version)
            await ctx.send(f"Successfully queued package `{name} v{version}`")
        except aiohttp.ClientResponseError as http_error:
            status_code = http_error.status

            if status_code == HTTPStatus.NOT_FOUND:
                await ctx.send(f"Package `{name} v{version}` was not found on PyPI")

            if status_code == HTTPStatus.CONFLICT:
                scan_results = await self.bot.dragonfly_services.get_scanned_packages(
                    name=name,
                    version=version,
                )

                if scan_results:
                    embed = _build_package_scan_result_embed(scan_results[0])
                    await ctx.send(f"Package `{name} v{version}` has already been scanned.", embed=embed)
                else:
                    await ctx.send(f"Package `{name} v{version}` is already waiting to be scanned.")
        except Exception as e:
            await ctx.send(str(e))
            raise

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
            package = scan_results[0]
            embed = _build_package_scan_result_embed(package)
            await interaction.response.send_message(embed=embed, view=ReportView(self.bot, package))
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
