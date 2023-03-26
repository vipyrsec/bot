from itertools import islice
from math import ceil
from typing import Generator

import discord
from discord.ext import commands

from bot.bot import Bot
from bot.constants import PyPiConfigs
from bot.pypi import get_packages
from bot.pypi.pypi import Package


class EmbedPaginator:
    def __init__(self, packages: list[Package], per_page: int) -> None:
        self.idx = 0
        self.per_page = per_page
        self.packages = packages
        self.embeds = self._build_embeds()

    def _batched(self) -> Generator[list[Package], None, None]:
        it = iter(self.packages)
        while True:
            batch = list(islice(it, self.per_page))
            if not batch:
                break
            yield batch

    def _build_embeds(self) -> list[discord.Embed]:
        embeds: list[discord.Embed] = []

        for page_number, packages in enumerate(self._batched()):
            embed = discord.Embed(
                title="Recently uploaded packages",
                color=discord.Color.blurple(),
            )

            for package in packages:
                embed.add_field(
                    name=package.title,
                    value="\n".join((
                        package.description or "*No description provided*",
                        "",
                        discord.utils.format_dt(package.publication_date),
                        f"[Package Link]({package.package_link})",
                        f"[Inspector Link]({package.inspector_link})",
                        package.author if PyPiConfigs.show_author_in_embed and package.author else ""
                    ))
                )

            embed.set_footer(text=f"Page {page_number+1}/{ceil(len(self.packages) / self.per_page)}")

            embeds.append(embed)

        return embeds

    @property
    def current(self) -> discord.Embed:
        return self.embeds[self.idx]

    @property
    def is_at_last(self) -> bool:
        return self.idx == len(self.embeds) - 1

    @property
    def is_at_first(self) -> bool:
        return self.idx == 0

    def next(self) -> None:
        if self.idx < len(self.embeds) - 1:
            self.idx += 1

    def prev(self) -> None:
        if self.idx > 0:
            self.idx -= 1

    def first(self) -> None:
        self.idx = 0

    def last(self) -> None:
        self.idx = len(self.embeds) - 1

class PackageViewer(discord.ui.View):
    def __init__(self, *, packages: list[Package], author: discord.User | discord.Member) -> None:
        self.paginator = EmbedPaginator(packages, per_page=3)
        self.author = author
        self.message: discord.Message | None = None

        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("This paginator is not for you!", ephemeral=True)
            return False

        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

        await self.message.edit(view=self)

    @discord.ui.button(label="First", style=discord.ButtonStyle.blurple)
    async def first(self, interaction: discord.Interaction, _) -> None:
        self.paginator.first()
        await interaction.response.edit_message(embed=self.paginator.current)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
    async def prev(self, interaction: discord.Interaction, _) -> None:
        self.paginator.prev()
        await interaction.response.edit_message(embed=self.paginator.current)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next(self, interaction: discord.Interaction, _) -> None:
        self.paginator.next()
        await interaction.response.edit_message(embed=self.paginator.current)

    @discord.ui.button(label="Last", style=discord.ButtonStyle.blurple)
    async def last(self, interaction: discord.Interaction, _) -> None:
        self.paginator.last()
        await interaction.response.edit_message(embed=self.paginator.current)

class Pypi(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.command()
    async def pypi(self, ctx: commands.Context) -> None:
        packages = await get_packages(self.bot.http_session)
        view = PackageViewer(packages=packages, author=ctx.author)
        message = await ctx.send(embed=view.paginator.current, view=view)
        view.message = message

async def setup(bot: Bot) -> None:
    await bot.add_cog(Pypi(bot))
