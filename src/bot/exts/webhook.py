"""Cog to delete Discord webhooks."""

import json
import logging
import re
from http import HTTPStatus
from re import Match
from typing import Self

from discord import Colour, Message, NotFound
from discord.ext.commands import Cog

from bot.bot import Bot
from bot.constants import Channels, Colours, Icons, Roles
from bot.exts.core.log import Log
from bot.utils.messages import format_user

WEBHOOK_URL_RE = re.compile(
    r"(https?:\/\/(www\.|ptb\.|canary\.)?discord(app)?\.com\/api(\/v\d{1,2})?\/webhooks\/(\d{17,21})\/)([\w-]{68})",
    re.IGNORECASE,
)

ALERT_MESSAGE_TEMPLATE = (
    "{user}, looks like you posted a Discord webhook URL. Therefore, your "
    "message has been removed, and your webhook has been deleted. "
    "You can re-create it if you wish to. If you believe this was a "
    "mistake, please let us know."
)

log = logging.getLogger(__name__)


class WebhookRemover(Cog):
    """Scan messages to detect Discord webhooks links."""

    def __init__(self: Self, bot: Bot) -> None:
        self.bot = bot

    @property
    def log(self: Self) -> Log | None:
        """Get current instance of `Log`."""
        return self.bot.get_cog("Log")

    async def delete_and_respond(
        self: Self, message: Message, matches: Match[str]
    ) -> None:
        """Delete `message` and send a warning that it contained a Discord webhook."""
        webhook_url = matches[0]
        redacted_url = matches[1] + "xxx"

        async with self.bot.http_session.get(webhook_url) as response:
            webhook_metadata = await response.json()

        async with self.bot.http_session.delete(webhook_url) as response:
            # The Discord API Returns a 204 NO CONTENT response on success.
            deleted_successfully = response.status == HTTPStatus.NO_CONTENT

        # The webhook should only be actioned if it is the only content of a message,
        # and within the defined exemption parameters.
        user_roles = [role.id for role in message.author.roles]
        if all(
            [
                message.content != webhook_url,
                message.channel.category.id == Channels.soc_category,
                Roles.security in user_roles,
            ],
        ):
            return

        try:
            await message.delete()
        except NotFound:
            log.debug(
                f"Failed to remove webhook in message {message.id}: message already deleted."
            )
            return

        # Log to user
        await message.channel.send(
            ALERT_MESSAGE_TEMPLATE.format(user=message.author.mention)
        )

        if deleted_successfully:
            delete_state = "The webhook was successfully deleted."
        else:
            delete_state = "There was an error when deleting the webhook, it might have already been removed."

        # Display Bot icon as thumbnail
        if webhook_metadata.get("avatar") is not None:
            thumb = f"https://cdn.discordapp.com/avatars/{webhook_metadata['id']}/{webhook_metadata['avatar']}.webp"
        else:
            thumb = message.author.display_avatar.url

        # Log to moderators
        text = (
            f"{format_user(message.author)} posted a Discord webhook URL to {message.channel.mention}. {delete_state} "
            f"Webhook URL was `{redacted_url}`"
        )
        log.debug(text)
        await self.log.send_log_message(
            icon_url=Icons.token_removed,
            colour=Colour(Colours.soft_red),
            title="Discord webhook URL removed!",
            text=text,
            thumbnail=thumb,
            channel_id=Channels.mod_alerts,
        )

        # Log to SOC
        text = (
            f"{format_user(message.author)} posted a Discord webhook URL to {message.channel.mention}. {delete_state} "
            f"Webhook URL was `{webhook_url}`. Metadata was: \n"
            f"```\n{json.dumps(webhook_metadata, indent=4)}\n```"
        )
        await self.log.send_log_message(
            icon_url=Icons.token_removed,
            colour=Colour(Colours.soft_red),
            title="Discord webhook URL removed!",
            text=text,
            thumbnail=thumb,
            channel_id=Channels.soc_alerts,
        )

    @Cog.listener()
    async def on_message(self: Self, message: Message) -> None:
        """Check if a Discord webhook URL is in `message`."""
        # Ignore DMs; can't delete messages in there anyway.
        if not message.guild or message.author.bot:
            return

        if matches := WEBHOOK_URL_RE.search(message.content):
            await self.delete_and_respond(message, matches)

    @Cog.listener()
    async def on_message_edit(self: Self, _before: Message, after: Message) -> None:
        """Check if a Discord webhook URL is in the edited message `after`."""
        await self.on_message(after)


async def setup(bot: Bot) -> None:
    """Load `WebhookRemover` cog."""
    await bot.add_cog(WebhookRemover(bot))