"""Interacting with the Dragonfly API."""

from datetime import datetime
from typing import Self

from dragonfly_db_commons.models import Scan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload


class DragonflyServices:
    """A class wrapping the Dragonfly database."""

    def __init__(
        self: Self,
        engine: AsyncEngine,
    ) -> None:
        """Initialize the DragonflyServices class."""
        self.engine = engine

    async def get_package(self: Self, *, name: str, version: str) -> Scan | None:
        """Find a package with the given name and version."""
        query = select(Scan).where(Scan.name == name).where(Scan.version == version).options(selectinload(Scan.rules))

        async with AsyncSession(self.engine) as session:
            return await session.scalar(query)

    async def get_scanned_packages_since(
        self: Self,
        since: datetime,
    ) -> list[Scan]:
        """Get a list of packages that were scanned after the given datetime."""
        query = select(Scan).where(Scan.finished_at >= since).options(selectinload(Scan.rules))

        async with AsyncSession(self.engine) as session:
            scalars = await session.scalars(query)

        return list(scalars)
