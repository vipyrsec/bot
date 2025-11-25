import logging
from typing import Any

from discord.ext import commands
from pydantic import BaseModel, Field

from bot.bot import Bot
from bot.constants import BaseURLs
from bot.utils.rdap import classify_query, parse_rdap_vcard

log = logging.getLogger(__name__)


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
    vcardArray: list[Any] = Field(default_factory=list)

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


class RDAP(commands.Cog):
    """RDAP lookup commands."""

    def __init__(self, bot: Bot):
        self.bot = bot

    def _format_table(self, data: dict[str, Any]) -> str:
        """Format a dictionary as a markdown table."""
        if not data:
            return "No data available."

        clean_data = {k: v for k, v in data.items() if v is not None}

        if not clean_data:
            return "No data available."

        max_key_len = max(len(k) for k in clean_data)
        lines: list[str] = []

        lines.append(f"{'Property'.ljust(max_key_len)} | Value")
        lines.append(f"{'-' * max_key_len}-|{'-' * 25}")

        for key, value in clean_data.items():
            lines.append(f"{key.ljust(max_key_len)} | {value}")

        return "```\n" + "\n".join(lines) + "\n```"

    @commands.command(name="rdap")
    async def rdap_command(self, ctx: commands.Context[Bot], query: str) -> None:
        """
        Perform an RDAP lookup for a domain, IP, or ASN.

        Usage:
        !rdap example.com
        !rdap 1.1.1.1
        !rdap AS13335
        """
        query_type = classify_query(query)
        url = f"{BaseURLs.rdap}/{query_type}/{query}"

        try:
            async with self.bot.http_session.get(url) as response:
                if response.status == 404:
                    await ctx.send(f"❌ No results found for `{query}`.")
                    return
                if response.status != 200:
                    log.warning(f"RDAP lookup failed for {query}: HTTP {response.status}")
                    await ctx.send(f"❌ Error fetching RDAP data: HTTP {response.status}")
                    return

                data = await response.json()
        except Exception as e:
            log.exception(f"Error performing RDAP lookup for {query}: {e}")
            await ctx.send("❌ An error occurred while fetching RDAP data.")
            return

        # Handle "Thin" registries (e.g., .com, .net) which provide a "related" link to the full RDAP info
        if query_type == "domain":
            for link in data.get("links", []):
                if link.get("rel") == "related" and link.get("type") == "application/rdap+json":
                    related_url = link.get("href")
                    if related_url:
                        log.debug(f"Following related RDAP link: {related_url}")
                        try:
                            async with self.bot.http_session.get(related_url) as related_response:
                                if related_response.status == 200:
                                    data = await related_response.json()
                        except Exception:
                            log.warning(f"Failed to follow related RDAP link: {related_url}", exc_info=True)
                        break

        result_data: dict[str, Any] = {}
        title = f"RDAP Lookup: {query}"

        if query_type == "domain":
            model = RDAPDomain(**data)
            registrar = model.get_entity_by_role("registrar")
            registrant = model.get_entity_by_role("registrant")
            abuse = model.get_entity_by_role("abuse")  # Sometimes abuse contact is separate

            iana_id = None
            if registrar and registrar.publicIds:
                for pid in registrar.publicIds:
                    if "IANA" in pid.get("type", ""):
                        iana_id = pid.get("identifier")
                        break

            result_data = {
                "Domain Name": model.ldhName,
                "Registrar": registrar.contact_info.get("name") if registrar else None,
                "IANA ID": iana_id,
                "Registered": model.registration_date,
                "Abuse Email": abuse.contact_info.get("email") if abuse else None,
            }

            if model.nameservers:
                ns_list = [str(ns.get("ldhName")) for ns in model.nameservers if ns.get("ldhName")]
                result_data["Nameservers"] = ", ".join(ns_list[:3]) + ("..." if len(ns_list) > 3 else "")

        elif query_type == "ip":
            model = RDAPIP(**data)
            registrant = model.get_entity_by_role("registrant")

            result_data = {
                "Range": f"{model.startAddress} - {model.endAddress}",
                "NetName": model.name,
                "Parent": model.parentHandle,
                "Registrant": registrant.contact_info.get("name") if registrant else None,
                "Contact": registrant.contact_info.get("email") if registrant else None,
            }

        elif query_type == "autnum":
            model = RDAPASN(**data)
            registrant = model.get_entity_by_role("registrant")
            abuse = model.get_entity_by_role("abuse")

            result_data = {
                "ASN": f"{model.startAutnum} - {model.endAutnum}",
                "Name": model.name,
                "Registrant": registrant.contact_info.get("name") if registrant else None,
                "Abuse Email": abuse.contact_info.get("email") if abuse else None,
            }

        table = self._format_table(result_data)
        await ctx.send(f"**{title}**\n{table}")


async def setup(bot: Bot) -> None:
    await bot.add_cog(RDAP(bot))
