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
    async with ClientSession(headers={"Content-Type": "application/json"}, timeout=ClientTimeout(total=30)) as session:
        dragonfly_services = DragonflyServices(
            session=session,
            base_url=constants.Dragonfly.base_url,
            auth_url=constants.Dragonfly.auth_url,
            audience=constants.Dragonfly.audience,
            client_id=constants.Dragonfly.client_id,
            client_secret=constants.Dragonfly.client_secret,
            username=constants.Dragonfly.username,
            password=constants.Dragonfly.password,
        )

        bot = Bot(
            guild_id=constants.Guild.id,
            http_session=session,
            allowed_roles=list({discord.Object(id_) for id_ in constants.MODERATION_ROLES}),
            command_prefix=get_prefix,
            intents=intents,
            dragonfly_services=dragonfly_services,
        )

        await bot.start(constants.Bot.token)


if __name__ == "__main__":
    asyncio.run(main())
