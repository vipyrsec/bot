"""Download the most recent packages from PyPI and use Dragonfly to check them for malware"""

import logging
from dataclasses import dataclass
from logging import getLogger

import discord
from aiohttp.client import ClientSession
from discord.ext import commands, tasks
from jinja2 import Template
from letsbuilda.pypi import PyPIServices
from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.bot import Bot
from bot.constants import DragonflyConfig
from bot.database import engine
from bot.database.models import PyPIPackageScan
from bot.utils.mailer import send_email
from bot.utils.microsoft import build_ms_graph_client

log = getLogger(__name__)
log.setLevel(logging.INFO)

graph_client = build_ms_graph_client()

Matches = dict[str, list[str]]


@dataclass
class PackageScanResult:
    """Package scan result from the API"""

    name: str
    most_malicious_file: str
    matches: list[str]
    pypi_link: str
    inspector_link: str
    score: int


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
        self.email_template = email_template
        self.package = package

    async def on_submit(self, interaction: discord.Interaction):
        content = self.email_template.render(package=self.package, description=self.description.value)

        log.info(
            "Sending report to with sender %s with recipient %s with bcc %s",
            DragonflyConfig.sender,
            DragonflyConfig.recipient,
            ", ".join(DragonflyConfig.bcc),
        )

        send_email(
            graph_client,
            sender=DragonflyConfig.sender,
            to_recipients=[self.recipient.value],
            subject=self.subject.value,
            content=content,
            bcc_recipients=list(DragonflyConfig.bcc),
        )

        await interaction.response.send_message("Successfully sent report.", ephemeral=True)


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

    embed = discord.Embed(
        title=f"New malicious package: {package.name}",
        description=f"```YARA rules matched: {', '.join(package.matches)}```",
        color=0xF70606,
    )

    embed.add_field(
        name="\u200B",
        value=f"[Inspector]({package.inspector_link})",
        inline=True,
    )

    embed.add_field(
        name="\u200B",
        value=f"[PyPI]({package.pypi_link})",
        inline=True,
    )

    embed.set_footer(text="DragonFly V2")

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


async def check_package(
    package_name,
    *,
    http_session: ClientSession,
) -> PackageScanResult | None:
    async with http_session.post(
        DragonflyConfig.dragonfly_api_url + "/check/",
        json={"package_name": package_name},
    ) as res:
        if res.status != 200:
            return None

        json = await res.json()
        return PackageScanResult(**json)


async def run(
    bot: Bot,
    *,
    log_channel: discord.abc.Messageable,
    alerts_channel: discord.abc.Messageable,
) -> None:
    """Script entrypoint"""
    client = PyPIServices(http_session=bot.http_session)
    new_packages_metadata = await client.get_new_packages_feed()
    log.info("Fetched %d new packages" % len(new_packages_metadata))

    scanned_packages: list[str] = []
    for package_metadata in new_packages_metadata:
        with Session(engine) as session:
            pypi_package_scan: PyPIPackageScan | None = session.scalars(
                select(PyPIPackageScan).filter_by(name=package_metadata.title)
            ).first()
            if pypi_package_scan is not None:
                log.info("Already checked %s!" % package_metadata.title)
                continue
            else:
                scanned_packages.append(package_metadata.title)
                pypi_package_scan = PyPIPackageScan(name=package_metadata.title, error=None)

            result = await check_package(package_metadata.title, http_session=bot.http_session)
            if result is None:
                log.info("%s: Dragonfly API returned non-200 response", package_metadata.title)
                pypi_package_scan.error = "Dragonfly API returned non-200 response"
                session.add(pypi_package_scan)
                session.commit()
                continue

            pypi_package_scan.rule_matches = result.matches
            session.add(pypi_package_scan)
            session.commit()

            if result.matches:
                log.info(f"{package_metadata.title} is malicious!")
                await notify_malicious_package(
                    email_template=bot.templates["malicious_pypi_package_email"],
                    channel=alerts_channel,
                    package=result,
                )
            else:
                log.info(f"{package_metadata.title} is safe")

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
    async def stop(self, ctx: commands.Context) -> None:
        if self.scan_loop.is_running():
            self.scan_loop.stop()
            await ctx.send("Stopping task...")
        else:
            await ctx.send("Task is not running.")


async def setup(bot: Bot) -> None:
    await bot.add_cog(Dragonfly(bot))
