"""Tests for RDAP query validation and response rendering."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from discord.ext import commands

from bot.bot import Bot
from bot.exts import rdap
from bot.utils.rdap import RDAPASN, RDAPIP, InvalidRDAPQuery, RDAPDomain, normalize_query


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("1.1.1.1", ("ip", "1.1.1.1")),
        ("2001:4860:4860::8888", ("ip", "2001:4860:4860::8888")),
        ("AS13335", ("autnum", "13335")),
        ("as00042", ("autnum", "42")),
        ("EXAMPLE.COM.", ("domain", "example.com")),
        ("bücher.example", ("domain", "xn--bcher-kva.example")),
    ],
)
def test_normalize_query(query: str, expected: tuple[str, str]) -> None:
    """Queries must be validated and normalized for the rdap.org path."""
    assert normalize_query(query) == expected


@pytest.mark.parametrize("query", ["", "AS4294967296", "bad domain", "-example.com", "example..com"])
def test_normalize_query_rejects_invalid_input(query: str) -> None:
    """Invalid input must not be interpolated into an outbound URL."""
    with pytest.raises(InvalidRDAPQuery):
        normalize_query(query)


def test_rdap_models_read_protocol_field_names_and_nested_entities() -> None:
    """Snake-case Python fields must populate from RFC-defined JSON names."""
    domain = RDAPDomain.model_validate(
        {
            "ldhName": "EXAMPLE.COM",
            "entities": [
                {
                    "roles": ["registrar"],
                    "publicIds": [{"type": "IANA Registrar ID", "identifier": "376"}],
                    "entities": [
                        {
                            "roles": ["abuse"],
                            "vcardArray": [
                                "vcard",
                                [["email", {}, "text", "abuse@example.test"]],
                            ],
                        }
                    ],
                }
            ],
        }
    )

    assert domain.ldh_name == "EXAMPLE.COM"
    assert domain.entities[0].public_ids[0]["identifier"] == "376"
    abuse = domain.get_entity_by_role("abuse")
    assert abuse is not None
    assert abuse.contact_info["email"] == "abuse@example.test"


def test_domain_result_combines_registry_and_registrar_responses() -> None:
    """Related registrar data must supplement, rather than replace, registry data."""
    primary: dict[str, Any] = {
        "ldhName": "EXAMPLE.COM",
        "events": [
            {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"},
            {"eventAction": "expiration", "eventDate": "2027-08-13T04:00:00Z"},
        ],
        "nameservers": [{"ldhName": "A.IANA-SERVERS.NET"}],
        "entities": [
            {
                "roles": ["abuse"],
                "vcardArray": ["vcard", [["email", {}, "text", "abuse@example.test"]]],
            }
        ],
    }
    related: dict[str, Any] = {
        "ldhName": "EXAMPLE.COM",
        "entities": [
            {
                "roles": ["registrant"],
                "vcardArray": ["vcard", [["fn", {}, "text", "Example Registrant"]]],
            },
            {
                "roles": ["abuse"],
                "vcardArray": ["vcard", [["fn", {}, "text", "Registrar without an abuse email"]]],
            },
        ],
    }

    result = rdap.build_result_data("domain", primary, related_data=related)

    assert result["Registration"] == "1995-08-14T04:00:00Z"
    assert result["Expiration"] == "2027-08-13T04:00:00Z"
    assert result["Registrant"] == "Example Registrant"
    assert result["Abuse"] == "abuse@example.test"
    assert result["Nameservers"] == "A.IANA-SERVERS.NET"


def test_ip_and_asn_models_render_rfc_fields() -> None:
    """IP and ASN aliases must produce useful output rather than None placeholders."""
    ip_model = RDAPIP.model_validate(
        {
            "startAddress": "1.1.1.0",
            "endAddress": "1.1.1.255",
            "cidr0_cidrs": [{"v4prefix": "1.1.1.0", "length": 24}],
        }
    )
    asn_data = {"startAutnum": 13335, "endAutnum": 13335}
    asn_model = RDAPASN.model_validate(asn_data)

    assert ip_model.start_address == "1.1.1.0"
    assert ip_model.cidrs == ["1.1.1.0/24"]
    assert asn_model.start_autnum == 13335
    assert rdap.build_result_data("autnum", asn_data)["ASN"] == "13335"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://rdap.example.com/domain/example.com", True),
        ("http://rdap.example.com/domain/example.com", False),
        ("https://user:password@rdap.example.com/domain/example.com", False),
        ("https://127.0.0.1/domain/example.com", False),
        ("https://rdap.local/domain/example.com", False),
    ],
)
def test_related_url_safety(url: str, expected: object) -> None:
    """Related lookups must reject obvious SSRF targets."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(rdap, "hostname_resolves_globally", AsyncMock(return_value=True))
        assert asyncio.run(rdap.is_safe_related_url(url)) is expected


def test_format_table_contains_external_text_safely() -> None:
    """External response text must not break out of the Markdown code block."""
    table = rdap.format_table({"Registrant": "line one\n```injected```"})

    assert table.count("```") == 2
    assert "line one '''injected'''" in table


def test_rdap_command_handles_request_timeout() -> None:
    """An upstream timeout must produce the RDAP-specific error response."""
    with patch.object(rdap, "fetch_rdap_data", AsyncMock(side_effect=TimeoutError)):
        ctx_mock = _invoke_rdap_command()

    ctx_mock.send.assert_awaited_once_with("❌ The RDAP service returned an invalid response. Please try again later.")


def test_rdap_command_handles_table_overflow() -> None:
    """Oversized valid output must produce the RDAP-specific error response."""
    oversized_result = {f"Field {index}": "x" * rdap.MAX_VALUE_LENGTH for index in range(8)}
    with (
        patch.object(rdap, "fetch_rdap_data", AsyncMock(return_value={})),
        patch.object(rdap, "fetch_related_domain_data", AsyncMock(return_value=None)),
        patch.object(rdap, "build_result_data", return_value=oversized_result),
    ):
        ctx_mock = _invoke_rdap_command()

    ctx_mock.send.assert_awaited_once_with("❌ The RDAP service returned an invalid response. Please try again later.")


def test_rdap_command_bounds_long_domain_title() -> None:
    """A valid maximum-length domain must fit Discord's embed title limit."""
    query = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 61))
    with (
        patch.object(rdap, "fetch_rdap_data", AsyncMock(return_value={})),
        patch.object(rdap, "fetch_related_domain_data", AsyncMock(return_value=None)),
        patch.object(rdap, "build_result_data", return_value={"Domain": query}),
    ):
        ctx_mock = _invoke_rdap_command(query)

    embed = ctx_mock.send.await_args.kwargs["embed"]
    assert len(embed.title) == rdap.MAX_EMBED_TITLE_LENGTH
    assert embed.title.endswith("…")


def _invoke_rdap_command(query: str = "example.com") -> Mock:
    """Invoke the decorated command callback with typed mocks."""
    bot = cast("Bot", Mock())
    ctx_mock = Mock()
    ctx_mock.send = AsyncMock()
    ctx = cast("commands.Context[Bot]", ctx_mock)
    cog = rdap.RDAP(bot)
    command = cast("commands.Command[Any, ..., Any]", rdap.RDAP.rdap_command)

    asyncio.run(command.callback(cog, ctx, query=query))
    return ctx_mock
