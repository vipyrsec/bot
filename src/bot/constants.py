"""
Loads bot configuration from environment variables
and `.env` files. By default, this simply loads the
default configuration defined thanks to the `default`
keyword argument in each instance of the `Field` class
If two files called `.env` and `.env.server` are found
in the project directory, the values will be loaded
from both of them, thus overlooking the predefined defaults.
Any settings left out in the custom user configuration
will default to the values passed to the `default` kwarg.
"""

from pydantic import BaseSettings, root_validator


class EnvConfig(BaseSettings):
    """EnvConfig"""

    class Config:
        """Config"""

        env_file = (
            ".env.server",
            ".env",
        )
        env_file_encoding = "utf-8"
        env_nested_delimiter = "__"


class _Miscellaneous(EnvConfig):
    """Miscellaneous configuration"""

    debug = True
    file_logs = False


Miscellaneous = _Miscellaneous()

FILE_LOGS = Miscellaneous.file_logs
DEBUG_MODE = Miscellaneous.debug


class _Bot(EnvConfig):
    """Bot data"""

    EnvConfig.Config.env_prefix = "bot_"

    guild_id = "1033456860864466995"
    prefix = "!"
    sentry_dsn = ""
    token = ""
    trace_loggers = "*"


Bot = _Bot()


class _Channels(EnvConfig):
    EnvConfig.Config.env_prefix = "channels_"
    """Channel constants"""

    dev_alerts = 1087922776024830075
    mod_alerts = 1087908228978966669
    soc_alerts = 1087922465021370388

    dev_log = 1012202489342345246
    mod_log = 1087901347040465006
    soc_log = 1087901419132170260


Channels = _Channels()


class _Roles(EnvConfig):
    EnvConfig.Config.env_prefix = "roles_"
    """Channel constants"""

    moderators = 1087224451571142716


Roles = _Roles()


class _Tokens(EnvConfig):
    """Authentication tokens for external services"""

    EnvConfig.Config.env_prefix = "tokens_"

    github = ""


Tokens = _Tokens()


