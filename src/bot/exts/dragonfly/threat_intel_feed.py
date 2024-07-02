"""Threat Intelligence Feed Cog."""

import json
import logging
import re
from io import BytesIO
from logging import getLogger
from typing import Any
from zipfile import ZipFile

import aiohttp
import discord
from discord.ext import commands, tasks

from bot import constants
from bot.bot import Bot
from bot.dragonfly_services import Package

log = getLogger(__name__)
log.setLevel(logging.INFO)

_p = re.compile(r"https://inspector.pypi.io/project/(?P<name>\w+)/(?P<version>[\w.]+)/.*")


def build_github_link_from_path(path: str) -> str:
    """Build a GitHub link to the given path."""
    segments = path.split("/")
    path = "/".join(segments[1:])

    return f"https://github.com/{constants.ThreatIntelFeed.repository}/blob/main/{path}"


def parse_package_info_from_inspector_url(inspector_url: str) -> tuple[str, str] | None:
    """Return a tuple of package name and version, parsed from the inspector URL. None if it couldn't be parsed."""
    if g := _p.match(inspector_url):
        name = g.group("name")
        version = g.group("version")

        return name, version

    return None


def search(d: dict, key: Any) -> Any | None:  # noqa: ANN401 - we can't know the type of the dict ahead of time
    """Recursively search for the first occurence of a key in a dict. None if not found."""
    for k, v in d.items():
        if k == key:
            return v

        if isinstance(v, dict) and (val := search(v, key)):
            return val

    return None


def build_embed(package: Package, path: str, inspector_url: str) -> discord.Embed:
    """Return the embed to be sent in the threat intelligence feed."""
    if package.reported_at:
        ts = discord.utils.format_dt(package.reported_at, style="F")
        description = f"We already reported this package at {ts}"
        color = discord.Color.green()
    else:
        description = f"We didn't catch this package! Here are our matched rules: ```{', '.join(package.rules)}```"
        color = discord.Colour.red()

    embed = discord.Embed(
        title=f"New Report: {package.name} v{package.version}",
        description=description,
        color=color,
        url=build_github_link_from_path(path),
    )

    embed.add_field(name="Inspector URL", value=f"[Inspector URL]({inspector_url})")

    return embed


def build_package_not_found_embed(name: str, version: str, path: str) -> discord.Embed:
    """Return the embed for when a report was filed for a package which we don't have records for."""
    return discord.Embed(
        title="Package not found!",
        description=(
            f"A report was filed for {name} v{version}, "
            "however we don't have any records for this package in our database. "
            "This means that we are missing packages, please investigate this!"
        ),
        color=discord.Color.red(),
        url=build_github_link_from_path(path),
    )


async def fetch_zipfile(http_client: aiohttp.ClientSession) -> ZipFile:
    """Download the source zipfile from GitHub for the feed source repository."""
    url = f"https://api.github.com/repos/{constants.ThreatIntelFeed.repository}/zipball"
    headers = {"Authorization": f"Bearer {constants.ThreatIntelFeed.access_token}"}

    async with http_client.get(url, headers=headers) as res:
        res.raise_for_status()
        b = await res.content.read()

        buffer = BytesIO(b)
        return ZipFile(buffer)


class ThreatIntelFeed(commands.Cog):
    """Threat Intelligence Feed Cog."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.reports_seen: set[str] = set()

    @tasks.loop(seconds=constants.ThreatIntelFeed.interval)
    async def watcher(self) -> None:
        """Watch the GitHub repository for changes."""
        zipfile = await fetch_zipfile(self.bot.http_session)
        paths = {path for path in zipfile.namelist() if path.endswith(".json")}

        channel = self.bot.get_channel(constants.ThreatIntelFeed.channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.error("Threat intel feed channel is not messageable")
            return

        # The first time around, just add all the reports to our "seen reports" set
        if len(self.reports_seen) == 0:
            self.reports_seen |= paths
            return

        for path in paths:
            if path in self.reports_seen:
                continue

            content = json.loads(zipfile.read(path).decode())
            inspector_url: str | None = search(content, "inspector_url")
            if not inspector_url:
                log.error("Inspector URL not found in %s, skipping", path)
                continue

            match parse_package_info_from_inspector_url(inspector_url):
                case name, version:
                    results = await self.bot.dragonfly_services.get_scanned_packages(name=name, version=version)
                    package = results[0] if results else None

                    if package:
                        embed = build_embed(package, path, inspector_url)
                    else:
                        embed = build_package_not_found_embed(name, version, path)

                    await channel.send(embed=embed)

                case None:
                    log.error('Unable to parse inspector URL: "%s" in %s, skipping', inspector_url, path)
                    continue

    @watcher.before_loop
    async def before_watcher(self) -> None:
        """Before first task run hook."""
        await self.bot.wait_until_ready()


async def setup(bot: Bot) -> None:
    """Extension setup."""
    cog = ThreatIntelFeed(bot)
    task = cog.watcher
    if not task.is_running:
        task.start()
    await bot.add_cog(cog)
