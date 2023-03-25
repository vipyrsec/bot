"""Database models"""

from enum import Enum

from sqlalchemy import BigInteger
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.database import engine


class Base(DeclarativeBase):
    """DeclarativeBase"""


class Guild(Base):
    """A Discord guild"""

    __tablename__ = "guilds"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str]
    github_organization: Mapped[str]


class Permissions(Enum):
    """Permissions enum"""

    CAN_INTERNAL_EVAL = "can_internal_eval"


class RolesPermissions(Base):
    """RolesPermissions"""

    __tablename__ = "roles_permissions"

    roles_permissions_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    role_id: Mapped[int] = mapped_column(BigInteger)
    permission: Mapped[str]


if __name__ == "__main__":
    Base.metadata.create_all(engine)
