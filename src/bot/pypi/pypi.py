from aiohttp import ClientSession
from bot.constants import PyPiConfigs
from xml.etree import ElementTree
from datetime import datetime
from dataclasses import dataclass
from xml.etree.ElementTree import Element

class PackageParserException(Exception):
    pass

@dataclass
class Package:
    title: str
    package_link: str
    inspector_link: str
    guid: str
    description: str | None
    author: str | None
    publication_date: datetime

def _parse_publication_date(publication_date: str) -> datetime:
    return datetime.strptime(publication_date, "%a, %d %b %Y %H:%M:%S %Z")

def _find_item(element: Element, name: str) -> str:
    item = element.find(name)
    if item is None:
        raise PackageParserException(f"<{name}> element was not found.")
    if item.text is None:
        raise PackageParserException(f"<{name}> element was found, but empty.")

    return item.text

def _parse_package(xml_element: Element) -> Package:
    title = _find_item(xml_element, "title").split(" ")[0]
    package_link = _find_item(xml_element, "link")
    inspector_link = "https://inspector.pypi.io/project/" + title
    guid = _find_item(xml_element, "guid")
    publication_date = _find_item(xml_element, "pubDate")
    publication_date = _parse_publication_date(publication_date)
    description = description_tag.text if (description_tag := xml_element.find("description")) is not None else None
    author = author_tag.text if (author_tag := xml_element.find("author")) is not None else None

    return Package(
        title=title,
        package_link=package_link,
        guid=guid,
        description=description,
        author=author,
        publication_date=publication_date,
        inspector_link=inspector_link
    )

async def get_packages(session: ClientSession) -> list[Package]:
    async with session.get(PyPiConfigs.rss_feed_url) as res:
        text = await res.text()
        root = ElementTree.fromstring(text)

        return [_parse_package(package) for package in root.iter("item")]
