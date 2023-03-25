"""Database functions"""

from os import getenv

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

engine = create_engine(
    # `create_engine` errors if no URL is supplied, causing tests to fail.
    getenv("BOT_DB_URL", "sqlite:///:memory:"),
    future=True,
)

session: scoped_session = scoped_session(
    sessionmaker(
        bind=engine,
        future=True,
    )
)
