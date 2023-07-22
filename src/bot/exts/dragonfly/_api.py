from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from bot.bot import Bot
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
    score: int

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
            package_id=data["scan_id"],
            rules=[d["name"] for d in data["rules"]],
            score=int(data["score"]),
        )

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


async def lookup_package_info(
    bot: Bot,
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

    headers = {"Authorization": f"Bearer {bot.access_token}"}

    req = bot.http_session.get(f"{DragonflyConfig.api_url}/package", params=params, headers=headers)
    res = await req
    if res.status == 401:
        await bot.authorize()
        res = await req
        res.raise_for_status()  # We should throw an error if something goes wrong the second time

    data = await res.json()
    return [PackageScanResult.from_dict(d) for d in data]


async def report_package(
    bot: Bot,
    *,
    name: str,
    version: str,
    inspector_url: Optional[str],
    additional_information: Optional[str],
    recipient: Optional[str],
) -> None:
    headers = {"Authorization": f"Bearer {bot.access_token}"}
    body = {
        "name": name,
        "version": version,
        "inspector_url": inspector_url,
        "additional_information": additional_information,
        "recipient": recipient,
    }

    req = bot.http_session.post(f"{DragonflyConfig.api_url}/report", json=body, headers=headers)
    res = await req
    if res.status == 401:
        await bot.authorize()
        res = await req
        res.raise_for_status()  # We should throw an error if something goes wrong the second time
