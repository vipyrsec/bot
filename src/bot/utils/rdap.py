import ipaddress
import re
from typing import Any, cast


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

            name = cast("str", prop[0])
            value = cast("str", prop[3])

            if name == "fn":
                result["name"] = value
            elif name == "email":
                result["email"] = value

    return result
