"""Database models"""

import uuid
from enum import Enum

from sqlalchemy import BigInteger, FetchedValue
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.database import engine
from bot.database.mixins.timestamp import TimestampMixin


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
        UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()
    )
    """Object ID"""
    name: Mapped[str]
    error: Mapped[str]
    rule_matches: Mapped[dict | None] = mapped_column(JSONB)


class SubscriberEmails(Base):
    """Emails to be BCC'd on automated reports"""

    __tablename__: str = "emails"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    address: Mapped[str]
    discord_id: Mapped[str]


if __name__ == "__main__":
    Base.metadata.create_all(engine)
