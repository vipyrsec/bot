from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import discord

from bot.dragonfly_services import DragonflyServices, QueueStatus

log = logging.getLogger(__name__)

ClusterQueueStatus = QueueStatus | Exception


async def fetch_cluster_queue_statuses(
    services: dict[str, DragonflyServices],
) -> dict[str, ClusterQueueStatus]:
    """Fetch independent cluster snapshots concurrently."""

    async def fetch(name: str, service: DragonflyServices) -> tuple[str, ClusterQueueStatus]:
        try:
            return name, await service.get_queue_status()
        except Exception as error:  # noqa: BLE001 - One unavailable cluster must not hide the others.
            log.warning("Failed to fetch Dragonfly queue status for %s", name, exc_info=error)
            return name, error

    return dict(await asyncio.gather(*(fetch(name, service) for name, service in services.items())))


def build_queue_status_embed(
    statuses: dict[str, ClusterQueueStatus],
    *,
    now: datetime | None = None,
) -> discord.Embed:
    """Build a compact multi-cluster queue summary."""
    current_time = now or datetime.now(tz=UTC)
    embed = discord.Embed(title="Dragonfly queue status", color=discord.Colour.blue(), timestamp=current_time)

    for cluster, snapshot in sorted(statuses.items()):
        if isinstance(snapshot, Exception):
            embed.add_field(name=cluster.title(), value="Unavailable", inline=False)
            continue

        oldest = "none"
        if snapshot.oldest_queued_at is not None:
            oldest = discord.utils.format_dt(snapshot.oldest_queued_at, "R")

        sampled = discord.utils.format_dt(snapshot.sampled_at, "R")
        value = (
            f"Queued: **{snapshot.queued:,}** · Scanning: **{snapshot.in_progress:,}** · "
            f"Retryable: **{snapshot.retryable:,}**\n"
            f"Backlog: **{snapshot.total_backlog:,}** · Oldest: **{oldest}** · Sampled {sampled}"
        )
        embed.add_field(name=cluster.title(), value=value, inline=False)

    if not statuses:
        embed.description = "No Dragonfly clusters are configured."
    return embed
