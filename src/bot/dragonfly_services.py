"""Interacting with the Dragonfly API."""

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Self

from aiohttp import ClientSession
from pydantic import BaseModel


class ScanStatus(Enum):
    """The status of a package scan."""

    QUEUED = "queued"
    PENDING = "pending"
    FINISHED = "finished"
    FAILED = "failed"


class Package(BaseModel):
    """Model representing a package queried from the database."""

    scan_id: str
    name: str
    version: str
    status: ScanStatus | None
    score: int | None
    inspector_url: str | None
    rules: list[str] = []
    download_urls: list[str] = []
    queued_at: datetime | None
    queued_by: str | None
    reported_at: datetime | None
    reported_by: str | None
    pending_at: datetime | None
    pending_by: str | None
    finished_at: datetime | None
    finished_by: str | None
    commit_hash: str | None

    def __str__(self) -> str:
        """Return package name and version."""
        return f"{self.name} {self.version}"


@dataclass
class PackageReport:
    """Represents the payload sent to the report endpoint."""

    name: str
    version: str
    inspector_url: str | None
    additional_information: str | None
    recipient: str | None
    use_email: bool


class DragonflyServices:
    """A class wrapping Dragonfly's API."""

    def __init__(
        self: Self,
        session: ClientSession,
        base_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Initialize the DragonflyServices class."""
        self.session = session
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret

    def _build_access_headers(self: Self) -> dict[str, str]:
        """Build Cloudflare Access service-token headers."""
        return {
            "CF-Access-Client-Id": self.client_id,
            "CF-Access-Client-Secret": self.client_secret,
        }

    async def make_request(
        self: Self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Make a request to Dragonfly's API."""
        args = {
            "url": self.base_url + path,
            "method": method,
            "headers": self._build_access_headers(),
        }

        if params is not None:
            args["params"] = params

        if json is not None:
            args["json"] = json

        async with self.session.request(**args) as response:  # type: ignore[arg-type]
            response.raise_for_status()
            return await response.json()  # type: ignore[no-any-return]

    async def get_scanned_packages(
        self: Self,
        name: str | None = None,
        version: str | None = None,
        since: datetime | None = None,
    ) -> list[Package]:
        """Get a list of scanned packages."""
        params = {}
        if name:
            params["name"] = name

        if version:
            params["version"] = version

        if since:
            params["since"] = int(since.timestamp())  # type: ignore[assignment]

        data = await self.make_request("GET", "/package", params=params)
        return list(map(Package.model_validate, data))

    async def report_package(
        self: Self,
        report: PackageReport,
    ) -> None:
        """Report a package to Dragonfly."""
        data = dataclasses.asdict(report)
        await self.make_request("POST", "/report", json=data)

    async def queue_package(self: Self, name: str, version: str) -> None:
        """Add a package to the Dragonfly scan queue."""
        data = {
            "name": name,
            "version": version,
        }

        await self.make_request("POST", "/package", json=data)
