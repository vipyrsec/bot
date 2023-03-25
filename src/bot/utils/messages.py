"""Message utilities"""

import discord


def format_user(user: discord.abc.User) -> str:
    """Return a string for `user` which has their mention and ID."""
    return f"{user.mention} (`{user.id}`)"
