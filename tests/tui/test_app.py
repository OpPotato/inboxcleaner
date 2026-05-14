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
        # senders has 1 real sender + 1 "* All senders *" pseudo-row at top.
        senders = app.query_one("#senders")
        recent = app.query_one("#recent")
        assert senders.row_count == 2
        # First row is "All", recent shows the 1 message from the group.
        assert recent.row_count == 1


async def test_selecting_sender_filters_recent(seeded_multi):
    _, _alpha_id, _bravo_id = seeded_multi
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        senders = app.query_one("#senders")
        recent = app.query_one("#recent")
        # Default group (Bravo, 3 msgs). Senders pane: "* All *" + 1 real sender.
        assert senders.row_count == 2
        assert recent.row_count == 3
        # Move cursor to the real sender row. RowHighlighted fires; recent
        # filters to that sender (still 3, since group has 1 sender).
        senders.move_cursor(row=1)
        await pilot.pause()
        assert recent.row_count == 3
        # Move back to "* All *" — recent reverts to group-wide.
        senders.move_cursor(row=0)
        await pilot.pause()
        assert recent.row_count == 3


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


@pytest.fixture
def seeded_multi(tmp_path, monkeypatch):
    """Two groups with different message counts and names — exercises sorting."""
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    conn = connect(tmp_path / "inboxcleaner.db")
    acct = repo.upsert_account(conn, Account(email="me@example.com"))
    g_a = repo.create_group(conn, name="Alpha", created_by="auto")
    g_b = repo.create_group(conn, name="Bravo", created_by="auto")
    s_a = repo.upsert_sender(
        conn,
        Sender(email="a@alpha.com", display_name="Alpha", domain="alpha.com", group_id=g_a.id),
    )
    s_b = repo.upsert_sender(
        conn,
        Sender(email="b@bravo.com", display_name="Bravo", domain="bravo.com", group_id=g_b.id),
    )
    # Bravo has 3 messages, Alpha has 1. Default repo order: Bravo, Alpha (count desc).
    for i in range(3):
        repo.upsert_message(
            conn,
            Message(
                id=f"b{i}", account_id=acct.id, thread_id=f"tb{i}", sender_id=s_b.id,
                subject="x", internal_date=2_000_000_000_000 + i, size_estimate=100,
                category="promotions", labels=[], list_unsubscribe=None,
            ),
        )
    repo.upsert_message(
        conn,
        Message(
            id="a1", account_id=acct.id, thread_id="ta1", sender_id=s_a.id,
            subject="x", internal_date=1_000_000_000_000, size_estimate=100,
            category="promotions", labels=[], list_unsubscribe=None,
        ),
    )
    conn.close()
    return tmp_path, g_a.id, g_b.id


async def test_sort_cycle_on_messages_column(seeded_multi):
    _, alpha_id, bravo_id = seeded_multi
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        groups = app.query_one("#groups")
        order = lambda: [k.value for k in groups.rows]  # noqa: E731

        # Default (no sort): repo returns count DESC → Bravo (3), Alpha (1)
        assert order() == [str(bravo_id), str(alpha_id)]
        assert app._sort_column is None

        # First click: desc
        app._sort_column = "count"
        app._sort_direction = "desc"
        app._load_groups()
        await pilot.pause()
        assert order() == [str(bravo_id), str(alpha_id)]

        # Cycle: desc → asc → unsorted → desc (simulate via header click)
        app.on_data_table_header_selected(_fake_header_event(groups, "count"))
        await pilot.pause()
        assert app._sort_direction == "asc"
        assert order() == [str(alpha_id), str(bravo_id)]

        app.on_data_table_header_selected(_fake_header_event(groups, "count"))
        await pilot.pause()
        assert app._sort_column is None
        assert app._sort_direction is None

        app.on_data_table_header_selected(_fake_header_event(groups, "count"))
        await pilot.pause()
        assert app._sort_column == "count"
        assert app._sort_direction == "desc"


async def test_sort_by_name_ascending(seeded_multi):
    _, alpha_id, bravo_id = seeded_multi
    app = InboxCleanerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        groups = app.query_one("#groups")
        # Click name twice → asc
        app.on_data_table_header_selected(_fake_header_event(groups, "name"))  # desc
        app.on_data_table_header_selected(_fake_header_event(groups, "name"))  # asc
        await pilot.pause()
        assert [k.value for k in groups.rows] == [str(alpha_id), str(bravo_id)]


def _fake_header_event(table, column_key: str):
    """Construct a DataTable.HeaderSelected-like event without going through
    the pointer-click event pipeline."""
    from textual.widgets._data_table import ColumnKey

    class _Evt:
        pass

    evt = _Evt()
    evt.data_table = table
    evt.column_key = ColumnKey(column_key)
    evt.column_index = 0
    evt.label = None
    return evt
