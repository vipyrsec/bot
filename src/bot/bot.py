"""Bot subclass."""

import logging
from typing import Self

import discord
from discord.ext import commands
from pydis_core import BotBase
from pydis_core.utils import scheduling
from sentry_sdk import push_scope
from sqlalchemy.ext.asyncio import AsyncEngine

from bot import exts
from bot.dragonfly_services import DragonflyServices

log = logging.getLogger(__name__)


class CommandTree(discord.app_commands.CommandTree):  # type: ignore[type-arg]
    """Custom command tree that handles errors raised by commands."""

    def __init__(self: Self, bot: commands.Bot) -> None:
        super().__init__(bot)

    async def on_error(
        self: Self,
        interaction: discord.Interaction,  # type: ignore[type-arg]
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """Override the default error handler to handle custom errors."""
        if isinstance(error, discord.app_commands.MissingRole):
            log.warning(
                "User '%s' attempted to run command '%s', which requires the '%s' role which the user is missing.",
                interaction.user,
                interaction.command.name if interaction.command else "None",
                error.missing_role,
            )

            await interaction.response.send_message(
                f"The '{error.missing_role}' role is required to run this command.",
                ephemeral=True,
            )
        elif isinstance(error, discord.app_commands.NoPrivateMessage):
            log.warning(
                "User '%s' attempted to run command '%s', which cannot be invoked from DMs",
                interaction.user,
                interaction.command,
            )

            await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
        else:
            raise error


class Bot(BotBase):  # type: ignore[misc]
    """Bot implementation."""

    def __init__(
        self: Self,
        *args: tuple,  # type: ignore[type-arg]
        database_engine: AsyncEngine,
        dragonfly_services: DragonflyServices,
        **kwargs: dict,  # type: ignore[type-arg]
    ) -> None:
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
        self.database_engine = database_engine
        self.dragonfly_services = dragonfly_services

    async def setup_hook(self: Self) -> None:
        """Default async initialisation method for discord.py."""  # noqa: D401
        log.debug("setup_hook")
        await super().setup_hook()

        # This is not awaited to avoid a deadlock with any cogs that have
        # wait_until_guild_available in their cog_load method.
        log.debug("load_extensions")
        scheduling.create_task(self.load_extensions(exts))

    async def on_error(self: Self, event: str, *args: tuple, **kwargs: dict) -> None:  # type: ignore[type-arg]
        """Log errors raised in event listeners rather than printing them to stderr."""
        with push_scope() as scope:
            scope.set_tag("event", event)
            scope.set_extra("args", args)
            scope.set_extra("kwargs", kwargs)

            log.exception(f"Unhandled exception in {event}.")
