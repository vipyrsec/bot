"""Message utilities."""

import contextlib
import random
from collections.abc import Sequence
from logging import getLogger

import discord
from discord import Embed, Message
from discord.ext import commands
from discord.ext.commands import Context, MessageConverter
from pydis_core.utils import scheduling

from bot.bot import Bot
from bot.constants import MODERATION_ROLES, NEGATIVE_REPLIES

log = getLogger(__name__)


def format_user(user: discord.abc.User) -> str:
    """Return a string for `user` which has their mention and ID."""
    return f"{user.mention} (`{user.id}`)"


async def get_discord_message(ctx: Context, text: str) -> Message | str:
    """
    Attempt to convert a given `text` to a discord Message object and return it.

    Conversion will succeed if given a discord Message ID or link.
    Returns `text` if the conversion fails.
    """
    with contextlib.suppress(commands.BadArgument):
        return await MessageConverter().convert(ctx, text)


async def send_denial(ctx: Context, reason: str) -> discord.Message:
    """Send an embed denying the user with the given reason."""
    embed = discord.Embed(
        title=random.choice(NEGATIVE_REPLIES),
        description=reason,
        colour=discord.Colour.red(),
    )

    return await ctx.send(embed=embed)


async def get_text_and_embed(ctx: Context, text: str) -> tuple[str, Embed | None]:
    """
    Attempt to extract the text and embed from a possible link to a discord Message.

    Does not retrieve the text and embed from the Message if it is in a channel the user does
    not have read permissions in.

    Returns a tuple of:
        str: If `text` is a valid discord Message, the contents of the message, else `text`.
        Optional[Embed]: The embed if found in the valid Message, else None
    """
    embed: Embed | None = None

    msg = await get_discord_message(ctx, text)
    # Ensure the user has read permissions for the channel the message is in
    if isinstance(msg, Message):
        permissions = msg.channel.permissions_for(ctx.author)
        if permissions.read_messages:
            text = msg.clean_content
            # Take first embed because we can't send multiple embeds
            if msg.embeds:
                embed = msg.embeds[0]

    return text, embed


def reaction_check(
    reaction: discord.Reaction,
    user: discord.abc.User,
    bot: Bot,
    *,
    message_id: int,
    allowed_emoji: Sequence[str],
    allowed_users: Sequence[int],
    allow_mods: bool = True,
) -> bool:
    """
    Check if a reaction's emoji and author are allowed and the message is `message_id`.

    If the user is not allowed, remove the reaction. Ignore reactions made by the bot.
    If `allow_mods` is True, allow users with moderator roles even if they're not in `allowed_users`.
    """
    right_reaction = user != bot.user and reaction.message.id == message_id and str(reaction.emoji) in allowed_emoji
    if not right_reaction:
        return False

    is_moderator = allow_mods and any(role.id in MODERATION_ROLES for role in getattr(user, "roles", []))

    if user.id in allowed_users or is_moderator:
        log.debug(f"Allowed reaction {reaction} by {user} on {reaction.message.id}.")
        return True

    log.debug(f"Removing reaction {reaction} by {user} on {reaction.message.id}: disallowed user.")
    scheduling.create_task(
        reaction.message.remove_reaction(reaction.emoji, user),
        suppressed_exceptions=(discord.HTTPException,),
        name=f"remove_reaction-{reaction}-{reaction.message.id}-{user}",
    )
    return False
