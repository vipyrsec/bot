from datetime import UTC, datetime, timedelta

from discord.ext.commands import BadArgument, Context, Converter

from bot.utils.time import parse_duration_string


class DeltaConverter(Converter):
    """Convert duration strings into dateutil.relativedelta.relativedelta objects."""

    async def convert(self, ctx: Context, duration: str) -> timedelta:
        """
        Converts a `duration` string to a timedelta object.

        The converter supports the following symbols for each unit of time:
        - years: `Y`, `y`, `year`, `years`
        - months: `m`, `month`, `months`
        - weeks: `w`, `W`, `week`, `weeks`
        - days: `d`, `D`, `day`, `days`
        - hours: `H`, `h`, `hour`, `hours`
        - minutes: `M`, `minute`, `minutes`
        - seconds: `S`, `s`, `second`, `seconds`

        The units need to be provided in descending order of magnitude.
        """
        if not (delta := parse_duration_string(duration)):
            msg = f"`{duration}` is not a valid duration string."
            raise BadArgument(msg)

        return delta


class DurationConverter(DeltaConverter):
    """Convert duration strings into UTC datetime.datetime objects."""

    async def convert(self, ctx: Context, duration: str) -> datetime:
        """
        Converts a `duration` string to a datetime object that's `duration` in the future.

        The converter supports the same symbols for each unit of time as its parent class.
        """
        delta = await super().convert(ctx, duration)
        now = datetime.now(UTC)

        try:
            return now + delta
        except (ValueError, OverflowError):
            msg = f"`{duration}` results in a datetime outside the supported range."
            raise BadArgument(msg)
