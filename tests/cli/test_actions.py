import pytest
from click.testing import CliRunner

from inboxcleaner.cli import actions as cli_actions
from inboxcleaner.cli.main import cli
from inboxcleaner.core import repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender
from tests.fakes import FakeGmailClient


@pytest.fixture
def seeded_home(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    # Pretend we're logged in so _get_client doesn't bail on the token check.
    (tmp_path / "token.json").write_text("{}")
    conn = connect(tmp_path / "inboxcleaner.db")
    acct = repo.upsert_account(conn, Account(email="me@example.com"))
    g = repo.create_group(conn, name="Uniqlo", created_by="auto")
    s = repo.upsert_sender(
        conn,
        Sender(email="a@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=g.id),
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


def test_archive_dry_run_prints_preview_and_skips_gmail(seeded_home, monkeypatch):
    _tmp_path, group_id, _ = seeded_home

    def boom():
        raise AssertionError("--dry-run must not contact Gmail")

    monkeypatch.setattr(cli_actions, "_get_client", boom)
    result = CliRunner().invoke(cli, ["archive", "--group", str(group_id), "--dry-run"])
    assert result.exit_code == 0
    assert "1 messages" in result.output
    assert "Sale" in result.output
    assert "--dry-run" in result.output


def test_archive_yes_invokes_gmail(seeded_home, monkeypatch):
    _tmp_path, group_id, _ = seeded_home
    fake = FakeGmailClient()
    monkeypatch.setattr(cli_actions, "_get_client", lambda: fake)
    result = CliRunner().invoke(cli, ["archive", "--group", str(group_id), "--yes"])
    assert result.exit_code == 0
    # batch_modify was called with INBOX removed.
    mod = next(c for c in fake.calls if c[0] == "batch_modify")
    assert "INBOX" in mod[1]["remove"]


def test_archive_prompt_n_aborts(seeded_home, monkeypatch):
    _tmp_path, group_id, _ = seeded_home
    fake = FakeGmailClient()
    monkeypatch.setattr(cli_actions, "_get_client", lambda: fake)
    result = CliRunner().invoke(cli, ["archive", "--group", str(group_id)], input="n\n")
    assert result.exit_code == 0
    assert "Aborted" in result.output
    assert not any(c[0] == "batch_modify" for c in fake.calls)


def test_archive_requires_one_target(seeded_home):
    result = CliRunner().invoke(cli, ["archive"])
    assert result.exit_code != 0
    assert "Specify exactly one of --group or --sender" in result.output


def test_archive_rejects_missing_group(seeded_home):
    result = CliRunner().invoke(cli, ["archive", "--group", "9999", "--dry-run"])
    assert result.exit_code != 0
    assert "No group with id 9999" in result.output


def test_trash_yes_invokes_gmail_and_marks_db(seeded_home, monkeypatch):
    tmp_path, group_id, _ = seeded_home
    fake = FakeGmailClient()
    monkeypatch.setattr(cli_actions, "_get_client", lambda: fake)
    result = CliRunner().invoke(cli, ["trash", "--group", str(group_id), "--yes"])
    assert result.exit_code == 0
    mod = next(c for c in fake.calls if c[0] == "batch_modify")
    assert "TRASH" in mod[1]["add"]
    conn = connect(tmp_path / "inboxcleaner.db")
    try:
        row = conn.execute("SELECT is_trashed FROM message WHERE id = 'm1'").fetchone()
        assert row["is_trashed"] == 1
    finally:
        conn.close()


def test_label_requires_name(seeded_home):
    _, group_id, _ = seeded_home
    result = CliRunner().invoke(cli, ["label", "--group", str(group_id), "--dry-run"])
    assert result.exit_code != 0
    assert "name" in result.output.lower()


def test_label_yes_creates_label_and_applies(seeded_home, monkeypatch):
    _, group_id, _ = seeded_home
    fake = FakeGmailClient()
    monkeypatch.setattr(cli_actions, "_get_client", lambda: fake)
    result = CliRunner().invoke(
        cli, ["label", "--group", str(group_id), "--name", "shopping", "--yes"]
    )
    assert result.exit_code == 0
    assert "shopping" in fake.labels
    mod = next(c for c in fake.calls if c[0] == "batch_modify")
    assert fake.labels["shopping"] in mod[1]["add"]


def test_unsubscribe_yes_surfaces_http_urls(seeded_home, monkeypatch):
    _a, group_id, _b = seeded_home
    fake = FakeGmailClient()

    async def boom(*a, **k):
        raise NotImplementedError

    fake.send_unsubscribe_mailto = boom  # type: ignore[assignment]
    monkeypatch.setattr(cli_actions, "_get_client", lambda: fake)

    result = CliRunner().invoke(
        cli, ["unsubscribe", "--group", str(group_id), "--yes"]
    )
    assert result.exit_code == 0
    assert "https://uniqlo.com/u" in result.output
