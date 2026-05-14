import pytest
from fastapi.testclient import TestClient

from inboxcleaner.core import repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender
from inboxcleaner.web.app import app


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    conn = connect(tmp_path / "inboxcleaner.db")
    acct = repo.upsert_account(conn, Account(email="me@example.com"))
    g = repo.create_group(conn, name="Uniqlo", created_by="auto")
    s = repo.upsert_sender(
        conn,
        Sender(email="a@uniqlo.com", display_name="Uniqlo",
               domain="uniqlo.com", group_id=g.id),
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
            labels=["CATEGORY_PROMOTIONS", "INBOX"],
            list_unsubscribe="<https://uniqlo.com/u>",
        ),
    )
    conn.close()
    return tmp_path, g.id, s.id


def test_index_shows_account_and_counts(seeded):
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "me@example.com" in resp.text
    assert "1 messages" in resp.text
    assert "1 groups" in resp.text


def test_index_handles_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    # Force the DB to exist with schema but no data
    conn = connect(tmp_path / "inboxcleaner.db")
    conn.close()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No synced account" in resp.text
