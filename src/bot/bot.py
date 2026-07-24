"""Bot subclass."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any, Self, TypedDict, Unpack, cast

import discord
from aiohttp import ClientSession
from pydis_core import BotBase
from pydis_core.utils import scheduling
from sentry_sdk import push_scope

from bot import exts
from bot.dragonfly_services import DragonflyServices

log = logging.getLogger(__name__)


class BotInitOptions(TypedDict):
    """Typed arguments forwarded to the untyped pydis BotBase initializer."""

    guild_id: int
    allowed_roles: list[discord.Object]
    http_session: ClientSession
    command_prefix: Callable[[Bot, discord.Message], list[str]]
    intents: discord.Intents


class CommandTree(discord.app_commands.CommandTree[discord.Client]):
    """Custom command tree that handles errors raised by commands."""

    def __init__(self: Self, bot: discord.Client) -> None:
        super().__init__(bot)

    async def on_error(
        self: Self,
        interaction: discord.Interaction[discord.Client],
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
        dragonfly_services: DragonflyServices,
        **options: Unpack[BotInitOptions],
    ) -> None:
        """Initialise the base bot instance.

        Args:
            allowed_roles: A list of role IDs that the bot is allowed to mention.
            http_session (aiohttp.ClientSession): The session to use for the bot.
        """
        # BotBase's published annotations leave its variadic arguments unknown.
        base_init = cast("Callable[..., None]", vars(BotBase)["__init__"])
        base_init(
            self,
            tree_cls=CommandTree,
            **options,
        )

        self.dragonfly_services = dragonfly_services
        self.all_extensions: frozenset[str] | None = None

    async def setup_hook(self: Self) -> None:
        """Default async initialisation method for discord.py."""
        log.debug("setup_hook")
        await super().setup_hook()

        # This is not awaited to avoid a deadlock with any cogs that have
        # wait_until_guild_available in their cog_load method.
        log.debug("load_extensions")
        create_task = cast("Callable[[Coroutine[Any, Any, None]], object]", vars(scheduling)["create_task"])
        create_task(self.load_extensions(exts))

    async def on_error(self: Self, event: str, *args: object, **kwargs: object) -> None:
        """Log errors raised in event listeners rather than printing them to stderr."""
        with push_scope() as scope:
            scope.set_tag("event", event)
            scope.set_extra("args", args)
            scope.set_extra("kwargs", kwargs)

            log.exception(f"Unhandled exception in {event}.")
