import pytest

from inboxcleaner.core import repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender
from inboxcleaner.tui import app as tui_app_module
from inboxcleaner.tui.app import ConfirmActionModal, InboxCleanerApp
from tests.fakes import FakeGmailClient


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


async def test_groups_loaded_into_left_pane(seeded):
    _, group_id, _ = seeded
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        groups = app.query_one("#groups")
        assert groups.row_count == 1
        # Group id used as the row key
        row_keys = [str(k.value) for k in groups.rows.keys()]  # noqa: SIM118
        assert str(group_id) in row_keys


async def test_selecting_group_populates_senders_and_recent(seeded):
    _, _group_id, _ = seeded
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # First row is auto-selected after load; senders + recent populated.
        senders = app.query_one("#senders")
        recent = app.query_one("#recent")
        assert senders.row_count == 1
        assert recent.row_count == 1


async def test_pressing_t_opens_trash_modal(seeded):
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        # Modal screen is now on top
        assert isinstance(app.screen, ConfirmActionModal)
        assert app.screen.action == "trash"


async def test_confirm_trash_invokes_gmail(seeded, monkeypatch):
    fake = FakeGmailClient()
    monkeypatch.setattr(tui_app_module, "_get_client", lambda: fake)
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        # Click the confirm button
        await pilot.click("#confirm")
        await pilot.pause()
        mod = next(c for c in fake.calls if c[0] == "batch_modify")
        assert "TRASH" in mod[1]["add"]


async def test_cancel_trash_does_not_invoke_gmail(seeded, monkeypatch):
    fake = FakeGmailClient()
    monkeypatch.setattr(tui_app_module, "_get_client", lambda: fake)
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        assert not any(c[0] == "batch_modify" for c in fake.calls)
