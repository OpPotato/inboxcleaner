from pathlib import Path

import click

from inboxcleaner.core.config import Paths
from inboxcleaner.core.gmail import load_or_run_oauth
from inboxcleaner.core.logging_setup import configure_logging


@click.group()
@click.version_option("0.1.0", prog_name="inboxcleaner")
def cli() -> None:
    """Local-first Gmail cleanup tool."""
    configure_logging(Paths.default())


@cli.command()
@click.option(
    "--client-secret",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to Google OAuth client_secret.json. "
         "Defaults to $INBOXCLEANER_HOME/client_secret.json or ~/.config/inboxcleaner/client_secret.json.",
)
def login(client_secret: Path | None) -> None:
    """Run the Gmail OAuth flow and cache the refresh token."""
    paths = Paths.default()
    paths.ensure_dirs()
    if client_secret is None:
        client_secret = paths.token.parent / "client_secret.json"
    if not client_secret.exists():
        raise click.ClickException(
            f"OAuth client secret not found at {client_secret}.\n"
            "Get one from https://console.cloud.google.com/apis/credentials "
            "(OAuth client ID, Desktop application), then place the JSON there."
        )
    creds = load_or_run_oauth(client_secret, paths.token)
    click.echo(f"Authenticated. Token cached at {paths.token}.")


@cli.command()
def sync() -> None:
    """Sync mail metadata into the local cache."""
    click.echo("sync: not yet implemented (Task 15)")


@cli.command()
def senders() -> None:
    """Print a table of sender groups."""
    click.echo("senders: not yet implemented (Task 16)")


@cli.command()
def regroup() -> None:
    """Re-run grouping over all senders."""
    click.echo("regroup: not yet implemented (Task 17)")


def main() -> None:
    cli()
