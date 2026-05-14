from typing import Protocol, TypedDict


class GmailMessageMetadata(TypedDict):
    id: str
    threadId: str
    internalDate: str  # ms-since-epoch as string per Gmail API
    sizeEstimate: int
    labelIds: list[str]
    payload: dict  # {"headers": [{"name": str, "value": str}, ...]}


class HistoryEvent(TypedDict, total=False):
    type: str  # 'messageAdded' | 'messageDeleted' | 'labelAdded' | 'labelRemoved'
    message_id: str
    label_ids: list[str]


class GmailClient(Protocol):
    async def get_profile(self) -> dict:
        """Returns {'emailAddress': str, 'historyId': str}."""
        ...

    async def list_message_ids(self, query: str) -> list[str]:
        """Returns all message ids matching `query`, fully paginated."""
        ...

    async def batch_get_metadata(
        self, message_ids: list[str], metadata_headers: list[str]
    ) -> list[GmailMessageMetadata]:
        """Fetch metadata for up to 100 message ids per call. Caller chunks."""
        ...

    async def history_since(
        self, start_history_id: str
    ) -> tuple[list[HistoryEvent], str | None]:
        """Returns (events, new_history_id). new_history_id None if start was unrecoverable."""
        ...

    async def trash(self, message_id: str) -> None: ...

    async def batch_modify(
        self, message_ids: list[str], add_labels: list[str], remove_labels: list[str]
    ) -> None: ...

    async def get_or_create_label(self, name: str) -> str:
        """Returns label id."""
        ...

    async def send_unsubscribe_mailto(self, to: str, subject: str | None) -> None: ...
