import pytest
from fastapi.testclient import TestClient

from inboxcleaner.core import repo, sync_state
from inboxcleaner.core.db import connect
from inboxcleaner.core.gmail import GmailMessageMetadata
from inboxcleaner.core.models import Account, Message, Sender
from inboxcleaner.web import app as web_app_module
from inboxcleaner.web.app import app
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


def test_groups_page_full_render(seeded):
    client = TestClient(app)
    resp = client.get("/groups")
    assert resp.status_code == 200
    assert "Uniqlo" in resp.text
    # Has table headers
    assert "Messages" in resp.text


def test_groups_table_partial_via_htmx(seeded):
    client = TestClient(app)
    resp = client.get("/groups?sort=size", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "Uniqlo" in resp.text
    # Partial response does NOT include the page chrome (no <html>).
    assert "<html" not in resp.text


def test_groups_category_filter_drops_non_matching(seeded):
    client = TestClient(app)
    # Filter to promotions (matches) — group should appear.
    resp = client.get("/groups?category=promotions")
    assert "Uniqlo" in resp.text
    # Filter to social (no matching messages) — group should NOT appear.
    resp = client.get("/groups?category=social")
    assert "Uniqlo" not in resp.text


def test_group_detail_shows_senders_and_messages(seeded):
    _, group_id, _ = seeded
    client = TestClient(app)
    resp = client.get(f"/groups/{group_id}")
    assert resp.status_code == 200
    assert "Uniqlo" in resp.text
    assert "a@uniqlo.com" in resp.text
    assert "Sale" in resp.text
    # Action buttons present
    for action in ("archive", "trash", "label", "unsubscribe"):
        assert action in resp.text.lower()


def test_group_detail_404_for_unknown_id(seeded):
    client = TestClient(app)
    resp = client.get("/groups/99999")
    assert resp.status_code == 404


def test_preview_returns_modal_with_counts(seeded):
    _, group_id, _ = seeded
    client = TestClient(app)
    resp = client.post(
        "/actions/preview",
        json={"target_kind": "group", "target_id": group_id, "action": "trash"},
    )
    assert resp.status_code == 200
    assert "1 messages" in resp.text
    assert "Sale" in resp.text
    # Modal has a form posting to /actions/execute
    assert "/actions/execute" in resp.text


def test_execute_trash_runs_gmail_and_returns_done_fragment(seeded, monkeypatch):
    _, group_id, _ = seeded
    fake = FakeGmailClient()
    monkeypatch.setattr(web_app_module, "_get_client", lambda: fake)
    client = TestClient(app)
    resp = client.post(
        "/actions/execute",
        data={"target_kind": "group", "target_id": str(group_id), "action": "trash"},
    )
    assert resp.status_code == 200
    assert "trashed" in resp.text.lower() or "done" in resp.text.lower()
    mod = next(c for c in fake.calls if c[0] == "batch_modify")
    assert "TRASH" in mod[1]["add"]


def test_execute_label_requires_name(seeded, monkeypatch):
    _, group_id, _ = seeded
    fake = FakeGmailClient()
    monkeypatch.setattr(web_app_module, "_get_client", lambda: fake)
    client = TestClient(app)
    resp = client.post(
        "/actions/execute",
        data={"target_kind": "group", "target_id": str(group_id), "action": "label"},
    )
    assert resp.status_code == 400


def test_execute_label_with_name_applies(seeded, monkeypatch):
    _, group_id, _ = seeded
    fake = FakeGmailClient()
    monkeypatch.setattr(web_app_module, "_get_client", lambda: fake)
    client = TestClient(app)
    resp = client.post(
        "/actions/execute",
        data={
            "target_kind": "group", "target_id": str(group_id),
            "action": "label", "label_name": "shopping",
        },
    )
    assert resp.status_code == 200
    assert "shopping" in fake.labels


def test_recent_fragment_returns_all_messages_for_group(seeded):
    _, group_id, _ = seeded
    client = TestClient(app)
    resp = client.get(f"/recent?group_id={group_id}")
    assert resp.status_code == 200
    assert "Sale" in resp.text
    # No "Show all" button when not filtered
    assert "Show all" not in resp.text
    # No <html> wrapper — it's a fragment
    assert "<html" not in resp.text


def test_recent_fragment_filters_to_sender(seeded):
    _, group_id, sender_id = seeded
    client = TestClient(app)
    resp = client.get(f"/recent?group_id={group_id}&sender_id={sender_id}")
    assert resp.status_code == 200
    assert "Sale" in resp.text
    # Sender heading visible
    assert "a@uniqlo.com" in resp.text
    # Reset button present
    assert "Show all" in resp.text


def test_recent_fragment_404_for_wrong_group(seeded):
    _, _, sender_id = seeded
    client = TestClient(app)
    resp = client.get(f"/recent?group_id=99999&sender_id={sender_id}")
    assert resp.status_code == 404


def test_recent_fragment_404_for_sender_outside_group(seeded, tmp_path, monkeypatch):
    # Create a second group + sender that does NOT belong to seeded's group
    _, group_id, _ = seeded
    conn = connect(tmp_path / "inboxcleaner.db")
    other_group = repo.create_group(conn, name="Other", created_by="auto")
    other_sender = repo.upsert_sender(
        conn,
        Sender(email="x@other.com", display_name="Other",
               domain="other.com", group_id=other_group.id),
    )
    conn.close()
    client = TestClient(app)
    # Asking for other_sender in seeded's group should 404.
    resp = client.get(f"/recent?group_id={group_id}&sender_id={other_sender.id}")
    assert resp.status_code == 404


def test_group_detail_marks_sender_rows_clickable(seeded):
    _, group_id, _ = seeded
    client = TestClient(app)
    resp = client.get(f"/groups/{group_id}")
    assert resp.status_code == 200
    # Sender rows have hx-get pointing at /recent
    assert "hx-get=\"/recent?group_id=" in resp.text
    assert "sender-row" in resp.text


def _make_meta(mid: str, from_: str, internal: int) -> GmailMessageMetadata:
    return GmailMessageMetadata(
        id=mid, threadId=f"t{mid}",
        internalDate=str(internal), sizeEstimate=4096,
        labelIds=["CATEGORY_PROMOTIONS"],
        payload={"headers": [
            {"name": "From", "value": from_},
            {"name": "Subject", "value": f"subj-{mid}"},
        ]},
    )


@pytest.fixture(autouse=True)
def _reset_sync_state():
    sync_state.reset()
    yield
    sync_state.reset()


def test_sync_status_idle_shows_button(seeded):
    client = TestClient(app)
    resp = client.get("/sync/status")
    assert resp.status_code == 200
    assert "Sync now" in resp.text
    assert "Syncing" not in resp.text


def test_post_sync_kicks_off_and_returns_status_fragment(seeded, monkeypatch):
    fake = FakeGmailClient(
        email="me@example.com",
        history_id="100",
        messages={"m1": _make_meta("m1", "Uniqlo <a@uniqlo.com>", 1_700_000_000_000)},
        query_ids={
            "category:promotions OR category:social OR category:updates": ["m1"]
        },
    )
    monkeypatch.setattr(web_app_module, "_get_client", lambda: fake)
    client = TestClient(app)
    resp = client.post("/sync")
    assert resp.status_code == 200
    # Returned fragment is the sync-status div, either in-progress or idle
    # depending on how fast the background task drained.
    assert "sync-status" in resp.text


def test_post_sync_runs_with_fake_client_to_completion(seeded, monkeypatch):
    fake = FakeGmailClient(
        email="me@example.com",
        history_id="200",
        messages={
            "m1": _make_meta("m1", "Uniqlo <a@uniqlo.com>", 1_700_000_000_000),
            "m2": _make_meta("m2", "Patagonia <hi@patagonia.com>", 1_700_000_000_001),
        },
        query_ids={
            "category:promotions OR category:social OR category:updates": ["m1", "m2"]
        },
    )
    monkeypatch.setattr(web_app_module, "_get_client", lambda: fake)

    import asyncio

    async def run():
        # Skip the create_task path; await directly so the test is deterministic.
        return await sync_state.run_sync(lambda: fake)

    result = asyncio.run(run())
    assert result.error is None
    assert result.last_message_count >= 1
    assert sync_state.status().last_history_id == "200"


def test_get_sync_status_during_in_progress_returns_running_fragment(monkeypatch):
    # Manually set the status to simulate an in-progress sync.
    sync_state.reset()
    sync_state.status().in_progress = True
    sync_state.status().done = 50
    sync_state.status().total = 100
    client = TestClient(app)
    resp = client.get("/sync/status")
    assert resp.status_code == 200
    assert "Syncing" in resp.text
    assert "50" in resp.text
    assert "100" in resp.text
