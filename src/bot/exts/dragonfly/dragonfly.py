"""Download the most recent packages from PyPI and use Dragonfly to check them for malware."""

import logging
from datetime import UTC, datetime, timedelta
from logging import getLogger
from typing import Self

import aiohttp
import discord
import sentry_sdk
from discord.ext import commands, tasks
from discord.utils import format_dt

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

    @discord.ui.button(label="Report", style=discord.ButtonStyle.red)
    async def report(self: Self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[type-arg]
        """Report a package."""
        modal = ConfirmReportModal(package=self.payload, bot=self.bot)
        await interaction.response.send_modal(modal)

        timed_out = await modal.wait()
        if not timed_out:
            button.disabled = True
            await interaction.edit_original_response(view=self)


class NoteModal(discord.ui.Modal, title="Add a note"):
    """A modal that allows users to add a note to a package."""

    _interaction: discord.Interaction | None = None
    note_content = discord.ui.TextInput(
        label="Content",
        placeholder="Enter the note content here",
        min_length=1,
        max_length=1000,  # Don't want to overfill the embed
    )

    def __init__(self, embed: discord.Embed, view: discord.ui.View) -> None:
        super().__init__()

        self.embed = embed
        self.view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Modal submit callback."""
        if not interaction.response.is_done():
            await interaction.response.defer()
        self._interaction = interaction

        content = f"{self.note_content.value} • {interaction.user.mention}"

        # We need to check what fields the embed has to determine where to add the note
        # If the embed has no fields, we add the note and return
        # Otherwise, we need to make sure the note is added after the event log
        # This involves clearing the fields and re-adding them in the correct order
        # Which is why we save the event log in a variable

        match len(self.embed.fields):
            case 0:  # Package is awaiting triage, no notes or event log
                notes = [content]
                event_log = None
            case 1:  # Package either has notes or event log
                if self.embed.fields[0].name == "Notes":
                    notes = [self.embed.fields[0].value, content]
                else:
                    event_log = self.embed.fields[0].value
                    notes = [content]
                self.embed.clear_fields()
            case 2:  # Package has both notes and event log
                if self.embed.fields[0].name == "Notes":
                    notes = [self.embed.fields[0].value, content]
                    event_log = self.embed.fields[1].value
                else:
                    notes = [self.embed.fields[1].value, content]
                    event_log = self.embed.fields[0].value
                self.embed.clear_fields()

        self.embed.add_field(name="Notes", value="\n".join(notes), inline=False)

        if event_log:
            self.embed.add_field(name="Event log", value=event_log, inline=False)

        await interaction.message.edit(embed=self.embed, view=self.view)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
    ) -> None:
        """Handle errors that occur in the modal."""
        await interaction.response.send_message(
            "An unexpected error occured.",
            ephemeral=True,
        )
        raise error


class MalwareView(discord.ui.View):
    """View for the malware triage system."""

    message: discord.Message | None = None

    def __init__(
        self: Self,
        embed: discord.Embed,
        bot: Bot,
        payload: Package,
    ) -> None:
        self.embed = embed
        self.bot = bot
        self.payload = payload
        self.event_log = []

        super().__init__(timeout=None)

    async def add_event(self, message: str) -> None:
        """Add an event to the event log."""
        # Much like earlier, we need to check the fields of the embed to determine where to add the event log
        match len(self.embed.fields):
            case 0:
                pass
            case 1:
                if self.embed.fields[0].name == "Event log":
                    self.embed.clear_fields()
            case 2:
                if self.embed.fields[0].name == "Event log":
                    self.embed.clear_fields()
                elif self.embed.fields[1].name == "Event log":
                    self.embed.remove_field(1)

        self.event_log.append(
            message,
        )  # For future reference, we save the event log in a variable
        self.embed.add_field(
            name="Event log",
            value="\n".join(self.event_log),
            inline=False,
        )

    async def update_status(self, status: str) -> None:
        """Update the status of the package in the embed."""
        self.embed.set_footer(text=status)

    def get_timestamp(self) -> str:
        """Return the current timestamp, formatted in Discord's relative style."""
        return format_dt(datetime.now(UTC), style="R")

    @discord.ui.button(
        label="Report",
        style=discord.ButtonStyle.red,
    )
    async def report(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """Report package and update the embed."""
        self.approve.disabled = False
        await self.add_event(
            f"Reported by {interaction.user.mention} • {self.get_timestamp()}",
        )
        await self.update_status("Flagged as malicious")

        self.embed.color = discord.Color.red()

        modal = ConfirmReportModal(package=self.payload, bot=self.bot)
        await interaction.response.send_modal(modal)

        timed_out = await modal.wait()
        if not timed_out:
            button.disabled = True
            await interaction.edit_original_response(view=self, embed=self.embed)

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.green,
    )
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """Approve package and update the embed."""
        self.report.disabled = False
        await self.add_event(
            f"Approved by {interaction.user.mention} • {self.get_timestamp()}",
        )
        await self.update_status("Flagged as benign")

        button.disabled = True

        self.embed.color = discord.Color.green()
        await interaction.response.edit_message(view=self, embed=self.embed)

    @discord.ui.button(
        label="Add note",
        style=discord.ButtonStyle.grey,
    )
    async def add_note(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        """Add note to the embed."""
        await interaction.response.send_modal(NoteModal(embed=self.embed, view=self))

    async def on_error(
        self,
        interaction: discord.Interaction[discord.Client],
        error: Exception,
        _item: discord.ui.Item,
    ) -> None:
        """Handle errors that occur in the view."""
        await interaction.response.send_message(
            "An unexpected error occured.",
            ephemeral=True,
        )
        raise error


def _build_package_scan_result_embed(scan_result: Package) -> discord.Embed:
    """Build the embed that shows the results of a package scan."""
    condition = (scan_result.score or 0) >= DragonflyConfig.threshold
    title, color = ("Malicious", 0xF70606) if condition else ("Benign", 0x4CBB17)

    embed = discord.Embed(
        title=f"{title} package found: {scan_result.name} @ {scan_result.version}",
        description=f"```YARA rules matched: {', '.join(scan_result.rules) or 'None'}```",
        color=color,
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


def _build_package_scan_result_triage_embed(
    scan_result: Package,
) -> discord.Embed:
    """Build the embed for the malware triage system."""
    embed = discord.Embed(
        title="View on Inspector",
        description=f"```{', '.join(scan_result.rules)}```",
        url=scan_result.inspector_url,
        color=discord.Color.orange(),
        timestamp=datetime.now(UTC),
    )
    embed.set_author(
        name=f"{scan_result.name}@{scan_result.version}",
        url=f"https://pypi.org/project/{scan_result.name}/{scan_result.version}",
        icon_url="https://seeklogo.com/images/P/pypi-logo-5B953CE804-seeklogo.com.png",
    )
    embed.set_footer(text="Awaiting triage")

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
            embed = _build_package_scan_result_triage_embed(result)
            view = MalwareView(embed=embed, bot=bot, payload=result)

            view.message = await alerts_channel.send(
                f"<@&{DragonflyConfig.alerts_role_id}>",
                embed=embed,
                view=view,
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
