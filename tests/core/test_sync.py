import pytest

from inboxcleaner.core.db import connect
from inboxcleaner.core.sync import DEFAULT_QUERY, incremental_sync, initial_sync
from tests.fakes import FakeGmailClient, make_metadata


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


@pytest.mark.asyncio
async def test_initial_sync_persists_messages_and_history_id(conn):
    fake = FakeGmailClient(
        email="me@example.com",
        history_id="100",
        messages={
            "m1": make_metadata(msg_id="m1", from_="Uniqlo <news@uniqlo.com>"),
            "m2": make_metadata(msg_id="m2", from_="Patagonia <hello@patagonia.com>"),
            "m3": make_metadata(msg_id="m3", from_="Uniqlo <noreply@email.uniqlo.com>"),
        },
        query_ids={DEFAULT_QUERY: ["m1", "m2", "m3"]},
    )

    result = await initial_sync(fake, conn, account_email="me@example.com")

    assert result.message_count == 3
    rows = conn.execute("SELECT COUNT(*) AS n FROM message").fetchone()
    assert rows["n"] == 3
    # Two distinct domains -> two groups
    groups = conn.execute("SELECT COUNT(*) AS n FROM sender_group").fetchone()
    assert groups["n"] == 2
    # Both Uniqlo senders share a group
    uniqlo_group = conn.execute(
        "SELECT id FROM sender_group WHERE name = ?", ("Uniqlo",)
    ).fetchone()
    senders = conn.execute(
        "SELECT email FROM sender WHERE group_id = ? ORDER BY email",
        (uniqlo_group["id"],),
    ).fetchall()
    assert [s["email"] for s in senders] == ["news@uniqlo.com", "noreply@email.uniqlo.com"]
    # history_id stored
    acct = conn.execute("SELECT history_id FROM account").fetchone()
    assert acct["history_id"] == "100"


@pytest.mark.asyncio
async def test_initial_sync_is_idempotent(conn):
    fake = FakeGmailClient(
        history_id="100",
        messages={"m1": make_metadata(msg_id="m1", from_="X <a@x.com>")},
        query_ids={DEFAULT_QUERY: ["m1"]},
    )
    await initial_sync(fake, conn, account_email="me@example.com")
    await initial_sync(fake, conn, account_email="me@example.com")
    n = conn.execute("SELECT COUNT(*) AS n FROM message").fetchone()["n"]
    assert n == 1


@pytest.mark.asyncio
async def test_incremental_sync_applies_added_and_trashed(conn):
    fake = FakeGmailClient(
        history_id="100",
        messages={"m1": make_metadata(msg_id="m1", from_="X <a@x.com>")},
        query_ids={DEFAULT_QUERY: ["m1"]},
    )
    await initial_sync(fake, conn, account_email="me@example.com")

    # New message + label-added TRASH on m1
    fake.messages["m2"] = make_metadata(msg_id="m2", from_="Y <b@y.com>")
    fake.history_id = "200"
    fake.history = [
        {"type": "messageAdded", "message_id": "m2", "label_ids": ["CATEGORY_PROMOTIONS"]},
        {"type": "labelAdded", "message_id": "m1", "label_ids": ["TRASH"]},
    ]
    acct = conn.execute("SELECT id FROM account").fetchone()
    result = await incremental_sync(fake, conn, account_id=acct["id"])
    assert result.message_count == 1  # one new
    rows = conn.execute("SELECT id, is_trashed FROM message ORDER BY id").fetchall()
    state = {r["id"]: r["is_trashed"] for r in rows}
    assert state == {"m1": 1, "m2": 0}
    assert (
        conn.execute("SELECT history_id FROM account").fetchone()["history_id"] == "200"
    )


@pytest.mark.asyncio
async def test_incremental_sync_handles_hard_delete(conn):
    fake = FakeGmailClient(
        history_id="100",
        messages={"m1": make_metadata(msg_id="m1", from_="X <a@x.com>")},
        query_ids={DEFAULT_QUERY: ["m1"]},
    )
    await initial_sync(fake, conn, account_email="me@example.com")
    fake.history = [{"type": "messageDeleted", "message_id": "m1", "label_ids": []}]
    fake.history_id = "200"
    acct = conn.execute("SELECT id FROM account").fetchone()
    await incremental_sync(fake, conn, account_id=acct["id"])
    assert conn.execute("SELECT COUNT(*) AS n FROM message").fetchone()["n"] == 0


@pytest.mark.asyncio
async def test_initial_sync_skips_unparseable_from(conn):
    fake = FakeGmailClient(
        history_id="100",
        messages={
            "m1": make_metadata(msg_id="m1", from_="Alice <a@x.com>"),
            "m2": make_metadata(msg_id="m2", from_=""),  # unparseable
        },
        query_ids={DEFAULT_QUERY: ["m1", "m2"]},
    )
    result = await initial_sync(fake, conn, account_email="me@example.com")
    assert result.message_count == 1
    assert conn.execute("SELECT COUNT(*) FROM message").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_incremental_sync_falls_back_to_initial_on_stale_history(conn):
    fake = FakeGmailClient(
        history_id="100",
        messages={"m1": make_metadata(msg_id="m1", from_="X <a@x.com>")},
        query_ids={DEFAULT_QUERY: ["m1"]},
    )
    await initial_sync(fake, conn, account_email="me@example.com")

    # Simulate stale historyId: client returns (events=[], new_history_id=None)
    async def stale_history(_):
        return [], None

    fake.history_since = stale_history  # type: ignore[assignment]
    fake.history_id = "999"
    # Add a new message that initial sync would pick up
    fake.messages["m2"] = make_metadata(msg_id="m2", from_="Y <b@y.com>")
    fake.query_ids[DEFAULT_QUERY] = ["m1", "m2"]
    acct = conn.execute("SELECT id FROM account").fetchone()
    await incremental_sync(fake, conn, account_id=acct["id"])
    assert conn.execute("SELECT COUNT(*) AS n FROM message").fetchone()["n"] == 2


@pytest.mark.asyncio
async def test_initial_sync_groups_streaming_added_senders(conn):
    """Each message in the same sync should see senders added by earlier messages."""
    fake = FakeGmailClient(
        history_id="100",
        messages={
            "m1": make_metadata(msg_id="m1", from_="Uniqlo <a@uniqlo.com>"),
            # same brand, different sender — must join m1's group
            "m2": make_metadata(msg_id="m2", from_="Uniqlo <b@uniqlo.com>"),
            "m3": make_metadata(msg_id="m3", from_="Patagonia <c@patagonia.com>"),
        },
        query_ids={DEFAULT_QUERY: ["m1", "m2", "m3"]},
    )
    result = await initial_sync(fake, conn, account_email="me@example.com")
    assert result.message_count == 3
    # m1 and m2 should be in the same group (Uniqlo), m3 in its own (Patagonia)
    n_groups = conn.execute("SELECT COUNT(*) AS n FROM sender_group").fetchone()["n"]
    assert n_groups == 2
    uniqlo_group = conn.execute("SELECT id FROM sender_group WHERE name = 'Uniqlo'").fetchone()
    n_uniqlo_senders = conn.execute(
        "SELECT COUNT(*) AS n FROM sender WHERE group_id = ?", (uniqlo_group["id"],)
    ).fetchone()["n"]
    assert n_uniqlo_senders == 2
