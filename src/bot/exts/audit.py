"""Cog for package audition."""


import math
import random
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands, ui
from discord.ext import commands

from bot.bot import Bot
from bot.exts.dragonfly._api import PackageScanResult

from .dragonfly._api import lookup_package_info


class PaginatorView(ui.View):
    def __init__(
        self,
        *,
        member: discord.Member | discord.User,
        packages: list[PackageScanResult],
        per: int = 15,
    ) -> None:
        super().__init__(timeout=None)
        pages = math.ceil(len(packages) / per)
        self.member = member
        self.embeds = [
            self._build_embed(packages[i : i + per], page, pages)
            for page, i in enumerate(range(0, len(packages), per), start=1)
        ]
        self.current = 0

    @ui.button(emoji="◀️")
    async def previous(self, interaction: discord.Interaction, _) -> None:
        if self.current == 0:
            self.current = len(self.embeds) - 1
        else:
            self.current -= 1

        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    @ui.button(emoji="⏹️")
    async def stop(self, interaction: discord.Interaction, button: ui.Button) -> None:
        self.previous.disabled = True
        button.disabled = True
        self.next.disabled = True

        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    @ui.button(emoji="▶️")
    async def next(self, interaction: discord.Interaction, _) -> None:
        if self.current == len(self.embeds) - 1:
            self.current = 0
        else:
            self.current += 1

        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user == self.member:
            return True

        await interaction.response.send_message("This paginator is not for you!", ephemeral=True)
        return False

    def _build_embed(self, packages: list[PackageScanResult], page: int, total: int) -> discord.Embed:
        embed = discord.Embed(
            title="Package Audit",
            description="\n".join(
                f"[{package.name} {package.version}]"
                f"(https://inspector.pypi.io/project/{package.name}/{package.version})"
                for package in packages
            ),
        )

        embed.set_author(name=f"Requested by {self.member.name}", icon_url=self.member.display_avatar.url)
        embed.set_footer(text=f"Page {page}/{total}")

        return embed


class Audit(commands.Cog):
    """Cog for package auditing."""

    def __init__(
        self,
        bot: Bot,
    ) -> None:
        self.bot = bot

    @app_commands.command(name="audit", description="Randomly pick packages and display them")
    async def audit(self, interaction: discord.Interaction, hours: int, amount: int) -> None:
        """
        Recalls for scanned packages within a given time frame and amount.

        Parameters
        ----------
        hours : int
                The number of hours relative to now to look back from

        amount : int
                 The amount of random packages that should be chosen

        """
        # Defer immediately because it make take longer than 3 seconds to respond
        await interaction.response.defer(thinking=True)

        since = datetime.now(tz=UTC) - timedelta(hours=hours)

        packages = await lookup_package_info(bot=self.bot, since=since)
        packages = random.sample(packages, k=amount)

        view = PaginatorView(member=interaction.user, packages=packages)
        await interaction.followup.send(embed=view.embeds[0], view=view)


async def setup(bot: Bot) -> None:
    await bot.add_cog(Audit(bot))
