"""Tests for the snakehook sandbox command."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from http import HTTPStatus
from typing import Any, Self, cast
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import discord
import pytest
from discord import app_commands
from pydantic import SecretStr

from bot.bot import Bot
from bot.exts import sandbox


class _MockResponse:
    def __init__(self, status: HTTPStatus, payload: object = None) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def json(self) -> object:
        return self._payload


def _invoke_command(
    *,
    api_key: str = "test-api-key",
    response: _MockResponse | None = None,
    request_error: Exception | None = None,
    name: str = "example-package",
    version: str = "1.2.3",
) -> tuple[Mock, Mock]:
    session = Mock()
    if request_error is not None:
        session.post.side_effect = request_error
    else:
        session.post.return_value = response or _MockResponse(
            HTTPStatus.ACCEPTED,
            {"run_id": "test-run-id"},
        )

    bot = cast("Bot", Mock(http_session=session))
    interaction_mock = Mock()
    interaction_mock.response.defer = AsyncMock()
    interaction_mock.followup.send = AsyncMock()
    interaction = cast("discord.Interaction[Bot]", interaction_mock)
    cog = sandbox.Sandbox(bot)
    command = cast("app_commands.Command[Any, ..., Any]", sandbox.Sandbox.sandbox_command)
    callback = cast(
        "Callable[[sandbox.Sandbox, discord.Interaction[Bot], str, str], Coroutine[Any, Any, None]]",
        command.callback,
    )

    with patch.object(sandbox.SandboxConfig, "api_key", SecretStr(api_key)):
        asyncio.run(callback(cog, interaction, name, version))

    interaction_mock.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
    return interaction_mock, session


def test_sandbox_is_a_role_restricted_slash_command() -> None:
    """The sandbox queue must be an application command with a role check."""
    command = sandbox.Sandbox.sandbox_command

    assert isinstance(command, app_commands.Command)
    assert command.name == "sandbox"
    assert command.description == "Queue a Python package for sandbox analysis"
    assert command.checks


def test_sandbox_api_key_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """SANDBOX_API_KEY must populate a redacting runtime secret."""
    monkeypatch.setenv("SANDBOX_API_KEY", "configured-api-key")

    config = type(sandbox.SandboxConfig)()

    assert config.api_key.get_secret_value() == "configured-api-key"
    assert "configured-api-key" not in repr(config)


def test_sandbox_command_queues_package() -> None:
    """An accepted package returns its run ID without exposing the API key."""
    interaction, session = _invoke_command()

    session.post.assert_called_once_with(
        sandbox.SANDBOX_TRIAGE_URL,
        headers={"Authorization": "Bearer test-api-key"},
        json={"package_name": "example-package", "version": "1.2.3"},
    )
    interaction.followup.send.assert_awaited_once_with(
        "Queued `example-package v1.2.3` for sandbox analysis. Run ID: `test-run-id`",
        ephemeral=True,
    )


def test_sandbox_command_escapes_inline_code_values() -> None:
    """Package and service text must not inject Discord inline-code delimiters."""
    interaction, _ = _invoke_command(
        name="example`package",
        version="1.`2.3",
        response=_MockResponse(HTTPStatus.ACCEPTED, {"run_id": "run`id"}),
    )

    interaction.followup.send.assert_awaited_once_with(
        "Queued `example'package v1.'2.3` for sandbox analysis. Run ID: `run'id`",
        ephemeral=True,
    )


def test_inline_code_bounds_response_values() -> None:
    """Unexpectedly large service values must remain within a Discord response."""
    interaction, _ = _invoke_command(
        response=_MockResponse(HTTPStatus.ACCEPTED, {"run_id": "x" * 301}),
    )

    interaction.followup.send.assert_awaited_once_with(
        f"Queued `example-package v1.2.3` for sandbox analysis. Run ID: `{'x' * 299}…`",
        ephemeral=True,
    )


def test_sandbox_command_fails_closed_without_api_key() -> None:
    """A missing runtime secret must not issue an unauthenticated request."""
    interaction, session = _invoke_command(api_key="")

    session.post.assert_not_called()
    interaction.followup.send.assert_awaited_once_with(
        sandbox.SANDBOX_UNAVAILABLE_MESSAGE,
        ephemeral=True,
    )


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (HTTPStatus.UNAUTHORIZED, "Sandbox authentication is misconfigured."),
        (HTTPStatus.UNPROCESSABLE_ENTITY, "The package name or version is invalid."),
        (HTTPStatus.TOO_MANY_REQUESTS, "Sandbox policy or rate limits rejected this request."),
        (HTTPStatus.SERVICE_UNAVAILABLE, "The sandbox queue is currently full. Please try again later."),
        (HTTPStatus.INTERNAL_SERVER_ERROR, sandbox.SANDBOX_UNAVAILABLE_MESSAGE),
    ],
)
def test_sandbox_command_maps_rejected_requests(status: HTTPStatus, message: str) -> None:
    """Expected API failures must produce concise, secret-free responses."""
    interaction, _ = _invoke_command(response=_MockResponse(status))

    interaction.followup.send.assert_awaited_once_with(message, ephemeral=True)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"run_id": ""},
        {"run_id": 123},
    ],
)
def test_sandbox_command_rejects_invalid_accepted_response(payload: object) -> None:
    """An accepted response still requires a non-empty string run ID."""
    interaction, _ = _invoke_command(response=_MockResponse(HTTPStatus.ACCEPTED, payload))

    interaction.followup.send.assert_awaited_once_with(
        sandbox.SANDBOX_UNAVAILABLE_MESSAGE,
        ephemeral=True,
    )


def test_sandbox_command_handles_client_failure() -> None:
    """Network failures must produce a generic response without leaking request details."""
    interaction, _ = _invoke_command(request_error=aiohttp.ClientConnectionError())

    interaction.followup.send.assert_awaited_once_with(
        sandbox.SANDBOX_UNAVAILABLE_MESSAGE,
        ephemeral=True,
    )


def test_sandbox_setup_adds_cog() -> None:
    """The extension setup must register the sandbox cog."""
    bot = cast("Bot", Mock())
    bot.add_cog = AsyncMock()

    asyncio.run(sandbox.setup(bot))

    bot.add_cog.assert_awaited_once()
    assert bot.add_cog.await_args is not None
    assert isinstance(bot.add_cog.await_args.args[0], sandbox.Sandbox)
