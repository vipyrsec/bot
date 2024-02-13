"""Utility methods that build Discord embeds."""

from datetime import UTC, datetime

import discord
from dragonfly_db_commons.models import Scan


def build_package_report_log_embed(
    *,
    member: discord.User | discord.Member,
    package_name: str,
    package_version: str,
    description: str | None,
    inspector_url: str | None,
) -> discord.Embed:
    """Build an embed that has information on a recently reported package."""
    embed = discord.Embed(
        title=f"Package reported: {package_name} v{package_version}",
        color=discord.Colour.red(),
        description=description or "*No description provided*",
        timestamp=datetime.now(tz=UTC),
    )

    embed.set_author(name=member.name, icon_url=member.display_avatar.url)
    embed.add_field(name="Reported by", value=member.mention)
    if inspector_url:
        embed.add_field(name="Inspector URL", value=f"[Inspector URL]({inspector_url})")

    return embed


def build_all_packages_scanned_embed(scans: list[Scan]) -> discord.Embed:
    """Build the embed that shows a list of all packages scanned."""
    if scans:
        description = "\n".join(f"{scan.name} {scan.version}" for scan in scans)
        return discord.Embed(description=f"```{description}```")
    return discord.Embed(description="_No packages scanned_")


def build_package_scan_result_embed(scan: Scan) -> discord.Embed:
    """Build the embed that shows the results of a package scan."""
    embed = discord.Embed(
        title=f"Malicious package found: {scan.name} @ {scan.version}",
        description=f"```YARA rules matched: {', '.join(rule.name for rule in scan.rules) or 'None'}```",
        color=0xF70606,
    )

    embed.add_field(
        name="\u200b",
        value=f"[Inspector]({scan.inspector_url})",
        inline=True,
    )

    embed.add_field(
        name="\u200b",
        value=f"[PyPI](https://pypi.org/project/{scan.name}/{scan.version})",
        inline=True,
    )

    return embed
