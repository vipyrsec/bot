"""Database models"""

import uuid
from enum import Enum

from sqlalchemy import BigInteger, FetchedValue, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.database.mixins.timestamp import TimestampMixin

from . import engine


class Base(DeclarativeBase):
    """DeclarativeBase"""


class Guild(Base):
    """A Discord guild"""

    __tablename__: str = "guilds"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str]
    github_organization: Mapped[str]


class Permissions(Enum):
    """Permissions enum"""

    CAN_INTERNAL_EVAL = "can_internal_eval"


class RolesPermissions(Base):
    """RolesPermissions"""

    __tablename__: str = "roles_permissions"

    roles_permissions_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    role_id: Mapped[int] = mapped_column(BigInteger)
    permission: Mapped[str]


class PyPIPackageScan(Base, TimestampMixin):
    """Scan results for PyPI packages"""

    __tablename__: str = "pypi_package_scans"

    pypi_package_scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )
    """Object ID"""
    name: Mapped[str]
    error: Mapped[str]
    rule_matches: Mapped[list[str]] = mapped_column(ARRAY(String))
    flagged: Mapped[bool | None] = mapped_column(bool, default=False)


if __name__ == "__main__":
    print("Emitting DDL...")
    Base.metadata.create_all(engine)
