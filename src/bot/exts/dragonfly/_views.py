"""Discord views for the Dragonfly cog."""

import logging
from typing import Self

import discord
from dragonfly_db_commons.models import Scan

from bot.bot import Bot
from bot.constants import Channels, MailerConfig
from bot.exts.dragonfly._builders import build_package_report_log_embed
from bot.utils.mailer import build_report_mail_body, send_email

log = logging.getLogger(__name__)


class ConfirmReportModal(discord.ui.Modal):
    """Modal for confirming a report."""

    recipient = discord.ui.TextInput(
        label="Recipient",
        placeholder="Recipient's Email Address",
        required=False,
        default="security@pypi.org",
        style=discord.TextStyle.short,
    )

    additional_information = discord.ui.TextInput(
        label="Additional information",
        placeholder="Additional information",
        style=discord.TextStyle.long,
    )

    inspector_url = discord.ui.TextInput(
        label="Inspector URL",
        placeholder="Inspector URL",
        style=discord.TextStyle.short,
    )

    def __init__(self: Self, *, package: Scan, bot: Bot) -> None:
        """Initialize the modal."""
        self.package = package
        self.bot = bot

        # set dynamic properties here because we can't set dynamic class attributes
        self.title = self._build_modal_title()
        if package.inspector_url:
            self.inspector_url.required = False
            self.inspector_url.default = package.inspector_url
        else:
            self.inspector_url.required = True

        if package.rules:
            self.additional_information.required = False
        else:
            self.additional_information.required = True
        self.inspector_url.default = package.inspector_url

        super().__init__(title=self._build_modal_title())

    async def on_error(self: Self, interaction: discord.Interaction, error: Exception) -> None:
        """Handle errors that occur in the modal."""
        await interaction.response.send_message("An unexpected error occured.", ephemeral=True)
        raise error

    def _build_modal_title(self: Self) -> str:
        """Build the modal title by truncating title if it's too long."""
        title = f"Confirm report for {self.package.name} v{self.package.version}"
        if len(title) >= 45:  # noqa: PLR2004
            title = title[:42] + "..."

        return title

    async def on_submit(self: Self, interaction: discord.Interaction) -> None:  # type: ignore[type-arg]
        """Submit the report."""
        # discord.py returns empty string "" if not filled out, we want it to be `None`
        additional_information = self.additional_information.value or None
        inspector_url = self.inspector_url.value or "None"

        log.info(
            "User %s reported package %s@%s with additional_information '%s' and inspector_url '%s'",
            interaction.user,
            self.package.name,
            self.package.version,
            additional_information,
            inspector_url,
        )

        log_channel = interaction.client.get_channel(Channels.reporting)
        if isinstance(log_channel, discord.abc.Messageable):
            embed = build_package_report_log_embed(
                member=interaction.user,
                package_name=self.package.name,
                package_version=self.package.version,
                description=additional_information,
                inspector_url=inspector_url,
            )
            await log_channel.send(embed=embed)

        content = build_report_mail_body(
            package_name=self.package.name,
            package_version=self.package.version,
            inspector_url=inspector_url,
            additional_information=additional_information or "No additional information provided",
            rules_matched=", ".join(rule.name for rule in self.package.rules) or "No rules matched",
        )

        await send_email(
            recipient_adresses=[self.recipient.value or MailerConfig.sender],
            bcc_recipient_addresses=list(MailerConfig.bcc_recipients),
            subject=f"Automated PyPI Malware Report: {self.package.name}@{self.package.version}",
            content=content,
        )

        await interaction.response.send_message("Reported!", ephemeral=True)


class ReportView(discord.ui.View):
    """Report view."""

    def __init__(self: Self, bot: Bot, package: Scan) -> None:
        self.bot = bot
        self.package = package
        super().__init__(timeout=None)

    @discord.ui.button(label="Report", style=discord.ButtonStyle.red)
    async def report(self: Self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[type-arg]
        """Report a package."""
        modal = ConfirmReportModal(package=self.package, bot=self.bot)
        await interaction.response.send_modal(modal)

        timed_out = await modal.wait()
        if not timed_out:
            button.disabled = True
            await interaction.edit_original_response(view=self)
