from logging import Logger
from typing import TextIO

DEFAULT_LEVEL_STYLES: dict[str, dict[str, bool | int | str]]
DEFAULT_LOG_FORMAT: str

def install(
    level: int | str | None = ...,
    *,
    logger: Logger | None = ...,
    stream: TextIO | None = ...,
    **kwargs: object,
) -> None: ...
