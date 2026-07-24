"""Message utilities."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import discord
from discord import Embed, Message
from discord.ext import commands

if TYPE_CHECKING:
    from bot.bot import Bot


def format_user(user: discord.abc.User) -> str:
    """Return a string for `user` which has their mention and ID."""
    return f"{user.mention} (`{user.id}`)"


async def get_discord_message(ctx: commands.Context[Bot], text: str) -> Message | str:
    """Attempt to convert a given `text` to a discord Message object and return it.

    Conversion will succeed if given a discord Message ID or link.
    Returns `text` if the conversion fails.
    """
    with contextlib.suppress(commands.BadArgument):
        return await commands.MessageConverter().convert(ctx, text)
    return text


async def get_text_and_embed(ctx: commands.Context[Bot], text: str) -> tuple[str, Embed | None]:
    """Attempt to extract the text and embed from a possible link to a discord Message.

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
        permissions = msg.channel.permissions_for(ctx.author)  # type: ignore[arg-type]
        if permissions.read_messages:
            text = msg.clean_content
            # Take first embed because we can't send multiple embeds
            if msg.embeds:
                embed = msg.embeds[0]

    return text, embed
