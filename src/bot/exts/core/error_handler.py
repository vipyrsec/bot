"""Error handling."""

import logging
import math
import random
from collections.abc import Iterable
from typing import Self

from discord import Embed, Message
from discord.ext import commands
from sentry_sdk import push_scope

from bot.bot import Bot
from bot.constants import NEGATIVE_REPLIES, Colours
from bot.utils.commands import get_command_suggestions
from bot.utils.exceptions import APIError, MovedCommandError

log = logging.getLogger(__name__)

QUESTION_MARK_ICON = "https://cdn.discordapp.com/emojis/512367613339369475.png"


class CommandErrorHandler(commands.Cog):
    """The error handler."""

    def __init__(self: Self, bot: Bot) -> None:
        self.bot = bot

    @staticmethod
    def revert_cooldown_counter(command: commands.Command, message: Message) -> None:  # type: ignore[type-arg]
        """Undoes the last cooldown counter for user-error cases."""
        if command._buckets.valid:  # noqa: SLF001 -- Underscored attribute
            bucket = command._buckets.get_bucket(message)  # type: ignore[arg-type] # noqa: SLF001 -- Underscored attribute
            bucket._tokens = min(bucket.rate, bucket._tokens + 1)  # type: ignore[union-attr] # noqa: SLF001 -- Underscored attribute
            logging.debug("Cooldown counter reverted as the command was not used correctly.")

    @staticmethod
    def error_embed(message: str, title: Iterable | str = NEGATIVE_REPLIES) -> Embed:  # type: ignore[type-arg]
        """Build a basic embed with red colour and either a random error title or a title provided."""
        embed = Embed(colour=Colours.soft_red)
        if isinstance(title, str):
            embed.title = title
        else:
            embed.title = random.choice(title)  # type: ignore[arg-type] # noqa: S311 -- wat
        embed.description = message
        return embed

    @commands.Cog.listener()
    async def on_command_error(  # noqa: C901,PLR0911 -- Probably refactor this?
        self: Self,
        ctx: commands.Context,  # type: ignore[type-arg]
        error: commands.CommandError,
    ) -> None:
        """Activates when a command raises an error."""
        if getattr(error, "handled", False):
            logging.debug(f"Command {ctx.command} had its error already handled locally; ignoring.")
            return

        parent_command = ""
        if subctx := getattr(ctx, "subcontext", None):
            parent_command = f"{ctx.command} "
            ctx = subctx

        error = getattr(error, "original", error)
        logging.debug(
            f"Error Encountered: {type(error).__name__} - {error!s}, "
            f"Command: {ctx.command}, "
            f"Author: {ctx.author}, "
            f"Channel: {ctx.channel}",
        )

        if isinstance(error, commands.CommandNotFound):
            await self.send_command_suggestion(ctx, ctx.invoked_with)  # type: ignore[arg-type]
            return

        if isinstance(error, commands.UserInputError):
            self.revert_cooldown_counter(ctx.command, ctx.message)  # type: ignore[arg-type]
            usage = f"```\n{ctx.prefix}{parent_command}{ctx.command} {ctx.command.signature}\n```"  # type: ignore[union-attr]
            embed = self.error_embed(f"Your input was invalid: {error}\n\nUsage:{usage}")
            await ctx.send(embed=embed)
            return

        if isinstance(error, commands.CommandOnCooldown):
            mins, secs = divmod(math.ceil(error.retry_after), 60)
            embed = self.error_embed(
                f"This command is on cooldown:\nPlease retry in {mins} minutes {secs} seconds.",
                NEGATIVE_REPLIES,
            )
            await ctx.send(embed=embed, delete_after=7.5)
            return

        if isinstance(error, commands.DisabledCommand):
            await ctx.send(embed=self.error_embed("This command has been disabled.", NEGATIVE_REPLIES))
            return

        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(embed=self.error_embed("This command can only be used in the server. ", NEGATIVE_REPLIES))
            return

        if isinstance(error, commands.BadArgument):
            self.revert_cooldown_counter(ctx.command, ctx.message)  # type: ignore[arg-type]
            embed = self.error_embed(
                "The argument you provided was invalid: "  # type: ignore[union-attr]
                f"{error}\n\nUsage:\n```\n{ctx.prefix}{parent_command}{ctx.command} {ctx.command.signature}\n```",  # type: ignore[arg-type]
            )
            await ctx.send(embed=embed)
            return

        if isinstance(error, commands.CheckFailure):
            await ctx.send(embed=self.error_embed("You are not authorized to use this command.", NEGATIVE_REPLIES))
            return

        if isinstance(error, APIError):
            await ctx.send(
                embed=self.error_embed(
                    f"There was an error when communicating with the {error.api}",  # type: ignore[attr-defined]
                    NEGATIVE_REPLIES,
                ),
            )
            return

        if isinstance(error, MovedCommandError):
            description = (
                f"This command, `{ctx.prefix}{ctx.command.qualified_name}` has moved to `{error.new_command_name}`.\n"  # type: ignore[attr-defined, union-attr]
                f"Please use `{error.new_command_name}` instead."
            )
            await ctx.send(embed=self.error_embed(description, NEGATIVE_REPLIES))
            return

        with push_scope() as scope:
            scope.user = {"id": ctx.author.id, "username": str(ctx.author)}

            scope.set_tag("command", ctx.command.qualified_name)  # type: ignore[union-attr]
            scope.set_tag("message_id", ctx.message.id)
            scope.set_tag("channel_id", ctx.channel.id)

            scope.set_extra("full_message", ctx.message.content)

            if ctx.guild is not None:
                scope.set_extra("jump_to", ctx.message.jump_url)

            log.exception(f"Unhandled command error: {error!s}", exc_info=error)

    async def send_command_suggestion(self: Self, ctx: commands.Context, command_name: str) -> None:  # type: ignore[type-arg]
        """Send user similar commands if any can be found."""
        command_suggestions = []
        if similar_command_names := get_command_suggestions(list(self.bot.all_commands.keys()), command_name):
            for similar_command_name in similar_command_names:
                similar_command = self.bot.get_command(similar_command_name)

                if not similar_command:
                    continue

                log_msg = "Cancelling attempt to suggest a command due to failed checks."
                try:
                    if not await similar_command.can_run(ctx):
                        log.debug(log_msg)
                        continue
                except commands.errors.CommandError:
                    log.debug(log_msg)
                    continue

                command_suggestions.append(similar_command_name)

            misspelled_content = ctx.message.content
            embed = Embed()
            embed.set_author(name="Did you mean:", icon_url=QUESTION_MARK_ICON)
            embed.description = "\n".join(
                misspelled_content.replace(command_name, cmd, 1) for cmd in command_suggestions
            )
            await ctx.send(embed=embed, delete_after=7.5)


async def setup(bot: Bot) -> None:
    """Load the ErrorHandler cog."""
    await bot.add_cog(CommandErrorHandler(bot))
