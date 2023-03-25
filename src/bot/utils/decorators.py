"""Decorators"""

import logging
from typing import Callable

from discord.ext import commands
from discord.ext.commands import Context
from sqlalchemy import select

from bot.database import session
from bot.database.models import Permissions, RolesPermissions

log = logging.getLogger(__name__)


def with_permission(permission: Permissions) -> Callable:
    """Check if user has permision"""

    async def predicate(ctx: Context) -> bool:
        """The predicate"""
        if not ctx.guild:  # Return False in a DM
            log.debug(
                f"{ctx.author} tried to use the '{ctx.command.name}'command from a DM. "
                "This command is restricted by the with_permission decorator. Rejecting request."
            )
            return False

        permissions_roles_query = session.execute(
            select(RolesPermissions.role_id)
            .where(RolesPermissions.permission == permission.value)
            .where(RolesPermissions.guild_id == ctx.guild.id)
        )
        permissions_roles = permissions_roles_query.scalars().all()

        for role in ctx.author.roles:
            if role.id in permissions_roles:
                log.debug(f"{ctx.author} has the '{role.name}' role, and passes the check.")
                return True

        log.debug(
            f"{ctx.author} does not have the required permission to use "
            f"the '{ctx.command.name}' command, so the request is rejected."
        )
        return False

    return commands.check(predicate)
