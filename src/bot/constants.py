"""
Loads bot configuration from environment variables and `.env` files.

By default, the values defined in the classes are used, these can be overridden by an env var with the same name.

`.env` and `.env.server` files are used to populate env vars, if present.
"""

from os import getenv
from typing import Self

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


class _DragonflyAuthentication(EnvConfig, env_prefix="auth0_"):
    """Settings related to authenticating with Dragonfly API"""

    client_id: str = ""
    client_secret: str = ""
    username: str = ""
    password: str = ""
    domain: str = "vipyrsec.us.auth0.com"
    audience: str = "https://dragonfly.vipyrsec.com"


DragonflyAuthentication = _DragonflyAuthentication()


class _DragonflyConfig(EnvConfig, env_prefix="dragonfly_"):
    """Dragonfly Cog Configuration"""

    alerts_channel_id: int = 1121462652342910986
    logs_channel_id: int = 1121462677131251752
    alerts_role_id: int = 1122647527485878392
    api_url: str = "https://dragonfly.vipyrsec.com"
    interval: int = 60
    threshold: int = 5
    timeout: int = 25


DragonflyConfig = _DragonflyConfig()


class _PyPi(EnvConfig, env_prefix="pypi_"):
    """PyPI Cog Configuration"""

    show_author_in_embed: bool = False


PyPiConfigs = _PyPi()


class _Bot(EnvConfig, env_prefix="bot_"):
    """Bot data"""

    token: str = ""
    trace_loggers: str = "*"


Bot = _Bot()


class _Sentry(BaseSettings, env_prefix="sentry_"):
    """Sentry configuration."""

    dsn: str = ""
    environment: str = ""
    release_prefix: str = ""


Sentry = _Sentry()


class _Channels(EnvConfig, env_prefix="channels_"):
    """Channel constants"""

    mod_alerts: int = 1121492582686539788
    mod_log: int = 1121492613070082118
    reporting: int = 1126657120897617961


Channels = _Channels()


class _Roles(EnvConfig, env_prefix="roles_"):
    """Channel constants"""

    administrators: int = 1121450967360098486

    moderators: int = 1121472560140390440

    vipyr_security: int = 1121472420755275776

    core_developers: int = 1121472691740880998


Roles = _Roles()


class _Guild(EnvConfig, env_prefix="guild_"):
    id: int = 1121450543462760448

    moderation_roles: list[int] = [Roles.moderators]


Guild = _Guild()


class _BaseURLs(EnvConfig, env_prefix="urls_"):
    # Snekbox endpoints
    snekbox_eval_api: str = "http://localhost:8060/eval"

    # Discord API
    discord_api: str = "https://discordapp.com/api/v7/"

    # Misc endpoints
    bot_avatar: str = "https://raw.githubusercontent.com/python-discord/branding/main/logos/logo_circle/logo_circle.png"

    github_bot_repo: str = "https://github.com/vipyrsec/bot"

    paste: str = "https://paste.pythondiscord.com"


BaseURLs = _BaseURLs()


class _URLs(_BaseURLs):
    # Discord API endpoints
    discord_invite_api: str = "".join([BaseURLs.discord_api, "invites"])

    # Base site vars
    connect_max_retries: int = 3
    connect_cooldown: int = 5

    paste_service: str = "".join([BaseURLs.paste, "/{key}"])
    site_logs_view: str = "https://pythondiscord.com/staff/bot/logs"


URLs = _URLs()


class _Tokens(EnvConfig, env_prefix="tokens_"):
    """Authentication tokens for external services"""

    github: str = ""


Tokens = _Tokens()


class _Emojis(EnvConfig, env_prefix="emojis_"):
    """Named emoji constants."""

    cross_mark: str = "\u274C"
    star: str = "\u2B50"
    christmas_tree: str = "\U0001F384"
    check: str = "\u2611"
    envelope: str = "\U0001F4E8"
    trashcan: str = "<:trashcan:637136429717389331>"
    ok_hand: str = ":ok_hand:"
    hand_raised: str = "\U0001F64B"

    dice_1: str = "<:dice_1:755891608859443290>"
    dice_2: str = "<:dice_2:755891608741740635>"
    dice_3: str = "<:dice_3:755891608251138158>"
    dice_4: str = "<:dice_4:755891607882039327>"
    dice_5: str = "<:dice_5:755891608091885627>"
    dice_6: str = "<:dice_6:755891607680843838>"

    # These icons are from GitHub's repo https://github.com/primer/octicons/
    issue_open: str = "<:IssueOpen:852596024777506817>"
    issue_closed: str = "<:IssueClosed:927326162861039626>"
    # Not currently used by GitHub, but here for future.
    issue_draft: str = "<:IssueDraft:852596025147523102>"
    pull_request_open: str = "<:PROpen:852596471505223781>"
    pull_request_closed: str = "<:PRClosed:852596024732286976>"
    pull_request_draft: str = "<:PRDraft:852596025045680218>"
    pull_request_merged: str = "<:PRMerged:852596100301193227>"

    number_emojis: dict[int, str] = {  # noqa: RUF012 - uh...
        1: "\u0031\ufe0f\u20e3",
        2: "\u0032\ufe0f\u20e3",
        3: "\u0033\ufe0f\u20e3",
        4: "\u0034\ufe0f\u20e3",
        5: "\u0035\ufe0f\u20e3",
        6: "\u0036\ufe0f\u20e3",
        7: "\u0037\ufe0f\u20e3",
        8: "\u0038\ufe0f\u20e3",
        9: "\u0039\ufe0f\u20e3",
    }

    confirmation: str = "\u2705"
    decline: str = "\u274c"
    incident_unactioned: str = "<:incident_unactioned:719645583245180960>"

    x: str = "\U0001f1fd"
    o: str = "\U0001f1f4"

    x_square: str = "<:x_square:632278427260682281>"
    o_square: str = "<:o_square:632278452413661214>"

    status_online: str = "<:status_online:470326272351010816>"
    status_idle: str = "<:status_idle:470326266625785866>"
    status_dnd: str = "<:status_dnd:470326272082313216>"
    status_offline: str = "<:status_offline:470326266537705472>"

    stackoverflow_tag: str = "<:stack_tag:870926975307501570>"
    stackoverflow_views: str = "<:stack_eye:870926992692879371>"

    # Reddit emojis
    reddit: str = "<:reddit:676030265734332427>"
    reddit_post_text: str = "<:reddit_post_text:676030265910493204>"
    reddit_post_video: str = "<:reddit_post_video:676030265839190047>"
    reddit_post_photo: str = "<:reddit_post_photo:676030265734201344>"
    reddit_upvote: str = "<:reddit_upvote:755845219890757644>"
    reddit_comments: str = "<:reddit_comments:755845255001014384>"
    reddit_users: str = "<:reddit_users:755845303822974997>"

    lemon_hyperpleased: str = "<:lemon_hyperpleased:754441879822663811>"
    lemon_pensive: str = "<:lemon_pensive:754441880246419486>"

    failed_file: str = "<:failed_file:1073298441968562226>"


