"""Utilities for sending emails."""

import string
import textwrap

from azure.identity import ClientSecretCredential
from msgraph import GraphServiceClient
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.message import Message
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import SendMailPostRequestBody

from bot.constants import MailerConfig, MicrosoftConfig
from bot.utils.pypi import file_path_from_inspector_url

credentials = ClientSecretCredential(
    tenant_id=MicrosoftConfig.tenant_id,
    client_id=MicrosoftConfig.client_id,
    client_secret=MicrosoftConfig.client_secret,
)

scopes = ["https://graph.microsoft.com/.default"]

client = GraphServiceClient(credentials=credentials, scopes=scopes)

TEMPLATE = string.Template(
    textwrap.dedent("""
    PyPI Malicious Package Report
    -
    Package Name: ${package_name}
    Version: ${package_version}
    File path: ${file_path}
    Inspector URL: ${inspector_url}
    Additional Information: ${additional_information}
    Yara rules matched: {rules_matched}
"""),
)


def build_report_mail_body(
    package_name: str,
    package_version: str,
    inspector_url: str,
    additional_information: str,
    rules_matched: str,
) -> str:
    """Build the email body for a package report."""
    return TEMPLATE.substitute({
        "package_name": package_name,
        "package_version": package_version,
        "inspector_url": inspector_url,
        "file_path": file_path_from_inspector_url(inspector_url),
        "rules_matched": rules_matched,
        "additional_information": additional_information,
    })


async def send_email(
    *,
    recipient_adresses: list[str],
    bcc_recipient_addresses: list[str] | None = None,
    subject: str,
    content: str,
) -> None:
    """Send an email using Microsoft Graph SDK."""
    if bcc_recipient_addresses is None:
        bcc_recipient_addresses = []
    sender = EmailAddress(address=MailerConfig.sender)
    from_recipient = Recipient(email_address=sender)
    to_recipients = [Recipient(email_address=EmailAddress(address=address)) for address in recipient_adresses]
    bcc_recipients = [Recipient(email_address=EmailAddress(address=address)) for address in bcc_recipient_addresses]
    email_body = ItemBody(content=content, content_type=BodyType.Text)
    message = Message(
        subject=subject,
        to_recipients=to_recipients,
        bcc_recipients=bcc_recipients,
        body=email_body,
        from_=from_recipient,
    )
    request_body = SendMailPostRequestBody(message=message)
    await client.users.by_user_id(MailerConfig.sender).send_mail.post(request_body)
