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


def test_regroup_rebuilds_auto_groups(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    conn = connect(tmp_path / "inboxcleaner.db")
    # Two senders that should end up in the same group by domain.
    repo.upsert_account(conn, Account(email="me@example.com"))
    g1 = repo.create_group(conn, name="Uniqlo", created_by="auto")
    g2 = repo.create_group(conn, name="Uniqlo Newsletter", created_by="auto")
    repo.upsert_sender(
        conn,
        Sender(email="a@uniqlo.com", display_name="Uniqlo", domain="uniqlo.com", group_id=g1.id),
    )
    repo.upsert_sender(
        conn,
        Sender(
            email="b@email.uniqlo.com",
            display_name="Uniqlo Newsletter",
            domain="uniqlo.com",
            group_id=g2.id,
        ),
    )
    conn.close()

    result = CliRunner().invoke(cli, ["regroup"])
    assert result.exit_code == 0

    conn = connect(tmp_path / "inboxcleaner.db")
    # Should be exactly one auto group now (both senders join it)
    groups = conn.execute(
        "SELECT COUNT(*) AS n FROM sender_group WHERE created_by = 'auto'"
    ).fetchone()["n"]
    assert groups == 1
    distinct_groups = conn.execute(
        "SELECT COUNT(DISTINCT group_id) AS n FROM sender"
    ).fetchone()["n"]
    assert distinct_groups == 1
    conn.close()


def test_show_group_drill_in(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    conn = connect(tmp_path / "inboxcleaner.db")
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
            display_name="Uniqlo Newsletter",
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
            subject="Spring Sale",
            internal_date=1_700_000_000_000,
            size_estimate=4096,
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
            subject="New Arrivals",
            internal_date=1_700_000_001_000,
            size_estimate=2048,
            category="promotions",
            labels=["CATEGORY_PROMOTIONS"],
            list_unsubscribe=None,
        ),
    )
    conn.close()

    result = CliRunner().invoke(cli, ["show", str(g.id)])
    assert result.exit_code == 0
    assert "Uniqlo" in result.output
    assert "a@uniqlo.com" in result.output
    assert "b@email.uniqlo.com" in result.output
    assert "Spring Sale" in result.output
    assert "New Arrivals" in result.output


def test_show_errors_when_group_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    conn = connect(tmp_path / "inboxcleaner.db")
    conn.close()
    result = CliRunner().invoke(cli, ["show", "999"])
    assert result.exit_code != 0
    assert "999" in result.output
