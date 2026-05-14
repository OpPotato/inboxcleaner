import pytest

from inboxcleaner.core import repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender
from inboxcleaner.tui.app import InboxCleanerApp


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


async def test_app_starts_with_three_panes(seeded):
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # All three DataTables exist
        assert app.query_one("#groups") is not None
        assert app.query_one("#senders") is not None
        assert app.query_one("#recent") is not None


async def test_app_registers_quit_and_refresh_bindings(seeded):
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        keys = [b[0] if isinstance(b, tuple) else b.key for b in app.BINDINGS]
        assert "q" in keys
        assert "r" in keys
