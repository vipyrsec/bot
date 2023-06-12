from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from aiohttp import ClientSession

from bot.constants import DragonflyConfig


class ScanStatus(Enum):
    QUEUED = "queued"
    PENDING = "pending"
    FINISHED = "finished"
    FAILED = "failed"


@dataclass
class PackageScanResult:
    status: ScanStatus
    inspector_url: str
    queued_at: datetime
    pending_at: datetime | None
    finished_at: datetime | None
    reported_at: datetime | None
    version: str
    name: str
    package_id: str
    rules: list[str]
    client_id: str | None

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            status=ScanStatus(data["status"]),
            inspector_url=data["inspector_url"],
            queued_at=datetime.fromisoformat(data["queued_at"]),
            pending_at=datetime.fromisoformat(p) if (p := data["pending_at"]) else None,
            finished_at=datetime.fromisoformat(p) if (p := data["finished_at"]) else None,
            reported_at=datetime.fromisoformat(p) if (p := data["reported_at"]) else None,
            version=data["version"],
            name=data["name"],
            package_id=data["package_id"],
            rules=[d["name"] for d in data["rules"]],
            client_id=data["client_id"],
        )


async def lookup_package_info(
    http_session: ClientSession,
    *,
    name: str | None = None,
    version: str | None = None,
    since: datetime | None = None,
) -> list[PackageScanResult]:
    params = {}
    if name:
        params["name"] = name

    if version:
        params["version"] = version

    if since:
        params["since"] = int(since.timestamp())

    async with http_session.get("/package", params=params) as res:
        res.raise_for_status()
        data = await res.json()
        return [PackageScanResult.from_dict(d) for d in data]
