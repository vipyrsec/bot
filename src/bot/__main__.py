"""Main runner."""

import asyncio

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


def get_prefix(bot_: Bot, message_: discord.Message) -> list[str]:
    """Return a callable to check for the bot's prefix."""
    extras = constants.Bot.prefix.split(",")
    return commands.when_mentioned_or(*extras)(bot_, message_)


async def main() -> None:
    """Run the bot."""
    async with ClientSession(headers={"Content-Type": "application/json"}, timeout=ClientTimeout(total=30)) as session:
        dragonfly_services = DragonflyServices(
            session=session,
            base_url=constants.DragonflyConfig.api_url,
            access_client_id=constants.Dragonfly.client_id,
            access_client_secret=constants.Dragonfly.client_secret,
        )
        dragonfly_queue_services = {"production": dragonfly_services}
        if constants.DragonflyConfig.queue_clusters:
            dragonfly_queue_services = {
                name: DragonflyServices(
                    session=session,
                    base_url=cluster.api_url,
                    access_client_id=cluster.access_client_id,
                    access_client_secret=cluster.access_client_secret.get_secret_value(),
                )
                for name, cluster in constants.DragonflyConfig.queue_clusters.items()
            }

        bot = Bot(
            guild_id=constants.Guild.id,
            http_session=session,
            allowed_roles=list({discord.Object(id_) for id_ in constants.MODERATION_ROLES}),
            command_prefix=get_prefix,
            intents=intents,
            dragonfly_services=dragonfly_services,
            dragonfly_queue_services=dragonfly_queue_services,
        )

        await bot.start(constants.Bot.token)


if __name__ == "__main__":
    asyncio.run(main())
