import re
from datetime import timedelta

DURATION_REGEX = re.compile(
    r"((?P<years>\d+?) ?(years|year|Y|y) ?)?"
    r"((?P<months>\d+?) ?(months|month|M) ?)?"
    r"((?P<weeks>\d+?) ?(weeks|week|W|w) ?)?"
    r"((?P<days>\d+?) ?(days|day|D|d) ?)?"
    r"((?P<hours>\d+?) ?(hours|hour|H|h) ?)?"
    r"((?P<minutes>\d+?) ?(minutes|minute|m) ?)?"
    r"((?P<seconds>\d+?) ?(seconds|second|S|s))?",
)


def parse_duration_string(duration: str) -> timedelta | None:
    """
    Convert a `duration` string to a relativedelta object.

    The following symbols are supported for each unit of time:

    - years: `Y`, `y`, `year`, `years`
    - months: `M`, `month`, `months`
    - weeks: `w`, `W`, `week`, `weeks`
    - days: `d`, `D`, `day`, `days`
    - hours: `H`, `h`, `hour`, `hours`
    - minutes: `m`, `minute`, `minutes`
    - seconds: `S`, `s`, `second`, `seconds`

    The units need to be provided in descending order of magnitude.
    Return None if the `duration` string cannot be parsed according to the symbols above.
    """
    match = DURATION_REGEX.fullmatch(duration)
    if not match:
        return None

    duration_dict = {unit: int(amount) for unit, amount in match.groupdict(default="0").items()}

    # since timedelta doesn't support months, let's just say 1 month = 30 days
    months = duration_dict.pop("months")
    duration_dict["days"] += int(months) * 30

    # since timedelta doesn't support years, let's just say 1 year = 365 days
    years = duration_dict.pop("years")
    duration_dict["days"] += int(years) * 365

    return timedelta(**duration_dict)
