import json

import pytest

from inboxcleaner.core import repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def test_upsert_account_inserts_then_updates(conn):
    a = repo.upsert_account(conn, Account(email="me@example.com"))
    assert a.id is not None
    a2 = repo.upsert_account(conn, Account(email="me@example.com", history_id="42"))
    assert a2.id == a.id
    assert a2.history_id == "42"


def test_upsert_group_and_sender(conn):
    g = repo.create_group(conn, name="Uniqlo", created_by="auto")
    assert g.id is not None
    s = repo.upsert_sender(
        conn,
        Sender(email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=g.id),
    )
    s2 = repo.upsert_sender(
        conn,
        Sender(email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=g.id),
    )
    assert s.id == s2.id


def test_insert_message_and_query_by_group(conn):
    acct = repo.upsert_account(conn, Account(email="me@example.com"))
    g = repo.create_group(conn, name="Uniqlo", created_by="auto")
    s = repo.upsert_sender(
        conn,
        Sender(email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=g.id),
    )
    repo.upsert_message(
        conn,
        Message(
            id="m1",
            account_id=acct.id,
            thread_id="t1",
            sender_id=s.id,
            subject="Sale",
            internal_date=1_700_000_000_000,
            size_estimate=4096,
            category="promotions",
            labels=["CATEGORY_PROMOTIONS"],
            list_unsubscribe=None,
        ),
    )
    rows = repo.message_ids_for_group(conn, g.id)
    assert rows == ["m1"]


def test_groups_with_counts(conn):
    acct = repo.upsert_account(conn, Account(email="me@example.com"))
    g = repo.create_group(conn, name="Uniqlo", created_by="auto")
    s = repo.upsert_sender(
        conn,
        Sender(email="news@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=g.id),
    )
    for i in range(3):
        repo.upsert_message(
            conn,
            Message(
                id=f"m{i}",
                account_id=acct.id,
                thread_id=f"t{i}",
                sender_id=s.id,
                subject="x",
                internal_date=1_700_000_000_000 + i,
                size_estimate=100,
                category="promotions",
                labels=[],
                list_unsubscribe=None,
            ),
        )
    summaries = repo.groups_with_counts(conn)
    assert len(summaries) == 1
    assert summaries[0].name == "Uniqlo"
    assert summaries[0].message_count == 3
    assert summaries[0].total_size == 300


def test_write_action_log(conn):
    entry_id = repo.write_action_log(
        conn,
        action_type="trash",
        target_kind="group",
        target_id=1,
        message_count=10,
        details={"reason": "test"},
    )
    assert entry_id > 0
    row = conn.execute("SELECT * FROM action_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["action_type"] == "trash"
    assert json.loads(row["details"]) == {"reason": "test"}
