"""Microsoft auth integration"""

from os import getenv

from azure.identity import ClientSecretCredential
from msgraph.core import GraphClient


def build_ms_graph_client() -> GraphClient:
    """Build authenticated GraphClient"""
    client_secret_credential = ClientSecretCredential(
        tenant_id=getenv("BOT_MICROSOFT_TENANT_ID"),
        client_id=getenv("BOT_MICROSOFT_CLIENT_ID"),
        client_secret=getenv("BOT_MICROSOFT_CLIENT_SECRET"),
    )
    return GraphClient(credential=client_secret_credential)
