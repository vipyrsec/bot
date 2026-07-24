"""Discord command for Registration Data Access Protocol lookups."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from collections.abc import Iterator, Sequence
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote, urlsplit

import aiohttp
import discord
from discord import Embed, app_commands
from discord.ext import commands
from pydantic import ValidationError

from bot.bot import Bot
from bot.constants import BaseURLs, Colours
from bot.utils.rdap import (
    RDAPASN,
    RDAPIP,
    InvalidRDAPQuery,
    QueryType,
    RDAPDomain,
    RDAPEntity,
    RDAPResponse,
    normalize_query,
)

log = logging.getLogger(__name__)

MAX_NAMESERVERS = 3
MAX_EMBED_TITLE_LENGTH = 256
MAX_TABLE_LENGTH = 3_900
MAX_VALUE_LENGTH = 500
RDAP_REQUEST_ATTEMPTS = 2
RDAP_REQUEST_TIMEOUT_SECONDS = 15
RDAP_MEDIA_TYPE = "application/rdap+json"
RDAP_HEADERS = {
    "Accept": RDAP_MEDIA_TYPE,
    "User-Agent": "VipyrSec-Bot/5.0 (+https://github.com/vipyrsec/bot)",
}


class RDAP(commands.Cog):
    """RDAP lookup commands."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="rdap",
        description="Look up registration data for a domain, IP address, or ASN",
    )
    @app_commands.describe(query="Domain, IP address, or ASN to look up")
    async def rdap_command(self, interaction: discord.Interaction[Bot], query: str) -> None:
        """
        Perform an RDAP lookup for a domain, IP address, or ASN.

        Usage:
        /rdap query:example.com
        /rdap query:1.1.1.1
        /rdap query:AS13335
        """
        await interaction.response.defer(thinking=True)

        try:
            query_type, normalized_query = normalize_query(query)
        except InvalidRDAPQuery as error:
            await interaction.followup.send(f"❌ {error}")
            return

        try:
            data = await fetch_rdap_data(
                self.bot.http_session,
                base_url=BaseURLs.rdap,
                query_type=query_type,
                query=normalized_query,
            )
            related_data = (
                await fetch_related_domain_data(self.bot.http_session, data) if query_type == "domain" else None
            )
            result_data = build_result_data(query_type, data, related_data=related_data)
            table = format_table(result_data)
        except RDAPNotFoundError:
            await interaction.followup.send(f"❌ No results found for `{normalized_query}`.")
            return
        except TimeoutError:
            log.exception("RDAP lookup timed out for %s", normalized_query)
            await interaction.followup.send("❌ The RDAP service timed out. Please try again.")
            return
        except (aiohttp.ClientError, RDAPResponseError, ValidationError):
            log.exception("RDAP lookup failed for %s", normalized_query)
            await interaction.followup.send("❌ The RDAP service returned an invalid response. Please try again later.")
            return

        title = f"RDAP Lookup: {normalized_query}"
        if len(title) > MAX_EMBED_TITLE_LENGTH:
            title = f"{title[: MAX_EMBED_TITLE_LENGTH - 1]}…"

        embed = Embed(
            title=title,
            description=table,
            colour=Colours.blue,
        )
        await interaction.followup.send(embed=embed)


class RDAPResponseError(RuntimeError):
    """Raised when an RDAP server returns an unusable response."""


class RDAPNotFoundError(RDAPResponseError):
    """Raised when an RDAP server has no result for a query."""


async def fetch_rdap_data(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    query_type: QueryType,
    query: str,
) -> dict[str, Any]:
    """Fetch and validate an RDAP JSON object, retrying one transient timeout."""
    url = f"{base_url.rstrip('/')}/{query_type}/{quote(query, safe='')}"
    for attempt in range(1, RDAP_REQUEST_ATTEMPTS + 1):
        try:
            return await _fetch_rdap_data_once(session, url)
        except TimeoutError:
            if attempt == RDAP_REQUEST_ATTEMPTS:
                raise
            log.warning("RDAP request timed out; retrying %s", url)

    message = "RDAP request exhausted its attempts"
    raise AssertionError(message)


