"""Main runner."""

import asyncio
from collections.abc import Callable

import discord
from aiohttp import ClientSession, ClientTimeout
from discord.ext import commands

from bot import constants
from bot.bot import Bot
from bot.log import setup_sentry

from .dragonfly_services import DragonflyServices

setup_sentry()

intents = discord.Intents.default()
intents.message_content = True


def get_prefix(bot_: Bot, message_: discord.Message) -> Callable[[Bot, discord.Message], list[str]]:
    """Return a callable to check for the bot's prefix."""
    extras = constants.Bot.prefix.split(",")
    return commands.when_mentioned_or(*extras)(bot_, message_)  # type: ignore[return-value]


async def main() -> None:
    """Run the bot."""
    async with ClientSession(headers={"Content-Type": "application/json"}, timeout=ClientTimeout(total=10)) as session:
        bot = Bot(
            guild_id=constants.Guild.id,  # type: ignore[arg-type]
            http_session=session,  # type: ignore[arg-type]
            allowed_roles=list({discord.Object(id_) for id_ in constants.MODERATION_ROLES}),  # type: ignore[arg-type]
            command_prefix=get_prefix,  # type: ignore[arg-type]
            intents=intents,  # type: ignore[arg-type]
        )

        bot.dragonfly_services = DragonflyServices(
            session=session,
            base_url=constants.Dragonfly.base_url,
            auth_url=constants.Dragonfly.auth_url,
            audience=constants.Dragonfly.audience,
            client_id=constants.Dragonfly.client_id,
            client_secret=constants.Dragonfly.client_secret,
            username=constants.Dragonfly.username,
            password=constants.Dragonfly.password,
        )

        await bot.start(constants.Bot.token)


if __name__ == "__main__":
    asyncio.run(main())
