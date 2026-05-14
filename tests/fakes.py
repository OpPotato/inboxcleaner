from typing import Any

from inboxcleaner.core.gmail import GmailClient, GmailMessageMetadata, HistoryEvent


class FakeGmailClient:
    """In-memory Gmail client for tests."""

    def __init__(
        self,
        *,
        email: str = "me@example.com",
        history_id: str = "1",
        messages: dict[str, GmailMessageMetadata] | None = None,
        query_ids: dict[str, list[str]] | None = None,
        history: list[HistoryEvent] | None = None,
    ) -> None:
        self.email = email
        self.history_id = history_id
        self.messages = messages or {}
        self.query_ids = query_ids or {}
        self.history = history or []
        self.labels: dict[str, str] = {}  # name -> id
        self.next_label_id = 1
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _log(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))

    async def get_profile(self) -> dict:
        self._log("get_profile")
        return {"emailAddress": self.email, "historyId": self.history_id}

    async def list_message_ids(self, query: str) -> list[str]:
        self._log("list_message_ids", query=query)
        return list(self.query_ids.get(query, []))

    async def batch_get_metadata(
        self, message_ids: list[str], metadata_headers: list[str]
    ) -> list[GmailMessageMetadata]:
        self._log("batch_get_metadata", ids=message_ids, headers=metadata_headers)
        return [self.messages[mid] for mid in message_ids if mid in self.messages]

    async def history_since(
        self, start_history_id: str
    ) -> tuple[list[HistoryEvent], str | None]:
        self._log("history_since", start=start_history_id)
        return list(self.history), self.history_id

    async def trash(self, message_id: str) -> None:
        self._log("trash", id=message_id)
        if message_id in self.messages:
            md = self.messages[message_id]
            self.messages[message_id] = {**md, "labelIds": list(set(md["labelIds"] + ["TRASH"]))}

    async def batch_modify(
        self, message_ids: list[str], add_labels: list[str], remove_labels: list[str]
    ) -> None:
        self._log(
            "batch_modify",
            ids=message_ids,
            add=add_labels,
            remove=remove_labels,
        )
        for mid in message_ids:
            if mid not in self.messages:
                continue
            labels = set(self.messages[mid]["labelIds"])
            labels = (labels | set(add_labels)) - set(remove_labels)
            self.messages[mid] = {**self.messages[mid], "labelIds": list(labels)}

    async def get_or_create_label(self, name: str) -> str:
        self._log("get_or_create_label", name=name)
        if name not in self.labels:
            self.labels[name] = f"Label_{self.next_label_id}"
            self.next_label_id += 1
        return self.labels[name]

    async def send_unsubscribe_mailto(self, to: str, subject: str | None) -> None:
        self._log("send_unsubscribe_mailto", to=to, subject=subject)


def _from_header(value: str) -> dict:
    return {"name": "From", "value": value}


def make_metadata(
    *,
    msg_id: str,
    from_: str,
    thread_id: str | None = None,
    subject: str = "",
    internal_date: int = 1_700_000_000_000,
    size: int = 4096,
    labels: list[str] | None = None,
    list_unsubscribe: str | None = None,
) -> GmailMessageMetadata:
    headers = [_from_header(from_), {"name": "Subject", "value": subject}]
    if list_unsubscribe:
        headers.append({"name": "List-Unsubscribe", "value": list_unsubscribe})
    return GmailMessageMetadata(
        id=msg_id,
        threadId=thread_id or f"t{msg_id}",
        internalDate=str(internal_date),
        sizeEstimate=size,
        labelIds=labels or ["CATEGORY_PROMOTIONS"],
        payload={"headers": headers},
    )


# Satisfy the Protocol at import time (structural check only)
_: GmailClient = FakeGmailClient()  # type: ignore[assignment]
