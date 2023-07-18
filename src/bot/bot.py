"""Bot subclass"""

import logging

import discord
from discord.ext import commands
from letsbuilda.pypi import PyPIServices
from pydis_core import BotBase
from pydis_core.utils import scheduling
from sentry_sdk import push_scope

from bot import exts
from bot.constants import DragonflyAuthentication
from bot.exts import pypi

log = logging.getLogger(__name__)


class CommandTree(discord.app_commands.CommandTree):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)

    async def on_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        if isinstance(error, discord.app_commands.MissingRole):
            log.warn(
                "User '%s' attempted to run command '%s', which requires the '%s' role which the user is missing.",
                interaction.user,
                interaction.command.name if interaction.command else "None",
                error.missing_role,
            )

            await interaction.response.send_message(
                f"The '{error.missing_role}' role is required to run this command.", ephemeral=True
            )
        elif isinstance(error, discord.app_commands.NoPrivateMessage):
            log.warn(
                "User '%s' attempted to run command '%s', which cannot be invoked from DMs",
                interaction.user,
                interaction.command,
            )

            await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        else:
            raise error


class Bot(BotBase):
    """Bot implementation."""

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        """
        Initialise the base bot instance.
        Args:
            allowed_roles: A list of role IDs that the bot is allowed to mention.
            http_session (aiohttp.ClientSession): The session to use for the bot.
        """
        super().__init__(
            *args,
            tree_cls=CommandTree,
            **kwargs,
        )

        self.all_extensions: frozenset[str] | None = None

    async def authorize(self) -> None:
        log.info("Authenticating")
        url = f"https://{DragonflyAuthentication.domain}/oauth/token"
        json = dict(
            client_id=DragonflyAuthentication.client_id,
            client_secret=DragonflyAuthentication.client_secret,
            username=DragonflyAuthentication.username,
            password=DragonflyAuthentication.password,
            grant_type="password",
            audience=DragonflyAuthentication.audience,
        )
        async with self.http_session.post(url, json=json) as res:
            res.raise_for_status()
            json = await res.json()
            self.access_token: str = json["access_token"]

    async def setup_hook(self) -> None:
        """Default async initialisation method for discord.py."""
        log.debug("setup_hook")
        await super().setup_hook()

        log.info("Performing initial authentication")
        await self.authorize()

        # This is not awaited to avoid a deadlock with any cogs that have
        # wait_until_guild_available in their cog_load method.
        log.debug("load_extensions")
        scheduling.create_task(self.load_extensions(exts))

        client = PyPIServices(self.http_session)
        self.package_view = pypi.PackageViewer(packages=(await client.get_rss_feed(client.NEWEST_PACKAGES_FEED_URL)))
        self.add_view(self.package_view)

    async def on_error(self, event: str, *args, **kwargs) -> None:
        """Log errors raised in event listeners rather than printing them to stderr."""
        with push_scope() as scope:
            scope.set_tag("event", event)
            scope.set_extra("args", args)
            scope.set_extra("kwargs", kwargs)

            log.exception(f"Unhandled exception in {event}.")
