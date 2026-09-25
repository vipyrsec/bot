"""Durable OpenGrep summaries and private evidence pagination."""

from __future__ import annotations

import logging
import re
from typing import Self
from urllib.parse import quote, unquote, urlsplit

import discord

from bot.bot import Bot
from bot.constants import Roles
from bot.dragonfly_services import OpenGrepDetails, OpenGrepResult, ScanStatus

SUMMARY_TITLE = "OpenGrep evidence"
FINDINGS_CUSTOM_ID = "dragonfly:opengrep:findings:v1"
PAGE_LIMIT = 1900
FINDING_LIMIT = 1800
PACKAGE_PATH_PARTS = 3
log = logging.getLogger(__name__)


def safe_text(value: str) -> str:
    """Escape untrusted Markdown and mentions without interpreting package text."""
    return re.sub(r"([\\`*_~|>\[\]])", r"\\\1", value.replace("@", "@\u200b"))


def summary_embed(name: str, version: str, result: OpenGrepDetails | OpenGrepResult | None) -> discord.Embed:
    """Keep the exact package reference in the durable message, not process memory."""
    embed = discord.Embed(
        title=SUMMARY_TITLE,
        url=f"https://pypi.org/project/{quote(name, safe='')}/{quote(version, safe='')}/",
        color=discord.Color.blue(),
    )
    if result is None:
        embed.description = "Pending · OpenGrep evidence will appear here when available."
        return embed
    status = result.status.value.capitalize()
    if result.status is ScanStatus.FINISHED:
        status = "Partial" if result.fail_reason else "Complete"
    rules = len({finding.rule_id for finding in result.findings})
    embed.description = (
        f"**{status}** · {len(result.findings)} findings · {rules} rules\nUse **View findings** for details."
    )
    if result.fail_reason:
        embed.add_field(
            name="Scan details", value=discord.utils.escape_mentions(result.fail_reason)[:500], inline=False
        )
    embed.set_footer(text="Source-level evidence; the package verdict is unchanged.")
    return embed


def set_evidence_field(embed: discord.Embed, value: str) -> None:
    """Replace the placeholder without changing the package verdict or its evidence."""
    for index, field in enumerate(embed.fields):
        if field.name == "OpenGrep":
            embed.set_field_at(index, name="OpenGrep", value=value, inline=False)
            return
    embed.add_field(name="OpenGrep", value=value, inline=False)


def add_evidence(
    embed: discord.Embed, name: str, version: str, result: OpenGrepDetails | OpenGrepResult | None
) -> None:
    """Keep the summary and restart-safe package reference in the original alert."""
    summary = summary_embed(name, version, result)
    embed.url = summary.url
    value = summary.description or ""
    if summary.fields:
        value += "\n" + (summary.fields[0].value or "")
    set_evidence_field(embed, value)


def evidence_pages(result: OpenGrepDetails) -> list[str]:
    """Include every stored finding and location in bounded pages."""
    heading = f"**OpenGrep · {result.status.value} · {len(result.findings)} findings**"
    if result.fail_reason:
        heading += "\n" + discord.utils.escape_mentions(result.fail_reason)[:500]
    pages = [heading]
    for finding in sorted(result.findings, key=lambda finding: finding.rule_id):
        rule = safe_text(finding.rule_id)[:200]
        path = safe_text(finding.path)[:200]
        url = quote(finding.inspector_url, safe=":/%")
        location = f"[{path}:{finding.start_line}-{finding.end_line}]({url}#line.{finding.start_line})"
        message = discord.utils.escape_mentions(finding.message)[:800]
        evidence = discord.utils.escape_mentions(finding.evidence)[:32]
        confidence = discord.utils.escape_mentions(finding.confidence)[:32]
        context = discord.utils.escape_mentions(finding.execution_context)[:64]
        block = f"**{rule}** · {evidence} / {confidence} / {context}\n{message}\n{location}"
        if len(block) > FINDING_LIMIT:  # Long Inspector URLs must not make the entire viewer fail.
            block = f"**{rule}**\n{message}\n{path}:{finding.start_line}-{finding.end_line}"
        if len(pages[-1]) + len(block) + 2 <= PAGE_LIMIT:
            pages[-1] += "\n\n" + block
        else:
            pages.append(block)
    if not result.findings:
        pages[0] += "\nNo stored findings." if result.status is ScanStatus.FINISHED else "\nNo findings available yet."
    return pages


class EvidencePages(discord.ui.View):
    """One private page cursor per investigator; the alert itself never paginates."""

    def __init__(self, result: OpenGrepDetails, owner_id: int) -> None:
        super().__init__(timeout=900)
        self.pages = evidence_pages(result)
        self.owner_id = owner_id
        self.index = 0
        self.update_buttons()

    @property
    def content(self) -> str:
        return f"{self.pages[self.index]}\n\nPage {self.index + 1}/{len(self.pages)}"

    def update_buttons(self) -> None:
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index == len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction[discord.Client]) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction[Bot], _button: discord.ui.Button[Self]) -> None:
        self.index = max(0, self.index - 1)
        self.update_buttons()
        await interaction.response.edit_message(
            content=self.content, view=self, allowed_mentions=discord.AllowedMentions.none()
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction[Bot], _button: discord.ui.Button[Self]) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        self.update_buttons()
        await interaction.response.edit_message(
            content=self.content, view=self, allowed_mentions=discord.AllowedMentions.none()
        )


class FindingsButton(discord.ui.Button[discord.ui.View]):
    """Resolve findings from a bot-authored message after any restart."""

    def __init__(self, bot: Bot) -> None:
        super().__init__(label="View findings", custom_id=FINDINGS_CUSTOM_ID, style=discord.ButtonStyle.secondary)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction[discord.Client]) -> None:
        if not isinstance(interaction.user, discord.Member) or Roles.vipyr_security not in {
            role.id for role in interaction.user.roles
        }:
            await interaction.response.send_message("You do not have permission to view this evidence.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        message = interaction.message
        if message is None or self.bot.user is None or message.author.id != self.bot.user.id:
            await interaction.followup.send("This message does not contain a valid OpenGrep reference.", ephemeral=True)
            return
        reference = next(
            (
                embed.url
                for embed in message.embeds
                if embed.title == SUMMARY_TITLE or any(field.name == "OpenGrep" for field in embed.fields)
            ),
            None,
        )
        parsed = urlsplit(reference or "")
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "pypi.org"
            or len(parts) != PACKAGE_PATH_PARTS
            or parts[0] != "project"
        ):
            await interaction.followup.send("This message does not contain a valid OpenGrep reference.", ephemeral=True)
            return
        try:
            result = await self.bot.dragonfly_services.get_opengrep_details(unquote(parts[1]), unquote(parts[2]))
        except Exception:
            log.exception("Failed to retrieve stored OpenGrep evidence.")
            await interaction.followup.send(
                "OpenGrep evidence is temporarily unavailable. Please try again.", ephemeral=True
            )
            return
        if result is None:
            await interaction.followup.send("No stored OpenGrep result yet. Please try again shortly.", ephemeral=True)
            return
        view = EvidencePages(result, interaction.user.id)
        await interaction.followup.send(
            content=view.content,
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class FindingsView(discord.ui.View):
    """Register the stable findings action globally at startup."""

    def __init__(self, bot: Bot) -> None:
        super().__init__(timeout=None)
        self.add_item(FindingsButton(bot))
