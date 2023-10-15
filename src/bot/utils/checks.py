from discord.ext.commands import CheckFailure, Context, NoPrivateMessage, has_any_role


async def has_any_role_check(ctx: Context, *roles: str | int) -> bool:
    """
    Returns True if the context's author has any of the specified roles.

    `roles` are the names or IDs of the roles for which to check.
    False is always returns if the context is outside a guild.
    """
    try:
        return await has_any_role(*roles).predicate(ctx)
    except CheckFailure:
        return False


async def has_no_roles_check(ctx: Context, *roles: str | int) -> bool:
    """
    Returns True if the context's author doesn't have any of the specified roles.

    `roles` are the names or IDs of the roles for which to check.
    False is always returns if the context is outside a guild.
    """
    try:
        return not await has_any_role(*roles).predicate(ctx)
    except NoPrivateMessage:
        return False
    except CheckFailure:
        return True
