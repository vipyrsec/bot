"""Database models."""

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column


class Base(MappedAsDataclass, DeclarativeBase):
    """SQLAlchemy declarative base class."""


class Reminder(Base):
    """Represents a Reminder in the database."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(  # noqa: A003 # shadowing id() function is fine
        init=False,
        primary_key=True,
        autoincrement=True,
        unique=True,
    )

    channel_id: Mapped[int] = mapped_column(BigInteger)

    message_id: Mapped[int] = mapped_column(BigInteger)

    author_id: Mapped[int] = mapped_column(BigInteger)

    mention_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))

    content: Mapped[str]

    expiration: Mapped[datetime] = mapped_column(DateTime(timezone=True))
