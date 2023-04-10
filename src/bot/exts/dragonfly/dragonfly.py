"""
Download the most recent packages
from PyPI and filter them for WASP malware

Also writes the packages checked to a file
so that they can be skipped in the future

Finally write all malicious packages to a file
for later analysis
"""

import logging
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
import itertools

from . import _get_all_addresses

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
        default=f"Automated PyPi Malware Report",
        required=True,
        style=discord.TextStyle.short,
    )

    description = discord.ui.TextInput(
        label="Description",
        placeholder="Optional long description...",
        required=False,
        style=discord.TextStyle.long,
    )

    def __init__(self, *, email_template: Template, package: str, matches: Matches) -> None:
        super().__init__()
        self.email_template = email_template
        self.package = package
        self.matches = matches

    async def on_submit(self, interaction: discord.Interaction):
        content = self.email_template.render(
            package_url=f"https://pypi.org/project/{self.package}/",
            inspector_url=f"https://inspector.pypi.io/project/{self.package}/",
            matches=list(self.matches.items()),
            description=self.description.value,
        )

        addresses = _get_all_addresses()

        log.info(
            "Sending report to with sender %s with recipient %s with bcc %s",
            DragonflyConfig.sender,
            DragonflyConfig.recipient,
            ", ".join(addresses),
        )

        send_email(
            graph_client,
            sender=DragonflyConfig.sender,
            subject=self.subject.value,
            content=content,
            bcc_recipients=addresses,
        )

        await interaction.response.send_message("Successfully sent report.", ephemeral=True)


class AutoReportView(discord.ui.View):
    def __init__(self, *, email_template: Template, package: str, matches: dict[str, list[str]]):
        super().__init__(timeout=None)
        self.email_template = email_template
        self.package = package
        self.matches = matches

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
            matches=self.matches,
        )
        await interaction.response.send_modal(modal)

        button.style = discord.ButtonStyle.gray
        button.disabled = True
        await interaction.edit_original_response(view=self)


async def notify_malicious_package(
    *,
    email_template: Template,
    channel: discord.abc.Messageable,
    package: str,
    matches: dict[str, list[str]],
) -> None:
    """
    Sends a message to our Discord server,
    notifying us of a new malicious package
    and showing the matched rules
    """
    description = "\n".join(f"{filename}: {', '.join(rules)}" for filename, rules in matches.items())
    if len(description) >= 4000:
        log.info("Embed description is too long: %s", description)
        description = "Embed too long; file breakdown is not displayed\n" + ', '.join(*itertools.chain(rules for rules in matches.values()))

    embed = discord.Embed(
        title=f"New malicious package: {package}",
        description=f"```{description}```",
        color=0xF70606,
    )

    embed.add_field(
        name="\u200B",
        value=f"[Inspector](https://inspector.pypi.io/project/{package}/)",
        inline=True,
    )

    embed.add_field(
        name="\u200B",
        value=f"[PyPI](https://pypi.org/project/{package})",
        inline=True,
    )

    embed.set_footer(text=f"DragonFly V2")

    view = AutoReportView(email_template=email_template, package=package, matches=matches)
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
) -> dict[str, list[str]] | None:
    async with http_session.post(
        DragonflyConfig.dragonfly_api_url + "/check/",
        json={"package_name": package_name},
    ) as res:
        if res.status != 200:
            return None

        json = await res.json()
        return json["matches"]


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

            matches = await check_package(package_metadata.title, http_session=bot.http_session)
            pypi_package_scan.rule_matches = matches
            session.add(pypi_package_scan)
            session.commit()

            if matches is None:
                log.info(f"{package_metadata.title} is a wheel, skipping")

            if matches:
                log.info(f"{package_metadata.title} is malicious!")
                await notify_malicious_package(
                    email_template=bot.templates["malicious_pypi_package_email"],
                    channel=alerts_channel,
                    package=package_metadata.title,
                    matches=matches,
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
