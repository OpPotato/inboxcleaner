import sqlite3
from dataclasses import dataclass, field

from inboxcleaner.core import repo
from inboxcleaner.core.gmail import GmailClient
from inboxcleaner.core.models import TargetKind
from inboxcleaner.core.parsing import parse_list_unsubscribe


@dataclass(frozen=True)
class SampleMessage:
    id: str
    subject: str | None
    internal_date: int


@dataclass(frozen=True)
class ActionPreview:
    target_kind: TargetKind
    target_id: int
    message_count: int
    total_size: int
    samples: list[SampleMessage]


@dataclass
class UnsubscribeResult:
    mailto_sent: int = 0
    http_urls: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _affected_message_ids(
    conn: sqlite3.Connection, target_kind: TargetKind, target_id: int
) -> list[str]:
    if target_kind == "sender":
        return repo.message_ids_for_sender(conn, target_id)
    if target_kind == "group":
        return repo.message_ids_for_group(conn, target_id)
    raise ValueError(f"unknown target_kind: {target_kind}")


def preview(
    conn: sqlite3.Connection,
    *,
    target_kind: TargetKind,
    target_id: int,
    sample_size: int = 5,
) -> ActionPreview:
    if target_kind == "sender":
        where = "WHERE sender_id = ?"
    else:
        where = (
            "WHERE sender_id IN (SELECT id FROM sender WHERE group_id = ?)"
        )
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS n, COALESCE(SUM(size_estimate), 0) AS total
        FROM message {where} AND is_trashed = 0
        """,
        (target_id,),
    ).fetchone()
    sample_rows = conn.execute(
        f"""
        SELECT id, subject, internal_date
        FROM message {where} AND is_trashed = 0
        ORDER BY internal_date DESC
        LIMIT ?
        """,
        (target_id, sample_size),
    ).fetchall()
    samples = [
        SampleMessage(id=r["id"], subject=r["subject"], internal_date=r["internal_date"])
        for r in sample_rows
    ]
    return ActionPreview(
        target_kind=target_kind,
        target_id=target_id,
        message_count=row["n"],
        total_size=row["total"],
        samples=samples,
    )


async def archive(
    client: GmailClient,
    conn: sqlite3.Connection,
    *,
    target_kind: TargetKind,
    target_id: int,
) -> int:
    ids = _affected_message_ids(conn, target_kind, target_id)
    repo.write_action_log(
        conn,
        action_type="archive",
        target_kind=target_kind,
        target_id=target_id,
        message_count=len(ids),
    )
    if not ids:
        return 0
    await client.batch_modify(ids, add_labels=[], remove_labels=["INBOX"])
    return len(ids)


async def trash(
    client: GmailClient,
    conn: sqlite3.Connection,
    *,
    target_kind: TargetKind,
    target_id: int,
) -> int:
    ids = _affected_message_ids(conn, target_kind, target_id)
    repo.write_action_log(
        conn,
        action_type="trash",
        target_kind=target_kind,
        target_id=target_id,
        message_count=len(ids),
    )
    if not ids:
        return 0
    await client.batch_modify(ids, add_labels=["TRASH"], remove_labels=["INBOX"])
    for mid in ids:
        repo.set_message_trashed(conn, mid, True)
    return len(ids)


async def apply_label(
    client: GmailClient,
    conn: sqlite3.Connection,
    *,
    target_kind: TargetKind,
    target_id: int,
    label_name: str,
) -> int:
    ids = _affected_message_ids(conn, target_kind, target_id)
    label_id = await client.get_or_create_label(label_name)
    repo.write_action_log(
        conn,
        action_type="label",
        target_kind=target_kind,
        target_id=target_id,
        message_count=len(ids),
        details={"label": label_name, "label_id": label_id},
    )
    if not ids:
        return 0
    await client.batch_modify(ids, add_labels=[label_id], remove_labels=[])
    return len(ids)


async def unsubscribe(
    client: GmailClient,
    conn: sqlite3.Connection,
    *,
    target_kind: TargetKind,
    target_id: int,
) -> UnsubscribeResult:
    if target_kind == "sender":
        where = "WHERE sender_id = ?"
    else:
        where = (
            "WHERE sender_id IN (SELECT id FROM sender WHERE group_id = ?)"
        )
    rows = conn.execute(
        f"""
        SELECT id, list_unsubscribe FROM message
        {where} AND list_unsubscribe IS NOT NULL
        """,
        (target_id,),
    ).fetchall()

    result = UnsubscribeResult()
    seen_targets: set[str] = set()
    for row in rows:
        for action in parse_list_unsubscribe(row["list_unsubscribe"]):
            key = f"{action.kind}:{action.target}"
            if key in seen_targets:
                continue
            seen_targets.add(key)
            if action.kind == "mailto":
                try:
                    await client.send_unsubscribe_mailto(action.target, action.subject)
                    result.mailto_sent += 1
                except NotImplementedError:
                    result.skipped.append(action.target)
            else:
                result.http_urls.append(action.target)

    repo.write_action_log(
        conn,
        action_type="unsubscribe",
        target_kind=target_kind,
        target_id=target_id,
        message_count=len(rows),
        details={
            "mailto_sent": result.mailto_sent,
            "http_urls": result.http_urls,
            "skipped": result.skipped,
        },
    )
    return result
