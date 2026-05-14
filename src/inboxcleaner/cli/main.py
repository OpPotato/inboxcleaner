import asyncio
from pathlib import Path

import click
from rich.progress import Progress

from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect
from inboxcleaner.core.gmail import RealGmailClient, load_or_run_oauth
from inboxcleaner.core.logging_setup import configure_logging
from inboxcleaner.core.sync import DEFAULT_QUERY, incremental_sync, initial_sync


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
    help=(
        "Path to Google OAuth client_secret.json. "
        "Defaults to $INBOXCLEANER_HOME/client_secret.json "
        "or ~/.config/inboxcleaner/client_secret.json."
    ),
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
    load_or_run_oauth(client_secret, paths.token)
    click.echo(f"Authenticated. Token cached at {paths.token}.")


@cli.command()
@click.option("--query", default=DEFAULT_QUERY, help="Gmail search query for initial sync.")
def sync(query: str) -> None:
    """Sync mail metadata into the local cache."""
    asyncio.run(_run_sync(query))


async def _run_sync(query: str) -> None:
    paths = Paths.default()
    paths.ensure_dirs()
    if not paths.token.exists():
        raise click.ClickException("Not logged in. Run `inboxcleaner login` first.")
    secret = paths.token.parent / "client_secret.json"
    creds = load_or_run_oauth(secret, paths.token)
    client = RealGmailClient(creds)
    conn = connect(paths.db)
    try:
        profile = await client.get_profile()
        email = profile["emailAddress"]
        row = conn.execute(
            "SELECT id, history_id FROM account WHERE email = ?", (email,)
        ).fetchone()
        with Progress() as progress_ui:
            task = progress_ui.add_task("Syncing", total=None)

            def on_progress(done: int, total: int) -> None:
                if progress_ui.tasks[0].total != total:
                    progress_ui.update(task, total=total)
                progress_ui.update(task, completed=done)

            if row is None or row["history_id"] is None:
                result = await initial_sync(
                    client, conn, account_email=email, query=query, progress=on_progress
                )
            else:
                result = await incremental_sync(
                    client, conn, account_id=row["id"], progress=on_progress
                )
        click.echo(f"Synced {result.message_count} messages. history_id={result.history_id}")
    finally:
        conn.close()


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
