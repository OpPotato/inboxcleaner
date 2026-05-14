from click.testing import CliRunner
from inboxcleaner.cli.main import cli


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