class _Emojis(EnvConfig):
    """Named emoji constants"""

    EnvConfig.Config.env_prefix = "emojis_"

    cross_mark = "\u274C"
    star = "\u2B50"
    christmas_tree = "\U0001F384"
    check = "\u2611"
    envelope = "\U0001F4E8"
    trashcan = "<:trashcan:637136429717389331>"
    ok_hand = ":ok_hand:"
    hand_raised = "\U0001F64B"

    dice_1 = "<:dice_1:755891608859443290>"
    dice_2 = "<:dice_2:755891608741740635>"
    dice_3 = "<:dice_3:755891608251138158>"
    dice_4 = "<:dice_4:755891607882039327>"
    dice_5 = "<:dice_5:755891608091885627>"
    dice_6 = "<:dice_6:755891607680843838>"

    # These icons are from GitHub's repo https://github.com/primer/octicons/
    issue_open = "<:IssueOpen:852596024777506817>"
    issue_closed = "<:IssueClosed:927326162861039626>"
    issue_draft = "<:IssueDraft:852596025147523102>"  # Not currently used by GitHub, but here for future.
    pull_request_open = "<:PROpen:852596471505223781>"
    pull_request_closed = "<:PRClosed:852596024732286976>"
    pull_request_draft = "<:PRDraft:852596025045680218>"
    pull_request_merged = "<:PRMerged:852596100301193227>"

    number_emojis = {
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

    confirmation = "\u2705"
    decline = "\u274c"
    incident_unactioned = "<:incident_unactioned:719645583245180960>"

    x = "\U0001f1fd"
    o = "\U0001f1f4"

    x_square = "<:x_square:632278427260682281>"
    o_square = "<:o_square:632278452413661214>"

    status_online = "<:status_online:470326272351010816>"
    status_idle = "<:status_idle:470326266625785866>"
    status_dnd = "<:status_dnd:470326272082313216>"
    status_offline = "<:status_offline:470326266537705472>"

    stackoverflow_tag = "<:stack_tag:870926975307501570>"
    stackoverflow_views = "<:stack_eye:870926992692879371>"

    # Reddit emojis
    reddit = "<:reddit:676030265734332427>"
    reddit_post_text = "<:reddit_post_text:676030265910493204>"
    reddit_post_video = "<:reddit_post_video:676030265839190047>"
    reddit_post_photo = "<:reddit_post_photo:676030265734201344>"
    reddit_upvote = "<:reddit_upvote:755845219890757644>"
    reddit_comments = "<:reddit_comments:755845255001014384>"
    reddit_users = "<:reddit_users:755845303822974997>"

    lemon_hyperpleased = "<:lemon_hyperpleased:754441879822663811>"
    lemon_pensive = "<:lemon_pensive:754441880246419486>"


Emojis = _Emojis()


class _Icons(EnvConfig):
    EnvConfig.Config.env_prefix = "icons_"

    crown_blurple = "https://cdn.discordapp.com/emojis/469964153289965568.png"
    crown_green = "https://cdn.discordapp.com/emojis/469964154719961088.png"
    crown_red = "https://cdn.discordapp.com/emojis/469964154879344640.png"

    defcon_denied = "https://cdn.discordapp.com/emojis/472475292078964738.png"  # noqa: E704
    defcon_shutdown = "https://cdn.discordapp.com/emojis/470326273952972810.png"  # noqa: E704
    defcon_unshutdown = "https://cdn.discordapp.com/emojis/470326274213150730.png"  # noqa: E704
    defcon_update = "https://cdn.discordapp.com/emojis/472472638342561793.png"  # noqa: E704

    filtering = "https://cdn.discordapp.com/emojis/472472638594482195.png"

    green_checkmark = (
        "https://raw.githubusercontent.com/python-discord/branding/main/icons/checkmark/green-checkmark-dist.png"
    )
    green_questionmark = (
        "https://raw.githubusercontent.com/python-discord/branding/main/icons/checkmark/green-question-mark-dist.png"
    )
    guild_update = "https://cdn.discordapp.com/emojis/469954765141442561.png"

    hash_blurple = "https://cdn.discordapp.com/emojis/469950142942806017.png"
    hash_green = "https://cdn.discordapp.com/emojis/469950144918585344.png"
    hash_red = "https://cdn.discordapp.com/emojis/469950145413251072.png"

    message_bulk_delete = "https://cdn.discordapp.com/emojis/469952898994929668.png"
    message_delete = "https://cdn.discordapp.com/emojis/472472641320648704.png"
    message_edit = "https://cdn.discordapp.com/emojis/472472638976163870.png"

    pencil = "https://cdn.discordapp.com/emojis/470326272401211415.png"

    questionmark = "https://cdn.discordapp.com/emojis/512367613339369475.png"

    remind_blurple = "https://cdn.discordapp.com/emojis/477907609215827968.png"
    remind_green = "https://cdn.discordapp.com/emojis/477907607785570310.png"
    remind_red = "https://cdn.discordapp.com/emojis/477907608057937930.png"

    sign_in = "https://cdn.discordapp.com/emojis/469952898181234698.png"
    sign_out = "https://cdn.discordapp.com/emojis/469952898089091082.png"

    superstarify = "https://cdn.discordapp.com/emojis/636288153044516874.png"
    unsuperstarify = "https://cdn.discordapp.com/emojis/636288201258172446.png"

    token_removed = "https://cdn.discordapp.com/emojis/470326273298792469.png"

    user_ban = "https://cdn.discordapp.com/emojis/469952898026045441.png"
    user_timeout = "https://cdn.discordapp.com/emojis/472472640100106250.png"
    user_unban = "https://cdn.discordapp.com/emojis/469952898692808704.png"
    user_untimeout = "https://cdn.discordapp.com/emojis/472472639206719508.png"
    user_update = "https://cdn.discordapp.com/emojis/469952898684551168.png"
    user_verified = "https://cdn.discordapp.com/emojis/470326274519334936.png"
    user_warn = "https://cdn.discordapp.com/emojis/470326274238447633.png"

    voice_state_blue = "https://cdn.discordapp.com/emojis/656899769662439456.png"
    voice_state_green = "https://cdn.discordapp.com/emojis/656899770094452754.png"
    voice_state_red = "https://cdn.discordapp.com/emojis/656899769905709076.png"


Icons = _Icons()


class _Colours(EnvConfig):
    """Named color constants"""

    EnvConfig.Config.env_prefix = "colours_"

    blue = 0x0279FD
    twitter_blue = 0x1DA1F2
    bright_green = 0x01D277
    dark_green = 0x1F8B4C
    orange = 0xE67E22
    pink = 0xCF84E0
    purple = 0xB734EB
    soft_green = 0x68C290
    soft_orange = 0xF9CB54
    soft_red = 0xCD6D6D
    yellow = 0xF9F586
    python_blue = 0x4B8BBE
    python_yellow = 0xFFD43B
    grass_green = 0x66FF00
    gold = 0xE6C200

    @root_validator(pre=True)
    # pylint: disable-next=no-self-argument
    def parse_hex_values(cls, values):
        """Verify that colors are valid hex"""
        for key, value in values.items():
            values[key] = int(value, 16)
        return values


Colours = _Colours()

# Bot replies
NEGATIVE_REPLIES = {
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
}

POSITIVE_REPLIES = {
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
}

ERROR_REPLIES = {
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
}
