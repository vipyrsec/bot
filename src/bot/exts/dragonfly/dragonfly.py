"""Download the most recent packages from PyPI and use Dragonfly to check them for malware"""

import logging
from logging import getLogger

import discord
from discord.ext import commands, tasks
from jinja2 import Template
from letsbuilda.pypi import PackageMetadata, PyPIServices
from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.bot import Bot
from bot.constants import DragonflyConfig
from bot.database import engine
from bot.database.models import PyPIPackageScan
from bot.utils.mailer import send_email
from bot.utils.microsoft import build_ms_graph_client

from ._api import DragonflyAPIException, PackageScanResult, check_package

log = getLogger(__name__)
log.setLevel(logging.INFO)

graph_client = build_ms_graph_client()

Matches = dict[str, list[str]]


class ConfirmReportModal(discord.ui.Modal):
    title = "Confirm Report"

    recipient = discord.ui.TextInput(
        label="To",
        placeholder="To",
        default=str(DragonflyConfig.recipient),
        required=True,
        style=discord.TextStyle.short,
    )

    subject = discord.ui.TextInput(
        label="Subject",
        placeholder="Subject",
        default="Automated PyPi Malware Report",
        required=True,
        style=discord.TextStyle.short,
    )

    description = discord.ui.TextInput(
        label="Description",
        placeholder="Optional long description...",
        required=False,
        style=discord.TextStyle.long,
    )

    def __init__(self, *, email_template: Template, package: PackageScanResult) -> None:
        super().__init__()
        self.package = package
        self.email_template = email_template

    async def on_submit(self, interaction: discord.Interaction):
        assert self.package.highest_score_distribution is not None  # for typechecker
        content = self.email_template.render(
            package=self.package,
            description=self.description.value,
            rules=", ".join(self.package.highest_score_distribution.matches),
        )

        log.info(
            "Sending report to with sender %s with recipient %s with bcc %s",
            DragonflyConfig.sender,
            DragonflyConfig.recipient,
            ", ".join(DragonflyConfig.bcc),
        )

        log.info(
            "User %s reported package %s with description %s",
            interaction.user,
            self.package.name,
            self.description,
        )

        log_channel = interaction.client.get_channel(DragonflyConfig.logs_channel_id)
        if isinstance(log_channel, discord.abc.Messageable):
            await log_channel.send(
                f"User {interaction.user.mention} "
                f"reported package `{self.package.name}` "
                f"with description `{self.description}`"
            )

        await interaction.response.send_message("Successfully sent report.", ephemeral=True)

        send_email(
            graph_client,
            sender=DragonflyConfig.sender,
            reply_to_recipients=[DragonflyConfig.reply_to],
            to_recipients=[self.recipient.value],
            subject=self.subject.value,
            content=content,
            bcc_recipients=list(DragonflyConfig.bcc),
        )


class AutoReportView(discord.ui.View):
    def __init__(self, *, email_template: Template, package: PackageScanResult):
        super().__init__(timeout=None)
        self.email_template = email_template
        self.package = package

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False

        if isinstance(interaction.user, discord.User):
            return False

        if interaction.guild.get_role(DragonflyConfig.security_role_id) in interaction.user.roles:
            return True

        await interaction.response.send_message("You cannot use that!", ephemeral=True)
        return False

    @discord.ui.button(
        label="Report",
        emoji="✉️",
        custom_id="REPORT_BTN",
        style=discord.ButtonStyle.red,
    )
    async def report_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        modal = ConfirmReportModal(
            email_template=self.email_template,
            package=self.package,
        )
        await interaction.response.send_modal(modal)

        button.style = discord.ButtonStyle.gray
        button.disabled = True
        await interaction.edit_original_response(view=self)


def _build_package_scan_result_embed(package: PackageScanResult) -> discord.Embed:
    assert package.highest_score_distribution is not None
    """Build the embed that shows the results of a package scan"""

    embed = discord.Embed(
        title=f"New malicious package: {package.name}",
        description=f"```YARA rules matched: {', '.join(package.highest_score_distribution.matches)}```",
        color=0xF70606,
    )

    embed.add_field(
        name="\u200B",
        value=f"[Inspector]({package.highest_score_distribution.inspector_link})",
        inline=True,
    )

    embed.add_field(
        name="\u200B",
        value=f"[PyPI]({package.pypi_link})",
        inline=True,
    )

    embed.set_footer(text="DragonFly V2")

    return embed


async def notify_malicious_package(
    *,
    email_template: Template,
    channel: discord.abc.Messageable,
    package: PackageScanResult,
) -> None:
    """
    Sends a message to our Discord server,
    notifying us of a new malicious package
    and showing the matched rules
    """

    embed = _build_package_scan_result_embed(package)

    view = AutoReportView(email_template=email_template, package=package)
    await channel.send(f"<@&{DragonflyConfig.dragonfly_alerts_role_id}>", embed=embed, view=view)


