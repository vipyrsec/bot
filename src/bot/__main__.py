"""Main runner"""

import asyncio
from os import getenv

import aiohttp
import discord
from discord.ext import commands
from bot import constants

from bot.bot import Bot

from bot.utils.microsoft import build_ms_graph_client

from .utils.templates import JINJA_TEMPLATES

from bot.log import setup_sentry

setup_sentry()

roles = getenv("ALLOWED_ROLES")
roles = [int(role) for role in roles.split(",")] if roles else []

intents = discord.Intents.default()
intents.message_content = True


def get_prefix(bot_, message_):
    """Get bot command prefixes"""
    extras = getenv("PREFIXES", ".").split(",")
    return commands.when_mentioned_or(*extras)(bot_, message_)


async def main() -> None:
    """Run the bot."""

    bot = Bot(
        guild_id=constants.Bot.guild_id,
        http_session=aiohttp.ClientSession(),
        graph_client=build_ms_graph_client(),
        allowed_roles=roles,
        command_prefix=get_prefix,
        intents=intents,
        templates=JINJA_TEMPLATES,
    )

    async with bot:
        await bot.start(constants.Bot.token)


if __name__ == "__main__":
    asyncio.run(main())
