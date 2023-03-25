"""Internal eval"""

from bot.bot import Bot


async def setup(bot: Bot) -> None:
    """Set up the Internal Eval extension."""
    # Import the Cog at runtime to prevent side effects like defining
    # RedisCache instances too early.
    # pylint: disable-next=import-outside-toplevel
    from ._internal_eval import InternalEval

    await bot.add_cog(InternalEval(bot))