Emojis = _Emojis()


class _Icons(EnvConfig, env_prefix="icons_"):
    crown_blurple: str = "https://cdn.discordapp.com/emojis/469964153289965568.png"
    crown_green: str = "https://cdn.discordapp.com/emojis/469964154719961088.png"
    crown_red: str = "https://cdn.discordapp.com/emojis/469964154879344640.png"

    defcon_denied: str = "https://cdn.discordapp.com/emojis/472475292078964738.png"
    defcon_shutdown: str = "https://cdn.discordapp.com/emojis/470326273952972810.png"
    defcon_unshutdown: str = "https://cdn.discordapp.com/emojis/470326274213150730.png"
    defcon_update: str = "https://cdn.discordapp.com/emojis/472472638342561793.png"

    filtering: str = "https://cdn.discordapp.com/emojis/472472638594482195.png"

    green_checkmark: str = (
        "https://raw.githubusercontent.com/python-discord/branding/main/icons/checkmark/green-checkmark-dist.png"
    )
    green_questionmark: str = (
        "https://raw.githubusercontent.com/python-discord/branding/main/icons/checkmark/green-question-mark-dist.png"
    )
    guild_update: str = "https://cdn.discordapp.com/emojis/469954765141442561.png"

    hash_blurple: str = "https://cdn.discordapp.com/emojis/469950142942806017.png"
    hash_green: str = "https://cdn.discordapp.com/emojis/469950144918585344.png"
    hash_red: str = "https://cdn.discordapp.com/emojis/469950145413251072.png"

    message_bulk_delete: str = "https://cdn.discordapp.com/emojis/469952898994929668.png"
    message_delete: str = "https://cdn.discordapp.com/emojis/472472641320648704.png"
    message_edit: str = "https://cdn.discordapp.com/emojis/472472638976163870.png"

    pencil: str = "https://cdn.discordapp.com/emojis/470326272401211415.png"

    questionmark: str = "https://cdn.discordapp.com/emojis/512367613339369475.png"

    remind_blurple: str = "https://cdn.discordapp.com/emojis/477907609215827968.png"
    remind_green: str = "https://cdn.discordapp.com/emojis/477907607785570310.png"
    remind_red: str = "https://cdn.discordapp.com/emojis/477907608057937930.png"

    sign_in: str = "https://cdn.discordapp.com/emojis/469952898181234698.png"
    sign_out: str = "https://cdn.discordapp.com/emojis/469952898089091082.png"

    superstarify: str = "https://cdn.discordapp.com/emojis/636288153044516874.png"
    unsuperstarify: str = "https://cdn.discordapp.com/emojis/636288201258172446.png"

    token_removed: str = "https://cdn.discordapp.com/emojis/470326273298792469.png"  # - false positive

    user_ban: str = "https://cdn.discordapp.com/emojis/469952898026045441.png"
    user_timeout: str = "https://cdn.discordapp.com/emojis/472472640100106250.png"
    user_unban: str = "https://cdn.discordapp.com/emojis/469952898692808704.png"
    user_untimeout: str = "https://cdn.discordapp.com/emojis/472472639206719508.png"
    user_update: str = "https://cdn.discordapp.com/emojis/469952898684551168.png"
    user_verified: str = "https://cdn.discordapp.com/emojis/470326274519334936.png"
    user_warn: str = "https://cdn.discordapp.com/emojis/470326274238447633.png"

    voice_state_blue: str = "https://cdn.discordapp.com/emojis/656899769662439456.png"
    voice_state_green: str = "https://cdn.discordapp.com/emojis/656899770094452754.png"
    voice_state_red: str = "https://cdn.discordapp.com/emojis/656899769905709076.png"


Icons = _Icons()


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
    def parse_hex_values(cls: type[Self], values: dict[str, int]) -> dict[str, int]:  # noqa: N805 - check this
        """Verify that colors are valid hex."""
        for key, value in values.items():
            values[key] = int(value, 16)
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
