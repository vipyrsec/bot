from discord.ext import commands
import discord
from discord import app_commands, Interaction
from sqlalchemy import delete, select
from bot.bot import Bot
from bot.database.models import SubscriberEmails
from bot.database import session
from . import _get_registered_addresses
import typing as t


class Subscribe(commands.GroupCog, name="subscribe", description="Have the auto-reporter BCC you"):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command()
    async def add(self, interaction: Interaction, address: str) -> None:
        row = SubscriberEmails(address=address, discord_id=str(interaction.user.id))
        session.add(row)
        session.commit()

        await interaction.response.send_message(f"Registered {address}", ephemeral=True)

    @app_commands.command()
    async def list(self, interaction: Interaction) -> None:
        addresses = _get_registered_addresses(str(interaction.user.id))
        embed = discord.Embed(
            title="Your registered addresses",
            description="\n".join(addresses),
            color=discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command()
    async def remove(self, interaction: Interaction, address: str) -> None:
        stmt = delete(SubscriberEmails).where(SubscriberEmails.address == address)
        result = session.execute(stmt)
        session.commit()

        if result.rowcount > 0:
            await interaction.response.send_message("Successfully removed record", ephemeral=True)
        else:
            await interaction.response.send_message("No records with that address found", ephemeral=True)

    @remove.autocomplete("address")
    async def remove_autocomplete(self, interaction: Interaction, current: str) -> t.List[app_commands.Choice[str]]:
        addresses = _get_registered_addresses(str(interaction.user.id))
        return [
            app_commands.Choice(name=address, value=address)
            for address in addresses
            if current.lower() in address.lower()
        ]


async def setup(bot: Bot) -> None:
    await bot.add_cog(Subscribe(bot))
