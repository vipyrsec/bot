"""
Loads bot configuration from environment variables and `.env` files.

By default, the values defined in the classes are used, these can be overridden by an env var with the same name.

An `.env` file is used to populate env vars, if present.
"""

from os import getenv
from typing import ClassVar

from pydantic import root_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    """Our default configuration for models that should load from .env files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


class _Miscellaneous(EnvConfig):
    """Miscellaneous configuration."""

    debug: bool = True
    file_logs: bool = False


Miscellaneous = _Miscellaneous()

FILE_LOGS = Miscellaneous.file_logs
DEBUG_MODE = Miscellaneous.debug


class _Dragonfly(EnvConfig, env_prefix="auth0_"):
    """Configuration for the Dragonfly API."""

    base_url: str = "https://dragonfly.vipyrsec.com"
    auth_url: str = "https://vipyrsec.us.auth0.com/oauth/token"
    audience: str = "https://dragonfly.vipyrsec.com"
    client_id: str = ""
    client_secret: str = ""
    username: str = ""
    password: str = ""


Dragonfly = _Dragonfly()


class _DragonflyConfig(EnvConfig, env_prefix="dragonfly_"):
    """Dragonfly Cog Configuration."""

    alerts_channel_id: int = 1121462652342910986
    logs_channel_id: int = 1121462677131251752
    alerts_role_id: int = 1122647527485878392
    api_url: str = "https://dragonfly.vipyrsec.com"
    interval: int = 60
    threshold: int = 8
    timeout: int = 25


DragonflyConfig = _DragonflyConfig()


class _PyPi(EnvConfig, env_prefix="pypi_"):
    """PyPI Cog Configuration."""

    show_author_in_embed: bool = False


PyPiConfigs = _PyPi()


class _Bot(EnvConfig, env_prefix="bot_"):
    """Bot data."""

    token: str = ""
    trace_loggers: str = "*"
    prefix: str = "$"


Bot = _Bot()


class _Sentry(BaseSettings, env_prefix="sentry_"):
    """Sentry configuration."""

    dsn: str = ""
    environment: str = ""
    release_prefix: str = ""


Sentry = _Sentry()


class _Channels(EnvConfig, env_prefix="channels_"):
    """Channel constants."""

    mod_alerts: int = 1121492582686539788
    mod_log: int = 1121492613070082118
    reporting: int = 1126657120897617961


Channels = _Channels()


class _Roles(EnvConfig, env_prefix="roles_"):
    """Channel constants."""

    administrators: int = 1121450967360098486

    moderators: int = 1121472560140390440

    vipyr_security: int = 1121472420755275776

    core_developers: int = 1121472691740880998


Roles = _Roles()


class _Guild(EnvConfig, env_prefix="guild_"):
    id: int = 1121450543462760448

    moderation_roles: ClassVar[list[int]] = [Roles.moderators]


Guild = _Guild()


class _BaseURLs(EnvConfig, env_prefix="urls_"):
    paste: str = "https://paste.pythondiscord.com"


BaseURLs = _BaseURLs()


class _URLs(_BaseURLs):
    # Base site vars
    connect_max_retries: int = 3
    connect_cooldown: int = 5

    paste_service: str = f"{BaseURLs.paste}/{{key}}"


URLs = _URLs()


class _Colours(EnvConfig, env_prefix="colours_"):
    """Named color constants."""

    blue: int = 0x0279FD
    twitter_blue: int = 0x1DA1F2
    bright_green: int = 0x01D277
    dark_green: int = 0x1F8B4C
    orange: int = 0xE67E22
    pink: int = 0xCF84E0
    purple: int = 0xB734EB
    soft_green: int = 0x68C290
    soft_orange: int = 0xF9CB54
    soft_red: int = 0xCD6D6D
    yellow: int = 0xF9F586
    python_blue: int = 0x4B8BBE
    python_yellow: int = 0xFFD43B
    grass_green: int = 0x66FF00
    gold: int = 0xE6C200

    @root_validator(pre=True)
    def parse_hex_values(cls, values: dict[str, int]) -> dict[str, int]:  # noqa: N805 - check this
        """Verify that colors are valid hex."""
        for key, value in values.items():
            values[key] = int(value, 16)  # type: ignore[call-overload]
        return values


Colours = _Colours()

# Git SHA for Sentry
GIT_SHA = getenv("GIT_SHA", "development")

# Default role combinations
MODERATION_ROLES = Guild.moderation_roles

TXT_LIKE_FILES = {".txt", ".csv", ".json"}

NEGATIVE_REPLIES = [
    "Noooooo!!",
    "Nope.",
    "I'm sorry Dave, I'm afraid I can't do that.",
    "I don't think so.",
    "Not gonna happen.",
    "Out of the question.",
    "Huh? No.",
    "Nah.",
    "Naw.",
    "Not likely.",
    "No way, José.",
    "Not in a million years.",
    "Fat chance.",
    "Certainly not.",
    "NEGATORY.",
    "Nuh-uh.",
    "Not in my house!",
]

POSITIVE_REPLIES = [
    "Yep.",
    "Absolutely!",
    "Can do!",
    "Affirmative!",
    "Yeah okay.",
    "Sure.",
    "Sure thing!",
    "You're the boss!",
    "Okay.",
    "No problem.",
    "I got you.",
    "Alright.",
    "You got it!",
    "ROGER THAT",
    "Of course!",
    "Aye aye, cap'n!",
    "I'll allow it.",
]

ERROR_REPLIES = [
    "Please don't do that.",
    "You have to stop.",
    "Do you mind?",
    "In the future, don't do that.",
    "That was a mistake.",
    "You blew it.",
    "You're bad at computers.",
    "Are you trying to kill me?",
    "Noooooo!!",
    "I can't believe you've done this",
]
