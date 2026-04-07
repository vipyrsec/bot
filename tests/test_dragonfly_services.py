"""Tests for the Dragonfly API wrapper."""

from __future__ import annotations

import asyncio
from typing import Any, Self
from unittest.mock import Mock

from bot.dragonfly_services import DragonflyServices


class _MockResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.raise_for_status = Mock()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._payload


def test_make_request_uses_cf_access_headers() -> None:
    response = _MockResponse({"ok": True})
    session = Mock()
    session.request.return_value = response
    service = DragonflyServices(
        session=session,
        base_url="https://dragonfly-staging.vipyrsec.com",
        client_id="client-id",
        client_secret="client-secret",
    )

    payload = asyncio.run(service.make_request("GET", "/package", params={"since": 1}))

    assert payload == {"ok": True}
    session.request.assert_called_once_with(
        url="https://dragonfly-staging.vipyrsec.com/package",
        method="GET",
        headers={
            "CF-Access-Client-Id": "client-id",
            "CF-Access-Client-Secret": "client-secret",
        },
        params={"since": 1},
    )
    response.raise_for_status.assert_called_once_with()
