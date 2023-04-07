"""Main runner"""

import asyncio
from os import getenv

import aiohttp
import discord
import dotenv
from discord.ext import commands

from bot import constants
from bot.bot import Bot
from .utils.templates import JINJA_TEMPLATES

dotenv.load_dotenv()

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
        allowed_roles=roles,
        command_prefix=get_prefix,
        intents=intents,
        templates=JINJA_TEMPLATES,
    )

    async with bot:
        await bot.start(getenv("BOT_TOKEN"))


if __name__ == "__main__":
    asyncio.run(main())
