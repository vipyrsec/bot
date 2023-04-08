from sqlalchemy import select
from bot.database import session
from bot.database.models import SubscriberEmails


def _get_registered_addresses(discord_id: str) -> list[str]:
    stmt = select(SubscriberEmails).where(SubscriberEmails.discord_id == discord_id)
    rows = session.execute(stmt)

    return [row.address for row, in rows]


def _get_all_addresses() -> list[str]:
    stmt = select(SubscriberEmails)
    rows = session.execute(stmt)

    return [row.address for row, in rows]
