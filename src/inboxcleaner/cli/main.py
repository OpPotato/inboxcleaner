import asyncio
import json as _json
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from inboxcleaner.core import repo
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
@click.option(
    "--sort",
    type=click.Choice(["count", "size", "date"]),
    default="count",
    show_default=True,
)
@click.option("--limit", type=int, default=50, show_default=True)
@click.option(
    "--category",
    type=click.Choice(["promotions", "social", "updates", "all"]),
    default="all",
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a table.")
def senders(sort: str, limit: int, category: str, as_json: bool) -> None:
    """Print a table of sender groups."""
    paths = Paths.default()
    paths.ensure_dirs()
    conn = connect(paths.db)
    try:
        summaries = repo.groups_with_counts(conn)
        if category != "all":
            keep_ids = {
                r["group_id"]
                for r in conn.execute(
                    """
                    SELECT DISTINCT s.group_id
                    FROM sender s
                    JOIN message m ON m.sender_id = s.id
                    WHERE m.category = ?
                    """,
                    (category,),
                ).fetchall()
                if r["group_id"] is not None
            }
            summaries = [s for s in summaries if s.id in keep_ids]
        if sort == "size":
            summaries.sort(key=lambda x: x.total_size, reverse=True)
        elif sort == "date":
            summaries.sort(key=lambda x: x.latest_message_date or 0, reverse=True)
        summaries = summaries[:limit]

        if as_json:
            click.echo(
                _json.dumps(
                    [
                        {
                            "id": s.id,
                            "name": s.name,
                            "message_count": s.message_count,
                            "total_size": s.total_size,
                            "latest_message_date": s.latest_message_date,
                        }
                        for s in summaries
                    ],
                    indent=2,
                )
            )
            return

        table = Table(title="Sender groups")
        table.add_column("Name")
        table.add_column("Messages", justify="right")
        table.add_column("Total size", justify="right")
        table.add_column("Latest", justify="right")
        for s in summaries:
            table.add_row(
                s.name,
                str(s.message_count),
                _human_size(s.total_size),
                _human_date(s.latest_message_date),
            )
        Console().print(table)
    finally:
        conn.close()


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def _human_date(ms: int | None) -> str:
    if ms is None:
        return "-"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


@cli.command()
def regroup() -> None:
    """Re-run grouping over all senders."""
    click.echo("regroup: not yet implemented (Task 17)")


def main() -> None:
    cli()
