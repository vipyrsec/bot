"""Interacting with the Dragonfly API."""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Self
from urllib.parse import quote

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


class QueueStatus(BaseModel):
    """Cached queue summary returned by Mainframe."""

    queued: int
    in_progress: int
    retryable: int
    stranded: int
    total_backlog: int
    oldest_queued_at: datetime | None
    oldest_age_seconds: int | None
    sampled_at: datetime


class AlertingConfiguration(BaseModel):
    """Production alerting configuration owned by Mainframe."""

    production_score_threshold: int
    updated_at: datetime
    updated_by: str


class OpenGrepFinding(BaseModel):
    """One source-level OpenGrep evidence record."""

    rule_id: str
    path: str
    start_line: int
    end_line: int
    message: str
    severity: str
    evidence: str
    confidence: str
    execution_context: str
    inspector_url: str


class OpenGrepResult(BaseModel):
    """A completed OpenGrep shadow result awaiting publication."""

    scan_id: uuid.UUID
    name: str
    version: str
    status: ScanStatus
    commit: str | None
    duration_ms: int | None
    findings: list[OpenGrepFinding]
    fail_reason: str | None
    finished_at: datetime
    publication_id: uuid.UUID
    discord_message_id: int | None
    discord_thread_id: int | None
    published_chunks: int


class Suppression(BaseModel):
    """A package-version alert suppression owned by Mainframe."""

    suppression_id: uuid.UUID
    package_name: str
    package_version: str
    rules: list[str] | None
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str


class SuppressionDeleteResponse(BaseModel):
    """Number of suppressions deleted by Mainframe."""

    deleted: int


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
        access_client_id: str,
        access_client_secret: str,
    ) -> None:
        """Initialize the DragonflyServices class."""
        self.session = session
        self.base_url = base_url
        self.access_client_id = access_client_id
        self.access_client_secret = access_client_secret

    def _build_access_headers(self: Self) -> dict[str, str]:
        """Build Cloudflare Access service-token headers."""
        return {
            "CF-Access-Client-Id": self.access_client_id,
            "CF-Access-Client-Secret": self.access_client_secret,
        }

    async def make_request(
        self: Self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to Dragonfly's API."""
        async with self.session.request(
            method=method,
            url=self.base_url + path,
            headers=self._build_access_headers(),
            params=params,
            json=json,
        ) as response:
            response.raise_for_status()
            return await response.json()  # type: ignore[no-any-return]

    async def get_scanned_packages(
        self: Self,
        name: str | None = None,
        version: str | None = None,
        since: datetime | None = None,
    ) -> list[Package]:
        """Get a list of scanned packages."""
        params: dict[str, str | int] = {}
        if name:
            params["name"] = name

        if version:
            params["version"] = version

        if since:
            params["since"] = int(since.timestamp())  # type: ignore[assignment]

        data = await self.make_request("GET", "/package", params=params)
        return list(map(Package.model_validate, data))

    async def get_queue_status(self: Self) -> QueueStatus:
        """Get Mainframe's latest cached queue snapshot."""
        data = await self.make_request("GET", "/queue-status")
        return QueueStatus.model_validate(data)

    async def get_alerting_configuration(self: Self) -> AlertingConfiguration:
        """Get Mainframe's durable production alerting configuration."""
        data = await self.make_request("GET", "/alerting/configuration")
        return AlertingConfiguration.model_validate(data)

    async def get_opengrep_results(self: Self) -> list[OpenGrepResult]:
        """Get completed, unpublished OpenGrep shadow results."""
        data = await self.make_request("GET", "/opengrep/results")
        return [OpenGrepResult.model_validate(item) for item in data]

    async def checkpoint_opengrep_publication(
        self: Self,
        result: OpenGrepResult,
        *,
        discord_message_id: int | None,
        discord_thread_id: int | None,
        published_chunks: int,
    ) -> None:
        """Persist monotonic Discord publication progress."""
        await self.make_request(
            "POST",
            f"/opengrep/results/{result.scan_id}/publication",
            json={
                "publication_id": str(result.publication_id),
                "discord_message_id": discord_message_id,
                "discord_thread_id": discord_thread_id,
                "published_chunks": published_chunks,
            },
        )

    async def acknowledge_opengrep_result(self: Self, result: OpenGrepResult) -> None:
        """Acknowledge a result after its complete Discord publication."""
        await self.make_request(
            "POST",
            f"/opengrep/results/{result.scan_id}/published",
            json={"publication_id": str(result.publication_id)},
        )

    async def update_alerting_configuration(
        self: Self,
        production_score_threshold: int,
    ) -> AlertingConfiguration:
        """Update Mainframe's durable production alerting configuration."""
        data = await self.make_request(
            "PUT",
            "/alerting/configuration",
            json={"production_score_threshold": production_score_threshold},
        )
        return AlertingConfiguration.model_validate(data)

    @staticmethod
    def _suppression_collection_path(package_name: str, package_version: str | None = None) -> str:
        package_path = quote(package_name, safe="")
        if package_version is None:
            return f"/packages/{package_path}/suppressions"
        version_path = quote(package_version, safe="")
        return f"/packages/{package_path}/versions/{version_path}/suppressions"

    async def get_suppressions(self: Self, package_name: str) -> list[Suppression]:
        """Get every suppression for a package across all versions."""
        path = self._suppression_collection_path(package_name)
        data = await self.make_request("GET", path)
        return [Suppression.model_validate(item) for item in data]

    async def get_suppression(
        self: Self,
        package_name: str,
        package_version: str,
        suppression_id: uuid.UUID,
    ) -> Suppression:
        """Get one suppression by its stable identifier."""
        path = f"{self._suppression_collection_path(package_name, package_version)}/{suppression_id}"
        data = await self.make_request("GET", path)
        return Suppression.model_validate(data)

    async def create_suppression(
        self: Self,
        package_name: str,
        package_version: str,
        rules: list[str] | None = None,
    ) -> Suppression:
        """Create a suppression; null rules suppress every rule."""
        path = self._suppression_collection_path(package_name, package_version)
        data = await self.make_request("POST", path, json={"rules": rules})
        return Suppression.model_validate(data)

    async def update_suppression(
        self: Self,
        package_name: str,
        package_version: str,
        suppression_id: uuid.UUID,
        rules: list[str] | None,
    ) -> Suppression:
        """Replace one suppression's rule corpus."""
        path = f"{self._suppression_collection_path(package_name, package_version)}/{suppression_id}"
        data = await self.make_request("PATCH", path, json={"rules": rules})
        return Suppression.model_validate(data)

    async def delete_suppression(
        self: Self,
        package_name: str,
        package_version: str,
        suppression_id: uuid.UUID,
    ) -> SuppressionDeleteResponse:
        """Delete one suppression."""
        path = f"{self._suppression_collection_path(package_name, package_version)}/{suppression_id}"
        data = await self.make_request("DELETE", path)
        return SuppressionDeleteResponse.model_validate(data)

    async def delete_version_suppressions(
        self: Self,
        package_name: str,
        package_version: str,
    ) -> SuppressionDeleteResponse:
        """Delete every suppression for one package version."""
        path = self._suppression_collection_path(package_name, package_version)
        data = await self.make_request("DELETE", path)
        return SuppressionDeleteResponse.model_validate(data)

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
