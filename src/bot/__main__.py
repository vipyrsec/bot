"""Main runner."""

import asyncio

import aiohttp
import discord
from discord.ext import commands

from bot import constants
from bot.bot import Bot
from bot.log import setup_sentry

setup_sentry()

intents = discord.Intents.default()
intents.message_content = True

def get_prefix(bot_, message_):
    extras = constants.Bot.prefix.split(",")
    return commands.when_mentioned_or(*extras)(bot_, message_)

async def main() -> None:
    """Run the bot."""
    async with aiohttp.ClientSession() as session:
        bot = Bot(
            guild_id=constants.Guild.id,
            http_session=session,
            allowed_roles=list({discord.Object(id_) for id_ in constants.MODERATION_ROLES}),
            command_prefix=get_prefix,
            intents=intents,
        )

        await bot.start(constants.Bot.token)


if __name__ == "__main__":
    asyncio.run(main())
