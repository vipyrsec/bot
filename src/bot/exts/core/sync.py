"""Sync all application commands"""

import logging
from logging import getLogger

import discord
from discord.app_commands import AppCommand
from discord.ext import commands

from bot.bot import Bot

log = getLogger(__name__)
log.setLevel(logging.INFO)


class Sync(commands.Cog):
    """Sync all application commands"""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def _sync_commands(self) -> list[AppCommand]:
        """App command syncing logic. Returns a list of app commands that were synced."""
        tree = self.bot.tree
        guild = discord.Object(id=1033456860864466995)

        log.debug("Syncing tree...")
        tree.copy_global_to(guild=guild)
        synced_commands = await tree.sync(guild=guild)
        log.debug(
            "Synced %s commands: %s", len(synced_commands), ", ".join(command.name for command in synced_commands)
        )

        return synced_commands

    @commands.command(name="sync")
    @commands.has_permissions(administrator=True)
    async def sync_prefix(self, ctx: commands.Context) -> None:
        """Prefix command that syncs all application commands"""
        synced_commands = await self._sync_commands()

        await ctx.send(
            f"Synced {len(synced_commands)} commands: {', '.join(command.name for command in synced_commands)}"
        )

    @discord.app_commands.command(name="sync", description="Sync all application commands")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def sync_slash(self, interaction: discord.Interaction) -> None:
        """Slash command that syncs all application commands"""
        synced_commands = await self._sync_commands()

        await interaction.response.send_message(
            f"Synced {len(synced_commands)} commands: {', '.join(command.name for command in synced_commands)}",
            ephemeral=True,
        )


async def setup(bot: Bot) -> None:
    """Load the Sync cog."""
    await bot.add_cog(Sync(bot))
