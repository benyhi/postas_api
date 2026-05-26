from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmailRequest:
    subject: str
    text_body: str
    from_email: str
    to: list[str]
    html_body: str = ""
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderSendResult:
    sent: int
    external_id: str = ""
    response: dict[str, Any] = field(default_factory=dict)


class BaseEmailProvider:
    name = ""

    def send(self, email_request: EmailRequest) -> ProviderSendResult:
        raise NotImplementedError
