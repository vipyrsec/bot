"""Sync all application commands."""

import logging
from logging import getLogger
from typing import Self

import discord
from discord.app_commands import AppCommand
from discord.ext import commands

from bot import constants
from bot.bot import Bot

log = getLogger(__name__)
log.setLevel(logging.INFO)


class Sync(commands.Cog):
    """Sync all application commands."""

    def __init__(self: Self, bot: Bot) -> None:
        self.bot = bot

    async def _sync_commands(self: Self) -> list[AppCommand]:
        """App command syncing logic. Returns a list of app commands that were synced."""
        tree = self.bot.tree
        guild = discord.Object(id=constants.Guild.id)

        log.debug("Syncing tree...")
        tree.copy_global_to(guild=guild)
        synced_commands = await tree.sync(guild=guild)
        log.debug(
            "Synced %s commands: %s",
            len(synced_commands),
            ", ".join(command.name for command in synced_commands),
        )

        return synced_commands  # type: ignore[no-any-return]

    @commands.command(name="sync")
    @commands.has_permissions(administrator=True)
    async def sync_prefix(self: Self, ctx: commands.Context) -> None:  # type: ignore[type-arg]
        """Prefix command that syncs all application commands."""
        synced_commands = await self._sync_commands()

        await ctx.send(
            f"Synced {len(synced_commands)} commands: {', '.join(command.name for command in synced_commands)}",
        )

    @discord.app_commands.command(name="sync", description="Sync all application commands")  # type: ignore[arg-type]
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def sync_slash(self: Self, interaction: discord.Interaction) -> None:  # type: ignore[type-arg]
        """Slash command that syncs all application commands."""
        synced_commands = await self._sync_commands()

        await interaction.response.send_message(
            f"Synced {len(synced_commands)} commands: {', '.join(command.name for command in synced_commands)}",
            ephemeral=True,
        )


async def setup(bot: Bot) -> None:
    """Load the Sync cog."""
    await bot.add_cog(Sync(bot))
