"""Queue packages for analysis by snakehook-runner."""

from __future__ import annotations

import logging
from http import HTTPStatus
from json import JSONDecodeError
from typing import cast

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from bot.bot import Bot
from bot.constants import Roles
from bot.constants import Sandbox as SandboxConfig

log = logging.getLogger(__name__)

SANDBOX_TRIAGE_URL = "https://sandbox.vipyrsec.com/v1/triage"
SANDBOX_ERROR_MESSAGES = {
    HTTPStatus.UNAUTHORIZED: "Sandbox authentication is misconfigured.",
    HTTPStatus.UNPROCESSABLE_ENTITY: "The package name or version is invalid.",
    HTTPStatus.TOO_MANY_REQUESTS: "Sandbox policy or rate limits rejected this request.",
    HTTPStatus.SERVICE_UNAVAILABLE: "The sandbox queue is currently full. Please try again later.",
}
SANDBOX_UNAVAILABLE_MESSAGE = "Sandbox analysis is temporarily unavailable."


class Sandbox(commands.Cog):
    """Snakehook sandbox commands."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @app_commands.command(name="sandbox", description="Queue a Python package for sandbox analysis")
    @app_commands.describe(name="PyPI package name", version="Exact package version")
    @app_commands.checks.has_role(Roles.vipyr_security)  # type: ignore[arg-type]
    async def sandbox_command(
        self,
        interaction: discord.Interaction[Bot],
        name: str,
        version: str,
    ) -> None:
        """Queue an exact package release for sandbox analysis."""
        await interaction.response.defer(thinking=True, ephemeral=True)

        api_key = SandboxConfig.api_key.get_secret_value()
        if not api_key:
            log.error("SANDBOX_API_KEY is not configured")
            await interaction.followup.send(SANDBOX_UNAVAILABLE_MESSAGE, ephemeral=True)
            return

        try:
            async with self.bot.http_session.post(
                SANDBOX_TRIAGE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"package_name": name, "version": version},
            ) as response:
                if response.status != HTTPStatus.ACCEPTED:
                    message = SANDBOX_ERROR_MESSAGES.get(
                        HTTPStatus(response.status),
                        SANDBOX_UNAVAILABLE_MESSAGE,
                    )
                    log.warning("Sandbox rejected a queue request with HTTP %d", response.status)
                    await interaction.followup.send(message, ephemeral=True)
                    return

                run_id = _read_run_id(await response.json())
        except (TimeoutError, aiohttp.ClientError, JSONDecodeError, ValueError):
            log.warning("Sandbox queue request failed", exc_info=True)
            await interaction.followup.send(SANDBOX_UNAVAILABLE_MESSAGE, ephemeral=True)
            return

        if run_id is None:
            log.error("Sandbox accepted a request without returning a run ID")
            await interaction.followup.send(SANDBOX_UNAVAILABLE_MESSAGE, ephemeral=True)
            return

        await interaction.followup.send(
            f"Queued `{name} v{version}` for sandbox analysis. Run ID: `{run_id}`",
            ephemeral=True,
        )


def _read_run_id(payload: object) -> str | None:
    """Extract a non-empty run ID from a sandbox response."""
    if not isinstance(payload, dict):
        return None
    run_id = cast("dict[object, object]", payload).get("run_id")
    return run_id if isinstance(run_id, str) and run_id else None


async def setup(bot: Bot) -> None:
    """Load the sandbox cog."""
    await bot.add_cog(Sandbox(bot))
