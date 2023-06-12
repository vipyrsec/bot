"""Bot subclass"""

import logging
from types import ModuleType

import aiohttp
import discord
from discord.ext import commands
from jinja2 import Template
from msgraph.core import GraphClient

from bot import exts
from bot.utils.extensions import walk_extensions
from bot.exts import pypi

from letsbuilda.pypi import PyPIServices

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


class Bot(commands.Bot):
    """Bot implementation."""

    def __init__(
        self,
        *args,
        allowed_roles: list,
        http_session: aiohttp.ClientSession,
        graph_client: GraphClient,
        templates: dict[str, Template],
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
            allowed_roles=allowed_roles,
            tree_cls=CommandTree,
            **kwargs,
        )

        self.http_session = http_session

        self.graph_client = graph_client

        self.templates = templates

        self.all_extensions: frozenset[str] | None = None

        

    async def load_extensions(self, module: ModuleType) -> None:
        """
        Load all the extensions within the given module and save them to ``self.all_extensions``.
        This should be ran in a task on the event loop to avoid deadlocks caused by ``wait_for`` calls.
        """
        self.all_extensions = walk_extensions(module)
        log.debug(f"{self.all_extensions=}")

        for extension in self.all_extensions:
            log.debug(f"loading {extension=}")
            await self.load_extension(extension)

    async def setup_hook(self) -> None:
        """Default async initialisation method for discord.py."""
        log.debug("setup_hook")
        await super().setup_hook()

        log.debug("load_extensions")
        await self.load_extensions(exts)
        client = PyPIServices(self.http_session)
        self.package_view = pypi.PackageViewer(packages=(await client.get_rss_feed(client.NEWEST_PACKAGES_FEED_URL)))
        self.add_view(self.package_view)