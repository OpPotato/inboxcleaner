import logging
import os
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from inboxcleaner.core import repo
from inboxcleaner.core.gmail import GmailClient, GmailMessageMetadata
from inboxcleaner.core.grouping import (
    ExistingGroup,
    GroupIndex,
    assign_group,
)
from inboxcleaner.core.models import Account, Message, Sender
from inboxcleaner.core.parsing import parse_from_header, registered_domain

logger = logging.getLogger(__name__)


DEFAULT_QUERY = "category:promotions OR category:social OR category:updates"

_METADATA_HEADERS = ["From", "Subject", "List-Unsubscribe", "Date"]
_BATCH_SIZE = 100


@dataclass(frozen=True)
class SyncResult:
    message_count: int      # number of new/changed messages applied
    history_id: str | None


ProgressFn = Callable[[int, int], None]


def _noop(done: int, total: int) -> None:
    return None


async def initial_sync(
    client: GmailClient,
    conn: sqlite3.Connection,
    *,
    account_email: str,
    query: str = DEFAULT_QUERY,
    progress: ProgressFn = _noop,
) -> SyncResult:
    if not repo.acquire_sync_lock(conn, os.getpid()):
        raise RuntimeError("Another sync is already in progress.")
    try:
        profile = await client.get_profile()
        head_history = profile["historyId"]
        account = repo.upsert_account(conn, Account(email=account_email))
        ids = await client.list_message_ids(query)
        progress(0, len(ids))
        sender_rows = conn.execute("SELECT * FROM sender").fetchall()
        existing_senders = [Sender(**dict(r)) for r in sender_rows]
        group_index = GroupIndex(groups=repo.all_groups(conn), senders=existing_senders)
        applied = 0
        for chunk_start in range(0, len(ids), _BATCH_SIZE):
            chunk = ids[chunk_start : chunk_start + _BATCH_SIZE]
            metas = await client.batch_get_metadata(chunk, _METADATA_HEADERS)
            for meta in metas:
                if _apply_message_metadata(conn, account.id, meta, group_index):
                    applied += 1
                progress(applied, len(ids))
        repo.upsert_account(
            conn,
            Account(id=account.id, email=account.email, history_id=head_history),
        )
        return SyncResult(message_count=applied, history_id=head_history)
    finally:
        repo.release_sync_lock(conn)


async def incremental_sync(
    client: GmailClient,
    conn: sqlite3.Connection,
    *,
    account_id: int,
    progress: ProgressFn = _noop,
) -> SyncResult:
    if not repo.acquire_sync_lock(conn, os.getpid()):
        raise RuntimeError("Another sync is already in progress.")
    try:
        row = conn.execute(
            "SELECT email, history_id FROM account WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No account with id={account_id}")
        if row["history_id"] is None:
            return await _do_initial(client, conn, row["email"], progress)

        events, new_history_id = await client.history_since(row["history_id"])
        if new_history_id is None:
            # Stale — fall back to full re-list
            return await _do_initial(client, conn, row["email"], progress)

        sender_rows = conn.execute("SELECT * FROM sender").fetchall()
        existing_senders = [Sender(**dict(r)) for r in sender_rows]
        group_index = GroupIndex(groups=repo.all_groups(conn), senders=existing_senders)
        applied = 0
        # Fetch metadata for new messages in batch
        new_ids = [e["message_id"] for e in events if e["type"] == "messageAdded"]
        if new_ids:
            for chunk_start in range(0, len(new_ids), _BATCH_SIZE):
                chunk = new_ids[chunk_start : chunk_start + _BATCH_SIZE]
                metas = await client.batch_get_metadata(chunk, _METADATA_HEADERS)
                for meta in metas:
                    if _apply_message_metadata(conn, account_id, meta, group_index):
                        applied += 1
                    progress(applied, len(new_ids))

        for event in events:
            etype = event["type"]
            mid = event["message_id"]
            if etype == "messageDeleted":
                repo.delete_message(conn, mid)
            elif etype == "labelAdded" and "TRASH" in event.get("label_ids", []):
                repo.set_message_trashed(conn, mid, True)
            elif etype == "labelRemoved" and "TRASH" in event.get("label_ids", []):
                repo.set_message_trashed(conn, mid, False)
            # Other label changes (non-TRASH) are ignored at v1 granularity.

        conn.execute(
            "UPDATE account SET history_id = ?, last_sync_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_history_id, account_id),
        )
        return SyncResult(message_count=applied, history_id=new_history_id)
    finally:
        repo.release_sync_lock(conn)


async def _do_initial(
    client: GmailClient,
    conn: sqlite3.Connection,
    email: str,
    progress: ProgressFn,
) -> SyncResult:
    repo.release_sync_lock(conn)  # initial_sync re-acquires
    return await initial_sync(
        client, conn, account_email=email, progress=progress
    )


def _apply_message_metadata(
    conn: sqlite3.Connection,
    account_id: int,
    meta: GmailMessageMetadata,
    index: GroupIndex,
) -> bool:
    """Apply one Gmail message metadata to the DB.

    Mutates `index` in-place: appends the newly-seen sender (and possibly
    a new group). Returns True iff a message row was written.
    """
    headers = {h["name"].lower(): h["value"] for h in meta["payload"].get("headers", [])}
    from_raw = headers.get("from", "")
    email, display_name = parse_from_header(from_raw)
    if not email:
        logger.warning("Skipping message %s: unparseable From header %r", meta.get("id"), from_raw)
        return False
    domain = registered_domain(email)

    candidate = Sender(email=email, display_name=display_name, domain=domain)
    decision = assign_group(candidate, index)
    if isinstance(decision, ExistingGroup):
        group_id = decision.group_id
    else:
        new_group = repo.create_group(conn, name=decision.name, created_by="auto")
        group_id = new_group.id
        # Track the new group in our local snapshot for subsequent decisions.
        index.groups.append(new_group)

    sender = repo.upsert_sender(
        conn,
        Sender(email=email, display_name=display_name, domain=domain, group_id=group_id),
    )
    # Track this sender (with id) in the snapshot so future messages can
    # match by domain/display_name.
    index.senders.append(sender)

    category = _category_from_labels(meta["labelIds"])
    msg = Message(
        id=meta["id"],
        account_id=account_id,
        thread_id=meta["threadId"],
        sender_id=sender.id,
        subject=headers.get("subject"),
        internal_date=int(meta["internalDate"]),
        size_estimate=meta.get("sizeEstimate"),
        category=category,
        labels=list(meta["labelIds"]),
        list_unsubscribe=headers.get("list-unsubscribe"),
        is_trashed="TRASH" in meta["labelIds"],
    )
    repo.upsert_message(conn, msg)
    return True


_CATEGORY_LABELS = {
    "CATEGORY_PROMOTIONS": "promotions",
    "CATEGORY_SOCIAL": "social",
    "CATEGORY_UPDATES": "updates",
    "CATEGORY_FORUMS": "forums",
    "CATEGORY_PERSONAL": "primary",
}


def _category_from_labels(label_ids: Iterable[str]) -> str | None:
    for lbl in label_ids:
        if lbl in _CATEGORY_LABELS:
            return _CATEGORY_LABELS[lbl]
    return None