async def _fetch_rdap_data_once(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    """Perform one bounded RDAP request."""
    timeout = aiohttp.ClientTimeout(total=RDAP_REQUEST_TIMEOUT_SECONDS)
    async with session.get(url, headers=RDAP_HEADERS, timeout=timeout) as response:
        if response.status == HTTPStatus.NOT_FOUND:
            raise RDAPNotFoundError
        if response.status != HTTPStatus.OK:
            message = f"RDAP server returned HTTP {response.status}"
            raise RDAPResponseError(message)
        try:
            data: object = await response.json()
        except (aiohttp.ContentTypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
            message = "RDAP server returned invalid JSON"
            raise RDAPResponseError(message) from error

    if not isinstance(data, dict):
        message = "RDAP server did not return a JSON object"
        raise RDAPResponseError(message)
    return cast("dict[str, Any]", data)


async def fetch_related_domain_data(
    session: aiohttp.ClientSession,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """Fetch the first safe related RDAP link from a domain response."""
    raw_links: object = data.get("links")
    if not isinstance(raw_links, list):
        return None

    for raw_link in cast("list[object]", raw_links):
        if not isinstance(raw_link, dict):
            continue
        link = cast("dict[str, object]", raw_link)
        if link.get("rel") != "related" or link.get("type") != RDAP_MEDIA_TYPE:
            continue

        related_url = link.get("href")
        if not isinstance(related_url, str) or not await is_safe_related_url(related_url):
            log.warning("Ignoring unsafe related RDAP URL: %r", related_url)
            continue

        try:
            timeout = aiohttp.ClientTimeout(total=RDAP_REQUEST_TIMEOUT_SECONDS)
            async with session.get(
                related_url,
                headers=RDAP_HEADERS,
                allow_redirects=False,
                timeout=timeout,
            ) as response:
                if response.status != HTTPStatus.OK:
                    log.warning("Related RDAP lookup returned HTTP %s", response.status)
                    return None
                related_data: object = await response.json()
        except (TimeoutError, aiohttp.ClientError, json.JSONDecodeError, UnicodeDecodeError):
            log.warning("Ignoring unavailable related RDAP response from %s", related_url, exc_info=True)
            return None

        if not isinstance(related_data, dict):
            log.warning("Ignoring non-object related RDAP response from %s", related_url)
            return None
        return cast("dict[str, Any]", related_data)

    return None


async def is_safe_related_url(url: str) -> bool:
    """Allow only credential-free HTTPS URLs that resolve to public addresses."""
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in {None, 443}:
        return False
    if parsed.hostname is None or "." not in parsed.hostname:
        return False

    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.endswith((".internal", ".local", ".localhost")):
            return False
        return await hostname_resolves_globally(parsed.hostname)
    return address.is_global


async def hostname_resolves_globally(hostname: str) -> bool:
    """Reject hostnames with any non-global address before making an outbound request."""
    try:
        address_info = await asyncio.get_running_loop().getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return False

    addresses = {entry[4][0] for entry in address_info}
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def build_result_data(
    query_type: QueryType,
    data: dict[str, Any],
    *,
    related_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse RDAP response data into the fields displayed by the command."""
    if query_type == "domain":
        models = [RDAPDomain.model_validate(data)]
        if related_data is not None:
            try:
                related_model = RDAPDomain.model_validate(related_data)
            except ValidationError:
                log.warning("Ignoring schema-invalid related RDAP response", exc_info=True)
            else:
                models.insert(0, related_model)
        return _build_domain_result(models)
    if query_type == "ip":
        return _build_ip_result(RDAPIP.model_validate(data))
    return _build_asn_result(RDAPASN.model_validate(data))


def _build_domain_result(models: list[RDAPDomain]) -> dict[str, Any]:
    """Combine primary and related domain data, preferring related details."""
    iana_id = None
    for registrar in _entities_by_role(models, "registrar"):
        for public_id in registrar.public_ids:
            public_id_type = public_id.get("type")
            if isinstance(public_id_type, str) and "IANA" in public_id_type.upper():
                iana_id = public_id.get("identifier")
                break
        if iana_id is not None:
            break

    nameservers: list[dict[str, Any]] = next(
        (model.nameservers for model in models if model.nameservers),
        list[dict[str, Any]](),
    )
    nameserver_names = [str(nameserver["ldhName"]) for nameserver in nameservers if nameserver.get("ldhName")]

    return {
        "Domain": next((model.ldh_name for model in models if model.ldh_name), None),
        "Registrar": _first_contact(models, ("registrar",), "name"),
        "Registrar IANA ID": iana_id,
        "Registration": next((date for model in models if (date := model.event_date("registration"))), None),
        "Expiration": next((date for model in models if (date := model.event_date("expiration"))), None),
        "Registrant": _first_contact(models, ("registrant",), "name"),
        "Abuse": _first_contact(models, ("abuse",), "email"),
        "Nameservers": _summarize_nameservers(nameserver_names),
    }


def _build_ip_result(model: RDAPIP) -> dict[str, Any]:
    """Build display fields for an IP network response."""
    models = (model,)
    address_range = (
        f"{model.start_address} - {model.end_address}"
        if model.start_address is not None and model.end_address is not None
        else None
    )
    return {
        "Range": address_range,
        "Network": model.name,
        "CIDR": ", ".join(model.cidrs) or None,
        "Parent": model.parent_handle,
        "Registrant": _first_contact(models, ("registrant",), "name"),
        "Contact": _first_contact(
            models,
            ("registrant", "administrative", "technical", "abuse"),
            "email",
        ),
    }


def _build_asn_result(model: RDAPASN) -> dict[str, Any]:
    """Build display fields for an ASN response."""
    models = (model,)
    asn_range = None
    if model.start_autnum is not None and model.end_autnum is not None:
        asn_range = (
            str(model.start_autnum)
            if model.start_autnum == model.end_autnum
            else f"{model.start_autnum} - {model.end_autnum}"
        )
    return {
        "ASN": asn_range,
        "Name": model.name,
        "Registrant": _first_contact(models, ("registrant",), "name"),
        "Abuse": _first_contact(models, ("abuse",), "email"),
    }


def _entities_by_role(models: Sequence[RDAPResponse], role: str) -> Iterator[RDAPEntity]:
    """Yield matching entities across multiple responses in preference order."""
    for model in models:
        for entity in model.entities:
            for candidate in entity.walk():
                if role in candidate.roles:
                    yield candidate


def _first_contact(
    models: Sequence[RDAPResponse],
    roles: Sequence[str],
    field: str,
) -> str | None:
    """Find the first populated contact field for the preferred roles."""
    for role in roles:
        for entity in _entities_by_role(models, role):
            value = entity.contact_info.get(field)
            if value:
                return value
    return None


def _summarize_nameservers(nameservers: list[str]) -> str | None:
    """Limit the nameserver list to a concise Discord-friendly value."""
    if not nameservers:
        return None
    suffix = "…" if len(nameservers) > MAX_NAMESERVERS else ""
    return ", ".join(nameservers[:MAX_NAMESERVERS]) + suffix


def format_table(data: dict[str, Any]) -> str:
    """Format populated values as a bounded Markdown code-block table."""
    clean_data = {
        key: _sanitize_table_value(value) for key, value in data.items() if value is not None and str(value).strip()
    }
    if not clean_data:
        return "No data available."

    max_key_len = max(len("Property"), *(map(len, clean_data)))
    lines = [
        f"{'Property':<{max_key_len}} | Value",
        f"{'-' * max_key_len}-|{'-' * 25}",
        *(f"{key:<{max_key_len}} | {value}" for key, value in clean_data.items()),
    ]
    table = "```\n" + "\n".join(lines) + "\n```"
    if len(table) > MAX_TABLE_LENGTH:
        message = "Formatted RDAP response exceeds Discord's embed limit"
        raise RDAPResponseError(message)
    return table


def _sanitize_table_value(value: object) -> str:
    """Prevent external RDAP text from breaking the table's code block."""
    sanitized = " ".join(str(value).replace("`", "'").splitlines())
    if len(sanitized) > MAX_VALUE_LENGTH:
        return sanitized[: MAX_VALUE_LENGTH - 1] + "…"
    return sanitized


async def setup(bot: Bot) -> None:
    """Load the RDAP cog."""
    await bot.add_cog(RDAP(bot))
