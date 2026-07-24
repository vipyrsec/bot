"""RDAP query validation and response parsing."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterator
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, Field

MIN_VCARD_FIELDS = 4
VCARD_VALUE_INDEX = 3
MAX_ASN = 2**32 - 1
MAX_DOMAIN_LENGTH = 253
MAX_DOMAIN_LABEL_LENGTH = 63

QueryType = Literal["ip", "autnum", "domain"]

ASN_RE = re.compile(r"^as(?P<number>\d+)$", re.IGNORECASE)
DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class InvalidRDAPQuery(ValueError):
    """Raised when a query is not an IP address, ASN, or valid domain name."""


class RDAPEntity(BaseModel):
    """An entity in an RDAP response, such as a registrar or abuse contact."""

    roles: Annotated[list[str], Field(default_factory=list)]
    public_ids: Annotated[list[dict[str, Any]], Field(default_factory=list, validation_alias="publicIds")]
    vcard_array: Annotated[list[Any], Field(default_factory=list, validation_alias="vcardArray")]
    entities: Annotated[list[RDAPEntity], Field(default_factory=list)]

    @property
    def contact_info(self) -> dict[str, str | None]:
        """Extract the name and email address from the entity's jCard."""
        return parse_rdap_vcard(self.vcard_array)

    def walk(self) -> Iterator[RDAPEntity]:
        """Yield this entity and all nested entities."""
        yield self
        for entity in self.entities:
            yield from entity.walk()


class RDAPResponse(BaseModel):
    """Fields shared by domain, IP network, and ASN RDAP responses."""

    handle: str | None = None
    entities: Annotated[list[RDAPEntity], Field(default_factory=list)]
    links: Annotated[list[dict[str, Any]], Field(default_factory=list)]

    def get_entity_by_role(self, role: str) -> RDAPEntity | None:
        """Find the first top-level or nested entity with the specified role."""
        return next(
            (candidate for entity in self.entities for candidate in entity.walk() if role in candidate.roles),
            None,
        )


class RDAPDomain(RDAPResponse):
    """A domain RDAP response."""

    ldh_name: str | None = Field(default=None, validation_alias="ldhName")
    events: Annotated[list[dict[str, Any]], Field(default_factory=list)]
    nameservers: Annotated[list[dict[str, Any]], Field(default_factory=list)]

    def event_date(self, action: str) -> str | None:
        """Return the date for the first matching RDAP event."""
        for event in self.events:
            if event.get("eventAction") == action:
                date = event.get("eventDate")
                return date if isinstance(date, str) else None
        return None


class RDAPIP(RDAPResponse):
    """An IP network RDAP response."""

    start_address: str | None = Field(default=None, validation_alias="startAddress")
    end_address: str | None = Field(default=None, validation_alias="endAddress")
    name: str | None = None
    parent_handle: str | None = Field(default=None, validation_alias="parentHandle")
    cidr0_cidrs: Annotated[list[dict[str, Any]], Field(default_factory=list, validation_alias="cidr0_cidrs")]

    @property
    def cidrs(self) -> list[str]:
        """Return CIDR0 extension entries in conventional notation."""
        result: list[str] = []
        for cidr in self.cidr0_cidrs:
            prefix = cidr.get("v4prefix", cidr.get("v6prefix"))
            length = cidr.get("length")
            if isinstance(prefix, str) and isinstance(length, int):
                result.append(f"{prefix}/{length}")
        return result


class RDAPASN(RDAPResponse):
    """An autonomous system number RDAP response."""

    start_autnum: int | None = Field(default=None, validation_alias="startAutnum")
    end_autnum: int | None = Field(default=None, validation_alias="endAutnum")
    name: str | None = None


def normalize_query(query: str) -> tuple[QueryType, str]:
    """Validate and normalize an IP address, ASN, or domain query."""
    query = query.strip()
    if not query:
        message = "The query cannot be empty."
        raise InvalidRDAPQuery(message)

    try:
        address = ipaddress.ip_address(query)
    except ValueError:
        pass
    else:
        return "ip", address.compressed

    if asn_match := ASN_RE.fullmatch(query):
        asn = int(asn_match.group("number"))
        if asn > MAX_ASN:
            message = f"ASN must not exceed {MAX_ASN}."
            raise InvalidRDAPQuery(message)
        return "autnum", str(asn)

    domain = _normalize_domain(query)
    return "domain", domain


def _normalize_domain(query: str) -> str:
    """Normalize and validate a domain name for an RDAP path."""
    domain = query.rstrip(".")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        message = "The domain name is not valid IDNA."
        raise InvalidRDAPQuery(message) from error

    if not ascii_domain or len(ascii_domain) > MAX_DOMAIN_LENGTH:
        message = "The domain name has an invalid length."
        raise InvalidRDAPQuery(message)

    labels = ascii_domain.split(".")
    if any(len(label) > MAX_DOMAIN_LABEL_LENGTH or DOMAIN_LABEL_RE.fullmatch(label) is None for label in labels):
        message = "The domain name contains an invalid label."
        raise InvalidRDAPQuery(message)

    return ascii_domain


def parse_rdap_vcard(vcard_array: list[Any]) -> dict[str, str | None]:
    """Parse a jCard array for the formatted name and email address."""
    result: dict[str, str | None] = {"name": None, "email": None}
    if len(vcard_array) <= 1:
        return result

    raw_properties: object = vcard_array[1]
    if not isinstance(raw_properties, list):
        return result

    for raw_property in cast("list[object]", raw_properties):
        if not isinstance(raw_property, list):
            continue
        prop = cast("list[object]", raw_property)
        if len(prop) < MIN_VCARD_FIELDS:
            continue

        name = prop[0]
        value = prop[VCARD_VALUE_INDEX]
        if not isinstance(name, str) or not isinstance(value, str):
            continue

        if name == "fn":
            result["name"] = value
        elif name == "email":
            result["email"] = value

    return result
