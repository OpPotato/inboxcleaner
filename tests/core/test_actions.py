import pytest

from inboxcleaner.core import actions, repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender
from tests.fakes import FakeGmailClient


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def _seed(conn) -> tuple[int, int, int]:
    acct = repo.upsert_account(conn, Account(email="me@example.com"))
    g = repo.create_group(conn, name="Uniqlo", created_by="auto")
    s1 = repo.upsert_sender(
        conn,
        Sender(email="a@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=g.id),
    )
    s2 = repo.upsert_sender(
        conn,
        Sender(
            email="b@email.uniqlo.com",
            display_name="Uniqlo",
            domain="uniqlo.com",
            group_id=g.id,
        ),
    )
    repo.upsert_message(
        conn,
        Message(
            id="m1",
            account_id=acct.id,
            thread_id="t1",
            sender_id=s1.id,
            subject="Sale 1",
            internal_date=1,
            size_estimate=100,
            category="promotions",
            labels=["CATEGORY_PROMOTIONS"],
            list_unsubscribe="<https://uniqlo.com/u>",
        ),
    )
    repo.upsert_message(
        conn,
        Message(
            id="m2",
            account_id=acct.id,
            thread_id="t2",
            sender_id=s2.id,
            subject="Sale 2",
            internal_date=2,
            size_estimate=200,
            category="promotions",
            labels=["CATEGORY_PROMOTIONS"],
            list_unsubscribe="<mailto:u@uniqlo.com?subject=unsubscribe>",
        ),
    )
    return g.id, s1.id, s2.id


def test_preview_for_group_counts_and_samples(conn):
    g_id, _, _ = _seed(conn)
    p = actions.preview(conn, target_kind="group", target_id=g_id)
    assert p.message_count == 2
    assert p.total_size == 300
    assert {s.subject for s in p.samples} == {"Sale 1", "Sale 2"}


@pytest.mark.asyncio
async def test_trash_marks_messages_and_logs(conn):
    g_id, _, _ = _seed(conn)
    fake = FakeGmailClient()
    await actions.trash(
        fake, conn, target_kind="group", target_id=g_id
    )
    # All affected messages should be is_trashed=1
    rows = conn.execute("SELECT id, is_trashed FROM message").fetchall()
    assert all(r["is_trashed"] == 1 for r in rows)
    # Action log row written
    log = conn.execute(
        "SELECT * FROM action_log WHERE action_type = 'trash'"
    ).fetchone()
    assert log["target_kind"] == "group"
    assert log["target_id"] == g_id
    assert log["message_count"] == 2
    # Gmail client invoked
    methods = [c[0] for c in fake.calls]
    assert "batch_modify" in methods or "trash" in methods


@pytest.mark.asyncio
async def test_archive_removes_inbox_label(conn):
    g_id, _, _ = _seed(conn)
    fake = FakeGmailClient()
    await actions.archive(fake, conn, target_kind="group", target_id=g_id)
    mod_call = next(c for c in fake.calls if c[0] == "batch_modify")
    assert "INBOX" in mod_call[1]["remove"]


@pytest.mark.asyncio
async def test_label_creates_label_and_applies(conn):
    g_id, _, _ = _seed(conn)
    fake = FakeGmailClient()
    await actions.apply_label(
        fake, conn, target_kind="group", target_id=g_id, label_name="shopping"
    )
    # Label was created
    assert "shopping" in fake.labels
    mod_call = next(c for c in fake.calls if c[0] == "batch_modify")
    assert fake.labels["shopping"] in mod_call[1]["add"]


@pytest.mark.asyncio
async def test_unsubscribe_skips_mailto_when_gmail_send_unsupported(conn):
    g_id, _, _ = _seed(conn)
    fake = FakeGmailClient()
    # FakeGmailClient.send_unsubscribe_mailto raises NotImplementedError below;
    # configure it to do so.
    async def boom(*a, **k):
        raise NotImplementedError
    fake.send_unsubscribe_mailto = boom  # type: ignore[assignment]

    result = await actions.unsubscribe(
        fake, conn, target_kind="group", target_id=g_id
    )
    assert result.mailto_sent == 0
    assert result.http_urls  # one http URL surfaced
    assert "https://uniqlo.com/u" in result.http_urls
