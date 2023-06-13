"""Cog for interacting with PyPI"""

from itertools import islice
from math import ceil
from typing import Generator

import discord
from discord.ext import commands
from letsbuilda.pypi import PackageMetadata, PyPIServices

from bot.constants import PyPiConfigs


class EmbedPaginator:
    """Paginate embeds"""

    def __init__(self, packages: list[PackageMetadata], per_page: int) -> None:
        self.idx = 0
        self.per_page = per_page
        self.packages = packages
        self.embeds = self._build_embeds()

    def _batched(self) -> Generator[list[PackageMetadata], None, None]:
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
                    value="\n".join(
                        (
                            package.description or "*No description provided*",
                            "",
                            discord.utils.format_dt(package.publication_date),
                            f"[Package Link]({package.package_link})",
                            f"[Inspector Link](https://inspector.pypi.io/project/{package.title})",
                            package.author if PyPiConfigs.show_author_in_embed and package.author else "",
                        )
                    ),
                )

            embed.set_footer(text=f"Page {page_number + 1}/{ceil(len(self.packages) / self.per_page)}")

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
    """Package viewer"""

    def __init__(self, *, packages: list[PackageMetadata]) -> None:
        self.paginator = EmbedPaginator(packages, per_page=3)
        self.message: discord.Message | None = None

        super().__init__(timeout=None)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

        await self.message.edit(view=self)

    @discord.ui.button(label="First", custom_id='first', style=discord.ButtonStyle.blurple)
    async def first(self, interaction: discord.Interaction, _) -> None:
        self.paginator.first()
        await interaction.response.edit_message(embed=self.paginator.current)

    @discord.ui.button(label="Previous", custom_id='previous', style=discord.ButtonStyle.blurple)
    async def prev(self, interaction: discord.Interaction, _) -> None:
        self.paginator.prev()
        await interaction.response.edit_message(embed=self.paginator.current)

    @discord.ui.button(label="Next", custom_id='next', style=discord.ButtonStyle.blurple)
    async def next(self, interaction: discord.Interaction, _) -> None:
        self.paginator.next()
        await interaction.response.edit_message(embed=self.paginator.current)

    @discord.ui.button(label="Last", custom_id='last', style=discord.ButtonStyle.blurple)
    async def last(self, interaction: discord.Interaction, _) -> None:
        self.paginator.last()
        await interaction.response.edit_message(embed=self.paginator.current)


class Pypi(commands.Cog):
    """Cog for interacting with PyPI"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def pypi(self, ctx: commands.Context) -> None:
        await ctx.send(embed=self.bot.package_view.paginator.current, view=self.bot.package_view)
        

async def setup(bot) -> None:
    """Setup the cog on the bot"""
    await bot.add_cog(Pypi(bot))
