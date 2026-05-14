import json as json_mod

import click
import pytest
from click.testing import CliRunner

from inboxcleaner.cli.main import _install_client_secret, cli
from inboxcleaner.core import repo
from inboxcleaner.core.db import connect
from inboxcleaner.core.models import Account, Message, Sender


def test_help_lists_all_subcommands():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in ("login", "sync", "senders", "regroup", "show"):
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
    assert "inboxcleaner setup" in result.output


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


def _valid_desktop_secret() -> dict:
    return {
        "installed": {
            "client_id": "1234.apps.googleusercontent.com",
            "client_secret": "GOCSPX-xxxxx",
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def test_install_client_secret_happy_path(tmp_path):
    src = tmp_path / "downloaded.json"
    src.write_text(json_mod.dumps(_valid_desktop_secret()))
    dest = tmp_path / "config" / "client_secret.json"
    _install_client_secret(src, dest)
    assert dest.exists()
    assert json_mod.loads(dest.read_text()) == _valid_desktop_secret()
    mode = dest.stat().st_mode & 0o777
    assert mode == 0o600


def test_install_client_secret_rejects_invalid_json(tmp_path):
    src = tmp_path / "bad.json"
    src.write_text("not json at all {{{")
    dest = tmp_path / "client_secret.json"
    with pytest.raises(click.ClickException) as exc_info:
        _install_client_secret(src, dest)
    assert "not valid JSON" in str(exc_info.value.message)
    assert not dest.exists()


def test_install_client_secret_rejects_web_app_credential(tmp_path):
    # Web app OAuth clients use a "web" top-level key, not "installed".
    src = tmp_path / "web.json"
    src.write_text(json_mod.dumps({"web": {"client_id": "x"}}))
    dest = tmp_path / "client_secret.json"
    with pytest.raises(click.ClickException) as exc_info:
        _install_client_secret(src, dest)
    assert "Desktop" in str(exc_info.value.message)
    assert not dest.exists()


def test_install_client_secret_rejects_missing_required_fields(tmp_path):
    src = tmp_path / "incomplete.json"
    src.write_text(json_mod.dumps({"installed": {"client_id": "x"}}))
    dest = tmp_path / "client_secret.json"
    with pytest.raises(click.ClickException) as exc_info:
        _install_client_secret(src, dest)
    assert "missing" in str(exc_info.value.message).lower()
    assert not dest.exists()


def test_setup_installs_secret_and_skips_login(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    # Stub click.launch so it doesn't open real browser windows during tests.
    monkeypatch.setattr("click.launch", lambda *a, **kw: 0)

    downloaded = tmp_path / "downloaded.json"
    downloaded.write_text(json_mod.dumps(_valid_desktop_secret()))

    # 4 ENTERs for the pauses, then path, then "n" to skip the auto-login.
    inputs = "\n\n\n\n" + str(downloaded) + "\nn\n"
    result = CliRunner().invoke(cli, ["setup"], input=inputs)
    assert result.exit_code == 0, result.output
    target = tmp_path / "client_secret.json"
    assert target.exists()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600
    # All 4 Cloud Console URLs should have been mentioned in the output.
    assert "console.cloud.google.com/projectcreate" in result.output
    assert "gmail.googleapis.com" in result.output
    assert "credentials/consent" in result.output
    # Final URL is plain credentials page.
    assert "console.cloud.google.com/apis/credentials" in result.output


def test_setup_aborts_if_secret_exists_and_user_says_no(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    monkeypatch.setattr("click.launch", lambda *a, **kw: 0)
    existing = tmp_path / "client_secret.json"
    existing.write_text("{}")
    original = existing.read_text()
    # Reply "n" to the overwrite prompt.
    result = CliRunner().invoke(cli, ["setup"], input="n\n")
    assert result.exit_code == 0
    # Existing file untouched.
    assert existing.read_text() == original
    assert "aborted" in result.output.lower() or "existing" in result.output.lower()


def test_setup_rejects_invalid_downloaded_file(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    monkeypatch.setattr("click.launch", lambda *a, **kw: 0)
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    inputs = "\n\n\n\n" + str(bad) + "\n"
    result = CliRunner().invoke(cli, ["setup"], input=inputs)
    assert result.exit_code != 0
    target = tmp_path / "client_secret.json"
    assert not target.exists()
