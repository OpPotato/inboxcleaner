import re
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Literal
from urllib.parse import parse_qs

import tldextract

_extract = tldextract.TLDExtract(suffix_list_urls=())  # avoid network at runtime


@dataclass(frozen=True)
class UnsubscribeAction:
    kind: Literal["mailto", "http"]
    target: str
    subject: str | None = None


def parse_from_header(raw: str) -> tuple[str, str | None]:
    name, email = parseaddr(raw)
    email = email.lower()
    name = name.strip() or None
    return email, name


def registered_domain(email: str) -> str:
    _, _, host = email.partition("@")
    result = _extract(host)
    if not result.domain or not result.suffix:
        return host
    return f"{result.domain}.{result.suffix}"


_TOKEN_RE = re.compile(r"<([^>]+)>")


def parse_list_unsubscribe(raw: str | None) -> list[UnsubscribeAction]:
    if not raw:
        return []
    actions: list[UnsubscribeAction] = []
    for match in _TOKEN_RE.findall(raw):
        target = match.strip()
        if target.lower().startswith("mailto:"):
            url = target[len("mailto:"):]
            addr, _, query = url.partition("?")
            subject = None
            if query:
                params = parse_qs(query)
                subject = params.get("subject", [None])[0]
            actions.append(UnsubscribeAction(kind="mailto", target=addr, subject=subject))
        elif target.lower().startswith(("http://", "https://")):
            actions.append(UnsubscribeAction(kind="http", target=target))
    return actions
