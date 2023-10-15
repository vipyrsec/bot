import random
import textwrap
import typing as t
from datetime import UTC, datetime, timedelta

import discord
from discord import Interaction
from discord.ext.commands import Cog, Context, Greedy, group
from pydis_core.utils.channel import get_or_fetch_channel
from pydis_core.utils.scheduling import Scheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.bot import Bot
from bot.constants import (
    NEGATIVE_REPLIES,
    POSITIVE_REPLIES,
    Roles,
)
from bot.converters import DurationConverter
from bot.db.models import Reminder
from bot.errors import LockedResourceError
from bot.log import get_logger
from bot.utils.checks import has_no_roles_check
from bot.utils.lock import lock_arg
from bot.utils.messages import send_denial
from bot.utils.paginator import LinePaginator

log = get_logger(__name__)

LOCK_NAMESPACE = "reminder"
MAXIMUM_REMINDERS = 5
REMINDER_EDIT_CONFIRMATION_TIMEOUT = 60


class ModifyReminderConfirmationView(discord.ui.View):
    """A view to confirm modifying someone else's reminder by admins."""

    def __init__(self, author: discord.Member | discord.User) -> None:
        super().__init__(timeout=REMINDER_EDIT_CONFIRMATION_TIMEOUT)
        self.author = author
        self.result: bool = False

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Only allow interactions from the command invoker."""
        return interaction.user.id == self.author.id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.blurple, row=0)
    async def confirm(self, interaction: Interaction, _: discord.ui.Button) -> None:
        """Confirm the reminder modification."""
        await interaction.response.edit_message(view=None)
        self.result = True
        self.stop()

    @discord.ui.button(label="Cancel", row=0)
    async def cancel(self, interaction: Interaction, _: discord.ui.Button) -> None:
        """Cancel the reminder modification."""
        await interaction.response.edit_message(view=None)
        self.stop()


class Reminders(Cog):
    """Provide in-channel reminder functionality."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.scheduler = Scheduler(self.__class__.__name__)

    async def cog_unload(self) -> None:
        """Cancel scheduled tasks."""
        self.scheduler.cancel_all()

    async def cog_load(self) -> None:
        """Get all current reminders from the API and reschedule them."""
        await self.bot.wait_until_guild_available()

        async with self.bot.get_session() as session:
            query = select(Reminder)
            scalars = await session.scalars(query)
            reminders = scalars.all()

            for reminder in reminders:
                await self.ensure_valid_reminder(reminder, session=session)
                self.schedule_reminder(reminder)

    async def ensure_valid_reminder(self, reminder: Reminder, *, session: AsyncSession) -> discord.Message | None:
        """Ensure reminder channel and message can be fetched. Otherwise delete the reminder."""
        channel = await get_or_fetch_channel(self.bot, reminder.channel_id)
        if isinstance(channel, discord.abc.Messageable):
            try:
                return await channel.fetch_message(reminder.message_id)
            except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                log.exception("Error while ensuring validity of reminder")
        else:
            log.info(f"Could not access channel ID {reminder.channel_id} for reminder {reminder.id}")

        log.warning("Deleting reminder {reminder.id} as it is invalid")
        await session.merge(reminder)
        await session.delete(reminder)
        return None

    @staticmethod
    async def _send_confirmation(
        ctx: Context,
        on_success: str,
        reminder_id: int,
    ) -> None:
        """Send an embed confirming the reminder change was made successfully."""
        embed = discord.Embed(
            description=on_success,
            colour=discord.Colour.green(),
            title=random.choice(POSITIVE_REPLIES),
        )

        footer_str = f"ID: {reminder_id}"

        embed.set_footer(text=footer_str)

        await ctx.send(embed=embed)

    def schedule_reminder(self, reminder: Reminder) -> None:
        """A coroutine which sends the reminder once the time is reached, and cancels the running task."""
        self.scheduler.schedule_at(reminder.expiration, reminder.id, self.send_reminder(reminder.id))

    async def _reschedule_reminder(self, reminder: Reminder) -> None:
        """Reschedule a reminder object."""
        log.trace(f"Cancelling old task #{reminder.id}")
        self.scheduler.cancel(reminder.id)

        log.trace(f"Scheduling new task #{reminder.id}")
        self.schedule_reminder(reminder)

    @lock_arg(LOCK_NAMESPACE, "reminder_id", lambda id: id, raise_error=True)
    async def send_reminder(self, reminder_id: int) -> None:
        """Send the reminder, then delete it."""
        async with self.bot.get_session() as session:
            query = select(Reminder).where(Reminder.id == reminder_id)

            reminder = await session.scalar(query)
            if reminder is None:
                log.error(f"Reminder {reminder_id} not found while sending reminder")
                return

            try:
                channel = await get_or_fetch_channel(self.bot, reminder.channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                log.exception(
                    f"Unable to find message {reminder.message_id} " f"while sending reminder {reminder.id}, deleting",
                )

                await session.delete(reminder)
                return

            channel = self.bot.get_partial_messageable(reminder.channel_id)
            embed = discord.Embed()
            if datetime.now(UTC) > reminder.expiration + timedelta(seconds=30):
                embed.colour = discord.Colour.red()
                embed.set_author(name="Sorry, your reminder should have arrived earlier!")
            else:
                embed.colour = discord.Colour.og_blurple()
                embed.set_author(name="It has arrived!")

            # Let's not use a codeblock to keep emojis and mentions working. Embeds are safe anyway.
            embed.description = f"Here's your reminder: {reminder.content}"

            additional_mentions = " ".join(f"<@{target}>" for target in reminder.mention_ids)

            partial_message = channel.get_partial_message(reminder.message_id)
            jump_button = discord.ui.Button(
                label="Click here to go to your reminder",
                style=discord.ButtonStyle.link,
                url=partial_message.jump_url,
            )

            view = discord.ui.View()
            view.add_item(jump_button)

            try:
                await partial_message.reply(content=f"{additional_mentions}", embed=embed, view=view)
            except discord.HTTPException as e:
                log.info(
                    f"There was an error when trying to reply to a reminder invocation message, {e}, "
                    "fall back to using jump_url",
                )
                await channel.send(content=f"<@{reminder.author_id}> {additional_mentions}", embed=embed, view=view)

            await session.delete(reminder)
            log.debug(f"Deleting reminder #{reminder.id} (the user has been reminded).")

    @staticmethod
    def try_get_content_from_rely(message: discord.Message) -> str | None:
        """
        Attempts to get content from a message's  reply, if it exists.

        Differs from `pydis_core.utils.commands.clean_text_or_reply` as allows for messages with no content.
        """
        if (reference := message.reference) and isinstance((resolved_message := reference.resolved), discord.Message):
            if resolved_message.content:
                return resolved_message.content
            else:
                # If the replied message has no content (e.g. only attachments/embeds)
                return "*See referenced message.*"

        return None

    @group(name="remind", aliases=("reminder", "reminders", "remindme"), invoke_without_command=True)
    async def remind_group(
        self,
        ctx: Context,
        mentions: Greedy[discord.Member | discord.User],
        expiration: t.Annotated[datetime, DurationConverter],
        *,
        content: str | None = None,
    ) -> None:
        """
        Commands for managing your reminders.

        The `expiration` duration of `!remind new` supports the following symbols for each unit of time:
        - years: `Y`, `y`, `year`, `years`
        - months: `m`, `month`, `months`
        - weeks: `w`, `W`, `week`, `weeks`
        - days: `d`, `D`, `day`, `days`
        - hours: `H`, `h`, `hour`, `hours`
        - minutes: `M`, `minute`, `minutes`
        - seconds: `S`, `s`, `second`, `seconds`

        For example, to set a reminder that expires in 3 days and 1 minute, you can do `!remind new 3d1M Do something`.
        """
        await self.new_reminder(ctx, mentions=mentions, expiration=expiration, content=content)

    @remind_group.command(name="new", aliases=("add", "create"))
    async def new_reminder(
        self,
        ctx: Context,
        mentions: Greedy[discord.Member | discord.User],
        expiration: t.Annotated[datetime, DurationConverter],
        *,
        content: str | None = None,
    ) -> None:
        """
        Set yourself a simple reminder.

        The `expiration` duration supports the following symbols for each unit of time:
        - years: `Y`, `y`, `year`, `years`
        - months: `m`, `month`, `months`
        - weeks: `w`, `W`, `week`, `weeks`
        - days: `d`, `D`, `day`, `days`
        - hours: `H`, `h`, `hour`, `hours`
        - minutes: `M`, `minute`, `minutes`
        - seconds: `S`, `s`, `second`, `seconds`

        For example, to set a reminder that expires in 3 days and 1 minute, you can do `!remind new 3d1M Do something`.
        """
        # Get their current active reminders
        async with self.bot.get_session() as session:
            query = select(Reminder).where(Reminder.author_id == ctx.author.id)

            scalars = await session.scalars(query)
            reminders = scalars.all()

        if len(reminders) > MAXIMUM_REMINDERS:
            await send_denial(ctx, f"You have too many active reminders! ({MAXIMUM_REMINDERS})")
            return

        # Remove duplicate mentions
        mention_ids = {mention.id for mention in mentions}
        mention_ids.discard(ctx.author.id)
        mention_ids = list(mention_ids)

        content = content or self.try_get_content_from_rely(ctx.message)
        if not content:
            await send_denial(ctx, "You must have content in your message or reply to a message!")
            return

        # Now we can attempt to actually set the reminder.
        async with self.bot.get_session() as session:
            reminder = Reminder(
                channel_id=ctx.channel.id,
                message_id=ctx.message.id,
                author_id=ctx.author.id,
                expiration=expiration,
                mention_ids=mention_ids,
                content=content,
            )

            session.add(reminder)

            await session.flush()

            mention_string = (
                f"Your reminder will arrive on {discord.utils.format_dt(expiration, style='F')} "
                f"and will mention {len(mentions)} other(s)!"
                if mentions
                else "!"
            )

            if mentions:
                mention_string += f" and will mention {len(mentions)} other(s)"
            mention_string += "!"

            # Confirm to the user that it worked.
            await self._send_confirmation(
                ctx,
                on_success=mention_string,
                reminder_id=reminder.id,
            )

            self.schedule_reminder(reminder)

    @remind_group.command(name="list")
    async def list_reminders(self, ctx: Context) -> None:
        """View a paginated embed of all reminders for your user."""
        # Get all the user's reminders from the database.
        async with self.bot.get_session() as session:
            query = select(Reminder).where(Reminder.author_id == ctx.author.id).order_by(Reminder.expiration)
            scalars = await session.scalars(query)
            reminders = scalars.all()

            lines = []
            for reminder in reminders:
                expiry = discord.utils.format_dt(reminder.expiration, style="R")

                message = await self.ensure_valid_reminder(reminder, session=session)
                if message is None:
                    log.warning("Invalid reminder {reminder.id} while listing, deleting")
                    continue

                mention_string = "**Mentions:** " + ", ".join(target.mention for target in message.mentions)

                text = textwrap.dedent(
                    f"""
                    **Reminder #{reminder.id}:** *expires {expiry}* {mention_string}
                    {message.content}
                """
                )

                lines.append(text)

        embed = discord.Embed()
        embed.colour = discord.Colour.og_blurple()
        embed.title = f"Reminders for {ctx.author}"

        # Remind the user that they have no reminders :^)
        if not lines:
            embed.description = "No active reminders could be found."
            await ctx.send(embed=embed)
            return

        # Construct the embed and paginate it.
        embed.colour = discord.Colour.og_blurple()

        await LinePaginator.paginate(
            lines,
            ctx,
            embed,
            max_lines=3,
        )

    @remind_group.group(name="edit", aliases=("change", "modify"), invoke_without_command=True)
    async def edit_reminder_group(self, ctx: Context) -> None:
        """Commands for modifying your current reminders."""
        await ctx.send_help(ctx.command)

    @edit_reminder_group.command(name="duration", aliases=("time",))
    async def edit_reminder_duration(
        self,
        ctx: Context,
        reminder_id: int,
        expiration: t.Annotated[datetime, DurationConverter],
    ) -> None:
        """
        Edit one of your reminder's expiration.

        The `expiration` duration supports the following symbols for each unit of time:
        - years: `Y`, `y`, `year`, `years`
        - months: `m`, `month`, `months`
        - weeks: `w`, `W`, `week`, `weeks`
        - days: `d`, `D`, `day`, `days`
        - hours: `H`, `h`, `hour`, `hours`
        - minutes: `M`, `minute`, `minutes`
        - seconds: `S`, `s`, `second`, `seconds`

        For example, to edit a reminder to expire in 3 days and 1 minute, you can do `!remind edit duration 1234 3d1M`.
        """
        await self.edit_reminder(ctx, reminder_id=reminder_id, new_expiration=expiration)

    @edit_reminder_group.command(name="content", aliases=("reason",))
    async def edit_reminder_content(
        self,
        ctx: Context,
        reminder_id: int,
        *,
        content: str | None = None,
    ) -> None:
        """
        Edit one of your reminder's content.

        You can either supply the new content yourself, or reply to a message to use its content.
        """
        content = content or self.try_get_content_from_rely(ctx.message)
        if not content:
            await send_denial(ctx, "You must have content in your message or reply to a message!")
            return

        await self.edit_reminder(ctx, reminder_id=reminder_id, new_content=content)

    @edit_reminder_group.command(name="mentions", aliases=("pings",))
    async def edit_reminder_mentions(
        self,
        ctx: Context,
        reminder_id: int,
        mentions: Greedy[discord.User | discord.Member],
    ) -> None:
        """Edit one of your reminder's mentions."""
        # Remove duplicate mentions
        mention_ids = {mention.id for mention in mentions}
        mention_ids.discard(ctx.author.id)
        mention_ids = list(mention_ids)

        await self.edit_reminder(ctx, reminder_id=reminder_id, new_mention_ids=mention_ids)

    @lock_arg(LOCK_NAMESPACE, "reminder_id", raise_error=True)
    async def edit_reminder(
        self,
        ctx: Context,
        *,
        reminder_id: int,
        new_mention_ids: list[int] | None = None,
        new_content: str | None = None,
        new_expiration: datetime | None = None,
    ) -> None:
        """Edits a reminder with the given new data, then sends a confirmation message."""
        if not await self._can_modify(ctx, reminder_id=reminder_id):
            return

        async with self.bot.get_session() as session:
            query = select(Reminder).where(Reminder.id == reminder_id)

            reminder = await session.scalar(query)

            if reminder is None:
                await send_denial(ctx, f"Unable to find reminder `{reminder_id}`.")
                return

            if new_mention_ids:
                reminder.mention_ids = new_mention_ids

            if new_content:
                reminder.content = new_content

            if new_expiration:
                reminder.expiration = new_expiration
                await self._reschedule_reminder(reminder)

        # Send a confirmation message to the channel
        await self._send_confirmation(
            ctx,
            on_success="That reminder has been edited successfully!",
            reminder_id=reminder_id,
        )

    @lock_arg(LOCK_NAMESPACE, "reminder_id", raise_error=True)
    async def _delete_reminder(self, ctx: Context, reminder_id: int) -> bool:
        """Acquires a lock on `reminder_id` and returns `True` if reminder is deleted, otherwise `False`."""
        if not await self._can_modify(ctx, reminder_id=reminder_id):
            return False

        async with self.bot.get_session() as session:
            query = select(Reminder).where(Reminder.id == reminder_id)

            reminder = await session.scalar(query)

            if reminder is None:
                await send_denial(ctx, f"Unable to find reminder `{reminder_id}`.")
                return False

            await session.delete(reminder)

        self.scheduler.cancel(reminder_id)
        return True

    @remind_group.command("delete", aliases=("remove", "cancel"))
    async def delete_reminder(self, ctx: Context, reminder_ids: Greedy[int]) -> None:
        """Delete up to (and including) 5 of your active reminders."""
        if len(reminder_ids) > 5:
            await send_denial(ctx, "You can only delete a maximum of 5 reminders at once.")
            return

        deleted_ids: list[str] = []
        for reminder_id in set(reminder_ids):
            try:
                reminder_deleted = await self._delete_reminder(ctx, reminder_id)
            except LockedResourceError:
                continue
            else:
                if reminder_deleted:
                    deleted_ids.append(str(reminder_id))

        if deleted_ids:
            colour = discord.Colour.green()
            title = random.choice(POSITIVE_REPLIES)
            deletion_message = f"Successfully deleted the following reminder(s): {', '.join(deleted_ids)}"

            if len(deleted_ids) != len(reminder_ids):
                deletion_message += (
                    "\n\nThe other reminder(s) could not be deleted as they're either locked, "
                    "belong to someone else, or don't exist."
                )
        else:
            colour = discord.Colour.red()
            title = random.choice(NEGATIVE_REPLIES)
            deletion_message = (
                "Could not delete the reminder(s) as they're either locked, " "belong to someone else, or don't exist."
            )

        embed = discord.Embed(
            description=deletion_message,
            colour=colour,
            title=title,
        )
        await ctx.send(embed=embed)

    async def _can_modify(
        self,
        ctx: Context,
        *,
        reminder_id: int,
        send_on_denial: bool = True,
    ) -> bool:
        """
        Check whether the reminder can be modified by the ctx author.

        The check passes if the user created the reminder, or if they are an admin (with confirmation).
        """
        async with self.bot.get_session() as session:
            query = select(Reminder).where(Reminder.id == reminder_id)

            reminder = await session.scalar(query)

            if reminder is None:
                log.warning(f"Reminder {reminder_id} not found when checking if user can modify")
                return False

            if reminder.author_id != ctx.author.id:
                if await has_no_roles_check(ctx, Roles.administrators):
                    log.warning(f"{ctx.author} is not the reminder's author and thus does not pass the check.")
                    if send_on_denial:
                        await send_denial(ctx, "You can't modify reminders of other users!")
                    return False
                else:
                    log.debug(f"{ctx.author} is an admin, asking for confirmation to modify someone else's.")

                    modify_action = "delete" if ctx.command == self.delete_reminder else "edit"

                    confirmation_view = ModifyReminderConfirmationView(ctx.author)
                    confirmation_message = await ctx.reply(
                        f"Are you sure you want to {modify_action} <@{reminder.author_id}>'s reminder?",
                        view=confirmation_view,
                    )
                    view_timed_out = await confirmation_view.wait()
                    # We don't have access to the message in `on_timeout` so we have to delete the view here
                    if view_timed_out:
                        await confirmation_message.edit(view=None)

                    if confirmation_view.result:
                        log.debug(f"{ctx.author} has confirmed reminder modification.")
                    else:
                        await ctx.send("🚫 Operation canceled.")
                        log.debug(f"{ctx.author} has cancelled reminder modification.")
                    return confirmation_view.result or False
            else:
                log.debug(f"{ctx.author} is the reminder's author and passes the check.")
                return True


async def setup(bot: Bot) -> None:
    """Load the Reminders cog."""
    await bot.add_cog(Reminders(bot))
