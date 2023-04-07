"""mixin: Timestamp"""

from datetime import datetime

from sqlalchemy import DateTime, FetchedValue
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Timestamp
    Adds created and updated timestamps to a model.
    """

    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=FetchedValue())
    """The date and time the object was created"""

    updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
    )
    """The date and time the object was last updated"""

    deleted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """The date and time the object was deleted (NULL if not deleted)"""
