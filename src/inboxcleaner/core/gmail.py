import asyncio
from pathlib import Path
from typing import Protocol, TypedDict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


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


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def load_or_run_oauth(client_secret_path: Path, token_path: Path) -> Credentials:
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)
    return creds


class RealGmailClient:
    def __init__(self, creds: Credentials) -> None:
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def get_profile(self) -> dict:
        def go():
            return self._service.users().getProfile(userId="me").execute()

        return await self._run(go)

    async def list_message_ids(self, query: str) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        while True:

            def go(tok=page_token):
                req = self._service.users().messages().list(
                    userId="me", q=query, pageToken=tok, maxResults=500
                )
                return req.execute()

            resp = await self._run(go)
            for m in resp.get("messages", []):
                ids.append(m["id"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    async def batch_get_metadata(
        self, message_ids: list[str], metadata_headers: list[str]
    ) -> list[GmailMessageMetadata]:
        # google-api-python-client supports BatchHttpRequest, but it's awkward to
        # use cleanly. For v1 we make parallel single calls via to_thread; the
        # ratelimit module enforces the safe rate.
        async def fetch_one(mid: str) -> GmailMessageMetadata:
            def go():
                return (
                    self._service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="METADATA",
                        metadataHeaders=metadata_headers,
                    )
                    .execute()
                )

            return await self._run(go)

        results = await asyncio.gather(*(fetch_one(mid) for mid in message_ids))
        return list(results)

    async def history_since(
        self, start_history_id: str
    ) -> tuple[list[HistoryEvent], str | None]:
        events: list[HistoryEvent] = []
        page_token: str | None = None
        new_history_id: str | None = None
        while True:

            def go(tok=page_token):
                return (
                    self._service.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=start_history_id,
                        pageToken=tok,
                    )
                    .execute()
                )

            try:
                resp = await self._run(go)
            except Exception as e:
                if "404" in str(e) or "startHistoryId" in str(e):
                    return [], None
                raise
            new_history_id = resp.get("historyId", new_history_id)
            for h in resp.get("history", []):
                for kind in ("messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"):
                    for item in h.get(kind, []):
                        msg = item.get("message", {})
                        events.append(
                            HistoryEvent(
                                type=_history_type(kind),
                                message_id=msg.get("id", ""),
                                label_ids=list(item.get("labelIds", [])),
                            )
                        )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return events, new_history_id

    async def trash(self, message_id: str) -> None:
        def go():
            return self._service.users().messages().trash(userId="me", id=message_id).execute()

        await self._run(go)

    async def batch_modify(
        self, message_ids: list[str], add_labels: list[str], remove_labels: list[str]
    ) -> None:
        # Gmail allows up to 1000 ids per batchModify call.
        for i in range(0, len(message_ids), 1000):
            chunk = message_ids[i : i + 1000]

            def go(ids=chunk):
                return (
                    self._service.users()
                    .messages()
                    .batchModify(
                        userId="me",
                        body={
                            "ids": ids,
                            "addLabelIds": add_labels,
                            "removeLabelIds": remove_labels,
                        },
                    )
                    .execute()
                )

            await self._run(go)

    async def get_or_create_label(self, name: str) -> str:
        def list_labels():
            return self._service.users().labels().list(userId="me").execute()

        resp = await self._run(list_labels)
        for lbl in resp.get("labels", []):
            if lbl["name"] == name:
                return lbl["id"]

        def create():
            return (
                self._service.users()
                .labels()
                .create(userId="me", body={"name": name})
                .execute()
            )

        created = await self._run(create)
        return created["id"]

    async def send_unsubscribe_mailto(self, to: str, subject: str | None) -> None:
        # v1: requires gmail.send scope which we don't request by default.
        # Surface to caller; actions.unsubscribe will record it as 'skipped'.
        raise NotImplementedError(
            "mailto unsubscribe disabled (requires gmail.send scope; re-run "
            "`inboxcleaner login --include-send` in a future version)"
        )


def _history_type(api_key: str) -> str:
    return {
        "messagesAdded": "messageAdded",
        "messagesDeleted": "messageDeleted",
        "labelsAdded": "labelAdded",
        "labelsRemoved": "labelRemoved",
    }[api_key]
