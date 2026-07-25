from __future__ import annotations

from datetime import UTC, datetime

import discord

from bot.dragonfly_services import QueueStatus


def build_queue_status_embed(
    snapshot: QueueStatus,
    *,
    now: datetime | None = None,
) -> discord.Embed:
    """Build a compact queue summary for this bot's Dragonfly service."""
    current_time = now or datetime.now(tz=UTC)
    embed = discord.Embed(title="Dragonfly queue status", color=discord.Colour.blue(), timestamp=current_time)

    oldest = "none"
    if snapshot.oldest_queued_at is not None:
        oldest = discord.utils.format_dt(snapshot.oldest_queued_at, "R")

    sampled = discord.utils.format_dt(snapshot.sampled_at, "R")
    embed.description = (
        f"Queued: **{snapshot.queued:,}** · Scanning: **{snapshot.in_progress:,}** · "
        f"Retryable: **{snapshot.retryable:,}** · Stranded: **{snapshot.stranded:,}**\n"
        f"Backlog: **{snapshot.total_backlog:,}** · Oldest: **{oldest}** · Sampled {sampled}"
    )
    return embed
