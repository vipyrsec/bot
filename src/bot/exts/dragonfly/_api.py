from dataclasses import dataclass
from logging import getLogger
from typing import Self

from aiohttp import ClientSession

from bot.constants import DragonflyConfig

log = getLogger(__name__)


class DragonflyAPIException(Exception):
    pass


@dataclass
class MaliciousFile:
    file_name: str
    rules: dict[str, int]


@dataclass
class PackageAnalysisResults:
    malicious_files: list[MaliciousFile]

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(malicious_files=d["malicious_files"])


@dataclass
class HighestScoreDistribution:
    score: int
    matches: list[str]
    most_malicious_file: str
    inspector_link: str

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            score=d["score"],
            matches=d["matches"],
            most_malicious_file=d["most_malicious_file"],
            inspector_link=d["inspector_link"],
        )


@dataclass
class PackageDistributionScanResults:
    file_name: str
    inspector_url: str
    analysis: PackageAnalysisResults

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            file_name=d["file_name"],
            inspector_url=d["inspector_url"],
            analysis=PackageAnalysisResults.from_dict(d["analysis"]),
        )


@dataclass
class PackageScanResult:
    """Package scan result from the API"""

    name: str
    version: str
    pypi_link: str
    distributions: list[PackageDistributionScanResults]
    highest_score_distribution: HighestScoreDistribution

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            name=d["name"],
            version=d["version"],
            pypi_link=d["pypi_link"],
            distributions=[
                PackageDistributionScanResults.from_dict(distribution) for distribution in d["distributions"]
            ],
            highest_score_distribution=HighestScoreDistribution.from_dict(d["highest_score_distribution"]),
        )


async def check_package(
    package_name: str,
    version: str | None = None,
    *,
    http_session: ClientSession,
) -> PackageScanResult | None:
    data = dict(package_name=package_name, version=version) if version is not None else dict(package_name=package_name)
    async with http_session.post(
        DragonflyConfig.dragonfly_api_url + "/check/",
        json=data,
    ) as res:
        json = await res.json()

        if res.status != 200:
            raise DragonflyAPIException(
                f"Error from upstream Dragonfly API while scanning package '{package_name}': {json}"
            )

        if json["highest_score_distribution"] is None:
            return None

        return PackageScanResult.from_dict(json)
