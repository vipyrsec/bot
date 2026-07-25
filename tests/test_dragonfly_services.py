"""Tests for the Dragonfly API wrapper."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Self
from unittest.mock import AsyncMock, Mock

import pytest

from bot.dragonfly_services import (
    AlertingConfiguration,
    DragonflyServices,
    Package,
    PackageReport,
    QueueStatus,
    ScanStatus,
)


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


def _service() -> DragonflyServices:
    return DragonflyServices(
        session=Mock(),
        base_url="https://dragonfly-staging.vipyrsec.com",
        access_client_id="client-id",
        access_client_secret="client-secret",
    )


@pytest.mark.parametrize(
    ("method", "path", "params", "json"),
    [
        ("GET", "/package", {"since": 1}, None),
        (
            "POST",
            "/report",
            None,
            {
                "name": "example",
                "version": "1.0.0",
                "inspector_url": None,
                "additional_information": None,
                "recipient": None,
                "use_email": False,
            },
        ),
        ("POST", "/package", None, {"name": "example", "version": "1.0.0"}),
    ],
)
def test_every_dragonfly_route_uses_cf_access_headers(
    method: str,
    path: str,
    params: dict[str, Any] | None,
    json: dict[str, Any] | None,
) -> None:
    response = _MockResponse({"ok": True})
    session = Mock()
    session.request.return_value = response
    service = _service()
    service.session = session

    payload = asyncio.run(service.make_request(method, path, params=params, json=json))

    assert payload == {"ok": True}
    expected_request: dict[str, object] = {
        "url": f"https://dragonfly-staging.vipyrsec.com{path}",
        "method": method,
        "headers": {
            "CF-Access-Client-Id": "client-id",
            "CF-Access-Client-Secret": "client-secret",
        },
        "params": params,
        "json": json,
    }

    session.request.assert_called_once_with(**expected_request)
    response.raise_for_status.assert_called_once_with()


def test_package_string() -> None:
    package = Package(
        scan_id="scan-id",
        name="example",
        version="1.0.0",
        status=ScanStatus.FINISHED,
        score=0,
        inspector_url=None,
        queued_at=None,
        queued_by=None,
        reported_at=None,
        reported_by=None,
        pending_at=None,
        pending_by=None,
        finished_at=None,
        finished_by=None,
        commit_hash=None,
    )

    assert str(package) == "example 1.0.0"


def test_get_scanned_packages() -> None:
    service = _service()
    service.make_request = AsyncMock(
        return_value=[
            {
                "scan_id": "scan-id",
                "name": "example",
                "version": "1.0.0",
                "status": "finished",
                "score": 0,
                "inspector_url": None,
                "queued_at": None,
                "queued_by": None,
                "reported_at": None,
                "reported_by": None,
                "pending_at": None,
                "pending_by": None,
                "finished_at": None,
                "finished_by": None,
                "commit_hash": None,
            },
        ],
    )
    since = dt.datetime(2026, 7, 23, tzinfo=dt.UTC)

    packages = asyncio.run(service.get_scanned_packages(name="example", version="1.0.0", since=since))

    assert [(package.name, package.version) for package in packages] == [("example", "1.0.0")]
    service.make_request.assert_awaited_once_with(
        "GET",
        "/package",
        params={"name": "example", "version": "1.0.0", "since": int(since.timestamp())},
    )


def test_report_package() -> None:
    service = _service()
    service.make_request = AsyncMock()
    report = PackageReport(
        name="example",
        version="1.0.0",
        inspector_url=None,
        additional_information="malicious",
        recipient=None,
        use_email=False,
    )

    asyncio.run(service.report_package(report))

    service.make_request.assert_awaited_once_with(
        "POST",
        "/report",
        json={
            "name": "example",
            "version": "1.0.0",
            "inspector_url": None,
            "additional_information": "malicious",
            "recipient": None,
            "use_email": False,
        },
    )


def test_get_queue_status() -> None:
    service = _service()
    sampled_at = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    service.make_request = AsyncMock(
        return_value={
            "queued": 12,
            "in_progress": 2,
            "retryable": 1,
            "stranded": 0,
            "total_backlog": 13,
            "oldest_queued_at": int((sampled_at - dt.timedelta(minutes=5)).timestamp()),
            "oldest_age_seconds": 300,
            "sampled_at": int(sampled_at.timestamp()),
        }
    )

    snapshot = asyncio.run(service.get_queue_status())

    assert snapshot == QueueStatus(
        queued=12,
        in_progress=2,
        retryable=1,
        stranded=0,
        total_backlog=13,
        oldest_queued_at=sampled_at - dt.timedelta(minutes=5),
        oldest_age_seconds=300,
        sampled_at=sampled_at,
    )
    service.make_request.assert_awaited_once_with("GET", "/queue-status")


def test_queue_package() -> None:
    service = _service()
    service.make_request = AsyncMock()

    asyncio.run(service.queue_package("example", "1.0.0"))

    service.make_request.assert_awaited_once_with(
        "POST",
        "/package",
        json={"name": "example", "version": "1.0.0"},
    )


def test_get_alerting_configuration() -> None:
    service = _service()
    updated_at = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    service.make_request = AsyncMock(
        return_value={
            "production_score_threshold": 8,
            "updated_at": int(updated_at.timestamp()),
            "updated_by": "bot",
        }
    )

    configuration = asyncio.run(service.get_alerting_configuration())

    assert configuration == AlertingConfiguration(
        production_score_threshold=8,
        updated_at=updated_at,
        updated_by="bot",
    )
    service.make_request.assert_awaited_once_with("GET", "/alerting/configuration")


def test_update_alerting_configuration() -> None:
    service = _service()
    updated_at = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    service.make_request = AsyncMock(
        return_value={
            "production_score_threshold": 12,
            "updated_at": int(updated_at.timestamp()),
            "updated_by": "bot",
        }
    )

    configuration = asyncio.run(service.update_alerting_configuration(12))

    assert configuration.production_score_threshold == 12
    service.make_request.assert_awaited_once_with(
        "PUT",
        "/alerting/configuration",
        json={"production_score_threshold": 12},
    )
