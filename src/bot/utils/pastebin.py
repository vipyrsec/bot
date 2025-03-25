"""Utilities relating to Pastebin services."""

from typing import Literal

import aiohttp
from pydantic import BaseModel

from bot.constants import Pastebin


class PastebinNotConfiguredError(Exception):
    """Raised when a paste was requested but no pastebin service is configured."""

    def __init__(self) -> None:
        super().__init__("A pastebin service is not configured.")


class PasteFile(BaseModel):
    """Represents a single file as part of a paste request."""

    name: str | None = None
    lexer: str
    content: str


class PasteRequest(BaseModel):
    """Represents a paste request."""

    expiry: Literal["1day", "7days", "30days"]
    files: list[PasteFile]


class PasteResponse(BaseModel):
    """Represents a paste response."""

    link: str
    removal: str


async def paste(payload: PasteRequest, *, session: aiohttp.ClientSession) -> PasteResponse:
    """Create a paste using the configured pastebin service. Raise an error if no service is configured."""
    if not (base_url := Pastebin.base_url):
        raise PastebinNotConfiguredError

    url = base_url + "/api/v1/paste"
    json = payload.model_dump()

    async with session.post(url, json=json) as response:
        response_json = await response.json()
        return PasteResponse.model_validate(response_json)
