"""Internal commands for bot administration and core development."""

import contextlib
import inspect
import pprint
import re
import textwrap
import traceback
from collections import Counter
from io import StringIO
from typing import Any, Self

import arrow
import discord
from discord.ext.commands import Cog, Context, group, has_any_role, is_owner

from bot.bot import Bot
from bot.constants import DEBUG_MODE, Roles
from bot.log import get_logger
from bot.utils import (
    PasteTooLongError,
    PasteUploadError,
    find_nth_occurrence,
    send_to_paste_service,
)

log = get_logger(__name__)


class Internal(Cog):
    """Administrator and Core Developer commands."""

    def __init__(self: Self, bot: Bot) -> None:
        self.bot = bot
        self.env = {}
        self.ln = 0
        self.stdout = StringIO()

        self.socket_since = arrow.utcnow()
        self.socket_event_total = 0
        self.socket_events = Counter()

        if DEBUG_MODE:
            self.eval.add_check(is_owner().predicate)

    @Cog.listener()
    async def on_socket_event_type(self: Self, event_type: str) -> None:
        """When a websocket event is received, increase our counters."""
        self.socket_event_total += 1
        self.socket_events[event_type] += 1

    def _format(self: Self, inp: str, out: Any) -> tuple[str, discord.Embed | None]:  # noqa: ANN401,C901,PLR0912
        """Format the eval output into a string & attempt to format it into an Embed."""
        self._ = out

        res = ""

        # Erase temp input we made
        if inp.startswith("_ = "):
            inp = inp[4:]

        # Get all non-empty lines
        lines = [line for line in inp.split("\n") if line.strip()]
        if len(lines) != 1:
            lines += [""]

        # Create the input dialog
        for i, line in enumerate(lines):
            if i == 0:  # noqa: SIM108 -- ternary would strip the comment
                # Start dialog
                start = f"In [{self.ln}]: "

            else:
                # Indent the 3 dots correctly;
                # Normally, it's something like
                # In [X]:
                #    ...:
                #
                # But if it's
                # In [XX]:
                #    ...:
                #
                # You can see it doesn't look right.
                # This code simply indents the dots
                # far enough to align them.
                # we first `str()` the line number
                # then we get the length
                # and use `str.rjust()`
                # to indent it.
                start = "...: ".rjust(len(str(self.ln)) + 7)

            if i == len(lines) - 2 and line.startswith("return"):
                line = line[6:].strip()  # noqa: PLW2901

            # Combine everything
            res += start + line + "\n"

        self.stdout.seek(0)
        text = self.stdout.read()
        self.stdout.close()
        self.stdout = StringIO()

        if text:
            res += text + "\n"

        if out is None:
            # No output, return the input statement
            return (res, None)

        res += f"Out[{self.ln}]: "

        if isinstance(out, discord.Embed):
            # We made an embed? Send that as embed
            res += "<Embed>"
            res = (res, out)

        else:
            if isinstance(out, str) and out.startswith("Traceback (most recent call last):\n"):
                # Leave out the traceback message
                out = "\n" + "\n".join(out.split("\n")[1:])

            pretty = out if isinstance(out, str) else pprint.pformat(out, compact=True, width=60)

            if pretty != str(out):
                # We're using the pretty version, start on the next line
                res += "\n"

            if pretty.count("\n") > 20:  # noqa: PLR2004
                # Text too long, shorten
                li = pretty.split("\n")

                pretty = (
                    "\n".join(li[:3])  # First 3 lines
                    + "\n ...\n"  # Ellipsis to indicate removed lines
                    + "\n".join(li[-3:])
                )  # last 3 lines

            # Add the output
            res += pretty
            res = (res, None)

        return res  # Return (text, embed)

    async def _eval(self: Self, ctx: Context, code: str) -> discord.Message | None:
        """Eval the input code string & send an embed to the invoking context."""
        self.ln += 1

        if code.startswith("exit"):
            self.ln = 0
            self.env = {}
            return await ctx.send("```Reset history!```")

        env = {
            "message": ctx.message,
            "author": ctx.message.author,
            "channel": ctx.channel,
            "guild": ctx.guild,
            "ctx": ctx,
            "self": self,
            "bot": self.bot,
            "inspect": inspect,
            "discord": discord,
            "contextlib": contextlib,
        }

        self.env.update(env)

        # Ignore this code, it works
        code_ = """
async def func():  # (None,) -> Any
    try:
        with contextlib.redirect_stdout(self.stdout):
{}
        if '_' in locals():
            if inspect.isawaitable(_):
                _ = await _
            return _
    finally:
        self.env.update(locals())
""".format(
            textwrap.indent(code, "            "),
        )

        try:
            exec(code_, self.env)  # noqa: S102
            func = self.env["func"]
            res = await func()

        except Exception:  # noqa: BLE001
            res = traceback.format_exc()

        out, embed = self._format(code, res)
        out = out.rstrip("\n")  # Strip empty lines from output

        # Truncate output to max 15 lines or 1500 characters
        newline_truncate_index = find_nth_occurrence(out, "\n", 15)

        if newline_truncate_index is None or newline_truncate_index > 1500:  # noqa: PLR2004
            truncate_index = 1500
        else:
            truncate_index = newline_truncate_index

        if len(out) > truncate_index:
            try:
                paste_link = await send_to_paste_service(self.bot.http_session, out, extension="py")
            except PasteTooLongError:
                paste_text = "too long to upload to paste service."
            except PasteUploadError:
                paste_text = "failed to upload contents to paste service."
            else:
                paste_text = f"full contents at {paste_link}"

            await ctx.send(f"```py\n{out[:truncate_index]}\n```... response truncated; {paste_text}", embed=embed)
            return None

        await ctx.send(f"```py\n{out}```", embed=embed)
        return None

    @group(name="internal", aliases=("int",))
    @has_any_role(Roles.administrators, Roles.core_developers)
    async def internal_group(self: Self, ctx: Context) -> None:
        """Internal commands. Top secret!."""  # noqa: D401
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @internal_group.command(name="eval", aliases=("e",))
    @has_any_role(Roles.administrators)
    async def eval(self: Self, ctx: Context, *, code: str) -> None:  # noqa: A003
        """Run eval in a REPL-like format."""
        code = code.strip("`")
        if re.match("py(thon)?\n", code):
            code = "\n".join(code.split("\n")[1:])

        if (
            not re.search(  # Check if it's an expression
                r"^(return|import|for|while|def|class|from|exit|[a-zA-Z0-9]+\s*=)",
                code,
                re.M,
            )
            and len(code.split("\n")) == 1
        ):
            code = "_ = " + code

        await self._eval(ctx, code)

    @internal_group.command(name="socketstats", aliases=("socket", "stats"))
    @has_any_role(Roles.administrators, Roles.core_developers)
    async def socketstats(self: Self, ctx: Context) -> None:
        """Fetch information on the socket events received from Discord."""
        running_s = (arrow.utcnow() - self.socket_since).total_seconds()

        per_s = self.socket_event_total / running_s

        stats_embed = discord.Embed(
            title="WebSocket statistics",
            description=f"Receiving {per_s:0.2f} events per second.",
            color=discord.Color.og_blurple(),
        )

        for event_type, count in self.socket_events.most_common(25):
            stats_embed.add_field(name=event_type, value=f"{count:,}", inline=True)

        await ctx.send(embed=stats_embed)


async def setup(bot: Bot) -> None:
    """Load the Internal cog."""
    await bot.add_cog(Internal(bot))
