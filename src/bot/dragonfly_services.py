"""Interacting with the Dragonfly API."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from aiohttp import ClientSession


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


class DragonflyServices:
    """A class wrapping Dragonfly's API."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        auth_url: str,
        audience: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
    ) -> None:
        self.session = session
        self.base_url = base_url
        self.auth_url = auth_url
        self.audience = audience
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.token = ""
        self.token_expires_at = datetime.now()

    async def _update_token(self) -> None:
        """Update the OAUTH token."""
        if self.token_expires_at > datetime.now():
            return

        auth_dict = {
            "grant_type": "password",
            "audience": self.audience,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }
        async with self.session.post(self.auth_url, json=auth_dict) as response:
            data = await response.json()
            self.token = data["access_token"]
            self.token_expires_at = datetime.now() + timedelta(seconds=data["expires_in"])

    async def make_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict:
        """Make a request to Dragonfly's API."""
        await self._update_token()

        headers = {"Authorization": "Bearer " + self.token}

        args = {
            "url": self.base_url + path,
            "method": method,
            "headers": headers,
        }

        if params is not None:
            args["params"] = params

        if json is not None:
            args["json"] = json

        async with self.session.request(**args) as response:
            return await response.json()

    async def get_scanned_packages(
        self,
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

        data = await self.make_request("GET", "/package", params=params)
        return [PackageScanResult.from_dict(dct) for dct in data]

    async def report_package(
        self,
        name: str,
        version: str,
        inspector_url: str | None,
        additional_information: str | None,
        recipient: str | None,
    ) -> None:
        data = {
            "name": name,
            "version": version,
            "inspector_url": inspector_url,
            "additional_information": additional_information,
            "recipient": recipient,
        }
        await self.make_request("POST", "/report", json=data)
