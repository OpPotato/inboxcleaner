import json
import sqlite3
from dataclasses import dataclass

from inboxcleaner.core.models import (
    Account,
    ActionType,
    Message,
    Sender,
    SenderGroup,
    TargetKind,
)


@dataclass(frozen=True)
class GroupSummary:
    id: int
    name: str
    message_count: int
    total_size: int
    latest_message_date: int | None


def upsert_account(conn: sqlite3.Connection, account: Account) -> Account:
    existing = conn.execute(
        "SELECT * FROM account WHERE email = ?", (account.email,)
    ).fetchone()
    if existing is None:
        cur = conn.execute(
            "INSERT INTO account (email, history_id, last_sync_at) VALUES (?, ?, ?)",
            (account.email, account.history_id, account.last_sync_at),
        )
        return account.model_copy(update={"id": cur.lastrowid})
    conn.execute(
        "UPDATE account SET history_id = ?, last_sync_at = ? WHERE id = ?",
        (account.history_id, account.last_sync_at, existing["id"]),
    )
    return account.model_copy(update={"id": existing["id"]})


def create_group(
    conn: sqlite3.Connection, *, name: str, created_by: str, notes: str | None = None
) -> SenderGroup:
    cur = conn.execute(
        "INSERT INTO sender_group (name, created_by, notes) VALUES (?, ?, ?)",
        (name, created_by, notes),
    )
    return SenderGroup(id=cur.lastrowid, name=name, created_by=created_by, notes=notes)


def get_group(conn: sqlite3.Connection, group_id: int) -> SenderGroup | None:
    row = conn.execute("SELECT * FROM sender_group WHERE id = ?", (group_id,)).fetchone()
    return SenderGroup(**dict(row)) if row else None


def all_groups(conn: sqlite3.Connection) -> list[SenderGroup]:
    rows = conn.execute("SELECT * FROM sender_group ORDER BY name").fetchall()
    return [SenderGroup(**dict(r)) for r in rows]


def upsert_sender(conn: sqlite3.Connection, sender: Sender) -> Sender:
    row = conn.execute(
        "SELECT * FROM sender WHERE email = ? AND IFNULL(display_name, '') = IFNULL(?, '')",
        (sender.email, sender.display_name),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO sender (email, display_name, domain, group_id) VALUES (?, ?, ?, ?)",
            (sender.email, sender.display_name, sender.domain, sender.group_id),
        )
        return sender.model_copy(update={"id": cur.lastrowid})
    if sender.group_id is not None and row["group_id"] != sender.group_id:
        conn.execute(
            "UPDATE sender SET group_id = ? WHERE id = ?", (sender.group_id, row["id"])
        )
    return sender.model_copy(update={"id": row["id"]})


def senders_for_group(conn: sqlite3.Connection, group_id: int) -> list[Sender]:
    rows = conn.execute(
        "SELECT * FROM sender WHERE group_id = ? ORDER BY email", (group_id,)
    ).fetchall()
    return [Sender(**dict(r)) for r in rows]


def reassign_sender(conn: sqlite3.Connection, sender_id: int, new_group_id: int) -> None:
    conn.execute("UPDATE sender SET group_id = ? WHERE id = ?", (new_group_id, sender_id))


def upsert_message(conn: sqlite3.Connection, msg: Message) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO message
            (id, account_id, thread_id, sender_id, subject, internal_date,
             size_estimate, category, labels, list_unsubscribe, is_trashed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            msg.id,
            msg.account_id,
            msg.thread_id,
            msg.sender_id,
            msg.subject,
            msg.internal_date,
            msg.size_estimate,
            msg.category,
            json.dumps(msg.labels),
            msg.list_unsubscribe,
            int(msg.is_trashed),
        ),
    )


def delete_message(conn: sqlite3.Connection, message_id: str) -> None:
    conn.execute("DELETE FROM message WHERE id = ?", (message_id,))


def set_message_trashed(conn: sqlite3.Connection, message_id: str, trashed: bool) -> None:
    conn.execute(
        "UPDATE message SET is_trashed = ? WHERE id = ?", (int(trashed), message_id)
    )


def message_ids_for_sender(conn: sqlite3.Connection, sender_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM message WHERE sender_id = ? AND is_trashed = 0", (sender_id,)
    ).fetchall()
    return [r["id"] for r in rows]


def message_ids_for_group(conn: sqlite3.Connection, group_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT m.id FROM message m
        JOIN sender s ON m.sender_id = s.id
        WHERE s.group_id = ? AND m.is_trashed = 0
        """,
        (group_id,),
    ).fetchall()
    return [r["id"] for r in rows]


def groups_with_counts(conn: sqlite3.Connection) -> list[GroupSummary]:
    rows = conn.execute(
        """
        SELECT g.id, g.name,
               COUNT(m.id) AS message_count,
               COALESCE(SUM(m.size_estimate), 0) AS total_size,
               MAX(m.internal_date) AS latest
        FROM sender_group g
        LEFT JOIN sender s ON s.group_id = g.id
        LEFT JOIN message m ON m.sender_id = s.id AND m.is_trashed = 0
        GROUP BY g.id, g.name
        ORDER BY message_count DESC
        """
    ).fetchall()
    return [
        GroupSummary(
            id=r["id"],
            name=r["name"],
            message_count=r["message_count"],
            total_size=r["total_size"],
            latest_message_date=r["latest"],
        )
        for r in rows
    ]


def write_action_log(
    conn: sqlite3.Connection,
    *,
    action_type: ActionType,
    target_kind: TargetKind,
    target_id: int,
    message_count: int,
    details: dict | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO action_log
            (action_type, target_kind, target_id, message_count, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            action_type,
            target_kind,
            target_id,
            message_count,
            json.dumps(details) if details is not None else None,
        ),
    )
    return cur.lastrowid


def acquire_sync_lock(conn: sqlite3.Connection, pid: int) -> bool:
    try:
        conn.execute(
            "INSERT INTO sync_lock (id, pid, started_at) VALUES (1, ?, CURRENT_TIMESTAMP)",
            (pid,),
        )
        return True
    except sqlite3.IntegrityError:
        # Lock held; check if stale (>1 hour)
        row = conn.execute("SELECT started_at FROM sync_lock WHERE id = 1").fetchone()
        if row is None:
            return False
        stale = conn.execute(
            "SELECT (julianday('now') - julianday(started_at)) * 24 > 1 AS stale"
            " FROM sync_lock WHERE id = 1"
        ).fetchone()
        if stale and stale["stale"]:
            conn.execute(
                "UPDATE sync_lock SET pid = ?, started_at = CURRENT_TIMESTAMP WHERE id = 1",
                (pid,),
            )
            return True
        return False


def release_sync_lock(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sync_lock WHERE id = 1")