async def send_completion_webhook(channel: discord.abc.Messageable, packages: list[str]):
    """Post the complete list of packages checked to the logs"""
    if len(packages) > 0:
        formatted_packages = "\n".join(packages)
        text = f"```{formatted_packages}\n```"
    else:
        text = "_no new packages since last scan_"

    embed = discord.Embed(
        title="DragonFly Logs",
        description=f"Packages scanned:\n{text}",
        color=0xF70606,
    )
    embed.set_footer(text="DragonFly V2")

    await channel.send(embed=embed)


async def run(
    bot: Bot,
    *,
    log_channel: discord.abc.Messageable,
    alerts_channel: discord.abc.Messageable,
) -> None:
    """Script entrypoint"""
    packages_to_check: list[PackageMetadata] = []
    client = PyPIServices(http_session=bot.http_session)
    packages_to_check.extend(await client.get_rss_feed(client.NEWEST_PACKAGES_FEED_URL))
    packages_to_check.extend(await client.get_rss_feed(client.PACKAGE_UPDATES_FEED_URL))
    log.info("Fetched %d packages" % len(packages_to_check))

    scanned_packages: list[str] = []
    for package_metadata in packages_to_check:
        log.info("Starting scan of package '%s'", package_metadata.title)
        with Session(engine) as session:
            pypi_package_scan: PyPIPackageScan | None = session.scalars(
                select(PyPIPackageScan)
                .where(PyPIPackageScan.name == package_metadata.title)
                .order_by(PyPIPackageScan.published_date.desc())
            ).fist()

            if pypi_package_scan is not None:
                if pypi_package_scan.flagged is True:
                    log.info("Already flagged %s!" % package_metadata.title)
                    continue
                if pypi_package_scan.published_date == package_metadata.publication_date:
                    log.info("Already scanned %s!" % package_metadata.title)
                    continue

            scanned_packages.append(package_metadata.title)
            pypi_package_scan = PyPIPackageScan(
                name=package_metadata.title, error=None, published_date=package_metadata.publication_date
            )

            try:
                result = await check_package(package_metadata.title, http_session=bot.http_session)
            except DragonflyAPIException as e:
                pypi_package_scan.error = str(e)
                session.add(pypi_package_scan)
                session.commit()

                log.warn("Dragonfly API Error: %s", str(e))
                continue

            # Package is safe
            if result is None:
                session.add(pypi_package_scan)
                session.commit()
                log.info(
                    "Package %s has no distribution with the highest score (all are 0), it is not malicious",
                    package_metadata.title,
                )
                continue

            result.highest_score_distribution

            distribution = result.highest_score_distribution
            if distribution is None:
                session.add(pypi_package_scan)
                session.commit()
                log.info("Package %s has no files with score greater than 0", result.name)
                continue

            pypi_package_scan.rule_matches = distribution.matches
            pypi_package_scan.flagged = True
            session.add(pypi_package_scan)
            session.commit()

            threshold = DragonflyConfig.threshold
            if distribution.score >= threshold:
                log.info(
                    f"{package_metadata.title} had a score of {distribution.score} "
                    f"which exceeded the threshold of {threshold}"
                )
                await notify_malicious_package(
                    email_template=bot.templates["malicious_pypi_package_email"],
                    channel=alerts_channel,
                    package=result,
                )
            else:
                log.info(
                    "%s had a score of %s which does not meet the threshold of %s",
                    result.name,
                    distribution.score,
                    threshold,
                )

    log.info("done!")
    await send_completion_webhook(log_channel, scanned_packages)


class Dragonfly(commands.Cog):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        super().__init__()

    @tasks.loop(seconds=DragonflyConfig.interval)
    async def scan_loop(self) -> None:
        logs_channel = self.bot.get_channel(DragonflyConfig.logs_channel_id)
        assert isinstance(logs_channel, discord.abc.Messageable)

        alerts_channel = self.bot.get_channel(DragonflyConfig.alerts_channel_id)
        assert isinstance(alerts_channel, discord.abc.Messageable)

        await run(
            self.bot,
            alerts_channel=alerts_channel,
            log_channel=logs_channel,
        )

    @commands.command()
    async def start(self, ctx: commands.Context) -> None:
        if self.scan_loop.is_running():
            await ctx.send("Task is already running.")
        else:
            self.scan_loop.start()
            await ctx.send("Started task...")

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

    @discord.app_commands.checks.has_role("Security")
    @discord.app_commands.command(name="scan", description="Scans a package")
    async def scan(self, interaction: discord.Interaction, package: str, version: str | None = None) -> None:
        try:
            results = await check_package(package, version, http_session=self.bot.http_session)
        except DragonflyAPIException as e:
            log.error(
                "Dragonfly API Exception when user '%s' tried to scan package '%s' with version '%s'. "
                "Upstream error: %s",
                str(interaction.user),
                package,
                version,
                str(e),
            )

            await interaction.response.send_message(str(e), ephemeral=True)
            return None

        embed = _build_package_scan_result_embed(results)
        view = AutoReportView(email_template=self.bot.templates["malicious_pypi_package_email"], package=results)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: Bot) -> None:
    await bot.add_cog(Dragonfly(bot))
