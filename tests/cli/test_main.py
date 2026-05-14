import json as json_mod

from click.testing import CliRunner

from inboxcleaner.cli.main import cli
from inboxcleaner.core import repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender


def test_help_lists_all_subcommands():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in ("login", "sync", "senders", "regroup"):
        assert name in result.output


def test_version_flag():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_login_errors_when_client_secret_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["login"])
    assert result.exit_code != 0
    assert "client_secret.json" in result.output


def test_sync_help():
    result = CliRunner().invoke(cli, ["sync", "--help"])
    assert result.exit_code == 0
    assert "--query" in result.output


def _seed_db(tmp_path):
    conn = connect(tmp_path / "inboxcleaner.db")
    acct = repo.upsert_account(conn, Account(email="me@example.com"))
    g = repo.create_group(conn, name="Uniqlo", created_by="auto")
    s = repo.upsert_sender(
        conn,
        Sender(
            email="a@uniqlo.com",
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
            sender_id=s.id,
            subject="x",
            internal_date=1,
            size_estimate=100,
            category="promotions",
            labels=[],
            list_unsubscribe=None,
        ),
    )
    conn.close()


def test_senders_json_output(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    _seed_db(tmp_path)
    result = CliRunner().invoke(cli, ["senders", "--json"])
    assert result.exit_code == 0
    data = json_mod.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "Uniqlo"
    assert data[0]["message_count"] == 1
