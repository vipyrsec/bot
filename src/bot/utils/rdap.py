import ipaddress
import re
from typing import Annotated, Any, cast

from pydantic import BaseModel, Field


class RDAPEntity(BaseModel):
    """
    Represents an entity in an RDAP response (e.g., registrar, registrant).

    Attributes:
        roles: List of roles this entity performs (e.g., 'registrar', 'abuse').
        publicIds: List of public identifiers (e.g., IANA ID).
        vcardArray: jCard formatted contact information.
    """

    roles: list[str] = []
    publicIds: list[dict[str, Any]] = []
    vcardArray: Annotated[list[Any], Field(default_factory=list)] = []

    @property
    def contact_info(self) -> dict[str, str | None]:
        """Extracts name and email from the vCard array."""
        return parse_rdap_vcard(self.vcardArray)


class RDAPResponse(BaseModel):
    """
    Base model for RDAP responses containing common fields.

    Attributes:
        handle: The registry-unique identifier of the object.
        entities: List of entities related to this object.
        links: List of related links (e.g., for 'thin' registry redirection).
    """

    handle: str | None = None
    entities: list[RDAPEntity] = []
    links: list[dict[str, Any]] = []

    def get_entity_by_role(self, role: str) -> RDAPEntity | None:
        """Finds the first entity with the specified role."""
        for entity in self.entities:
            if role in entity.roles:
                return entity
        return None


class RDAPDomain(RDAPResponse):
    """Model for Domain RDAP responses."""

    ldhName: str | None = None
    events: list[dict[str, Any]] = []
    nameservers: list[dict[str, Any]] = []

    @property
    def registration_date(self) -> str | None:
        """Extracts the registration date from events."""
        for event in self.events:
            if event.get("eventAction") == "registration":
                return event.get("eventDate")
        return None


class RDAPIP(RDAPResponse):
    """Model for IP Network RDAP responses."""

    startAddress: str | None = None
    endAddress: str | None = None
    name: str | None = None
    parentHandle: str | None = None
    type: str | None = None


class RDAPASN(RDAPResponse):
    """Model for Autonomous System Number RDAP responses."""

    startAutnum: int | None = None
    endAutnum: int | None = None
    name: str | None = None
    type: str | None = None



def classify_query(query: str) -> str:
    """
    Classify the query as 'ip', 'asn', or 'domain'.
    """
    query = query.strip()

    try:
        ipaddress.ip_address(query)
        return "ip"
    except ValueError:
        pass

    if re.match(r"^as\d+$", query, re.IGNORECASE):
        return "autnum"

    return "domain"


def parse_rdap_vcard(vcard_array: Any) -> dict[str, str | None]:
    """
    Parse a jCard array to extract 'fn' (name) and 'email'.
    """
    result: dict[str, str | None] = {"name": None, "email": None}

    if not vcard_array or not isinstance(vcard_array, list):
        return result

    # jCard format: ["vcard", [ [property, {params}, type, value], ... ]]
    if len(vcard_array) > 1 and isinstance(vcard_array[1], list):  # type: ignore
        properties = cast("list[list[Any]]", vcard_array[1])
        for prop in properties:
            if len(prop) < 4:
                continue

            name = cast(str, prop[0])
            value = cast(str, prop[3])

            if name == "fn":
                result["name"] = value
            elif name == "email":
                result["email"] = value

    return result
