"""Bot subclass"""

import logging
from types import ModuleType

import aiohttp
import discord
from discord.ext import commands
from jinja2 import Template

from bot import exts
from bot.utils.extensions import walk_extensions

log = logging.getLogger(__name__)


class Bot(commands.Bot):
    """Bot implementation."""

    def __init__(
        self,
        *args,
        allowed_roles: list,
        http_session: aiohttp.ClientSession,
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
            **kwargs,
        )

        self.http_session = http_session

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
        
        guild = discord.Object(id=1033456860864466995)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
