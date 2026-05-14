import asyncio
import contextlib
import json as _json
from datetime import datetime
from pathlib import Path

import click
from google.auth.exceptions import RefreshError
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from inboxcleaner.core import repo
from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect
from inboxcleaner.core.gmail import RealGmailClient, load_or_run_oauth
from inboxcleaner.core.grouping import ExistingGroup, GroupIndex, assign_group
from inboxcleaner.core.logging_setup import configure_logging
from inboxcleaner.core.models import Sender
from inboxcleaner.core.sync import DEFAULT_QUERY, incremental_sync, initial_sync


def _install_client_secret(src: Path, dest: Path) -> None:
    """Validate a downloaded Google OAuth JSON is a Desktop-application
    credential, then copy it to `dest` with 0o600 permissions.

    Raises click.ClickException on invalid JSON, wrong client type, or
    missing required fields.
    """
    try:
        data = _json.loads(src.read_text())
    except _json.JSONDecodeError as exc:
        raise click.ClickException(f"{src} is not valid JSON: {exc}") from exc
    if "installed" not in data:
        raise click.ClickException(
            f"{src} is not a Desktop application credential. Expected an "
            "'installed' top-level key. If you created a Web or Mobile OAuth "
            "client, recreate it with Application type 'Desktop app'."
        )
    required = ("client_id", "client_secret", "redirect_uris")
    missing = [k for k in required if k not in data["installed"]]
    if missing:
        raise click.ClickException(
            f"{src} is missing required fields under 'installed': {missing}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text())
    dest.chmod(0o600)


def _load_creds_or_die(client_secret: Path, token_path: Path):
    try:
        return load_or_run_oauth(client_secret, token_path)
    except RefreshError as exc:
        # Refresh token has been revoked or expired. Clear the cache and ask the user to re-login.
        with contextlib.suppress(FileNotFoundError):
            token_path.unlink()
        raise click.ClickException(
            f"Cached OAuth token at {token_path} was rejected ({exc}). "
            "It's been cleared — re-run `inboxcleaner login`."
        ) from exc


@click.group()
@click.version_option("0.1.0", prog_name="inboxcleaner")
def cli() -> None:
    """Local-first Gmail cleanup tool."""
    configure_logging(Paths.default())


@cli.command()
def setup() -> None:
    """One-time guided onboarding: walks through Google Cloud Console setup."""
    paths = Paths.default()
    paths.ensure_dirs()
    target = paths.token.parent / "client_secret.json"

    if target.exists() and not click.confirm(
        f"Found existing {target}. Overwrite?", default=False
    ):
        click.echo(
            "Setup aborted. Run `inboxcleaner login` to use the existing credentials."
        )
        return

    click.echo("inboxcleaner needs a one-time Google Cloud setup (~5 minutes).")
    click.echo(
        "You create your own Google Cloud project — no shared developer credentials."
    )
    click.echo("")

    # Step 1: Create project
    click.echo("[1/4] Create a Google Cloud project")
    url = "https://console.cloud.google.com/projectcreate"
    click.echo(f"  Open: {url}")
    click.echo("  - Name it something like 'inboxcleaner-yourname'.")
    click.echo("  - Click Create and wait ~30 seconds for provisioning.")
    click.launch(url)
    click.pause(info="\n  Press ENTER when the project is created...")

    # Step 2: Enable Gmail API
    click.echo("\n[2/4] Enable the Gmail API")
    url = "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
    click.echo(f"  Open: {url}")
    click.echo("  - Make sure your new project is selected in the top bar.")
    click.echo("  - Click Enable.")
    click.launch(url)
    click.pause(info="\n  Press ENTER when the Gmail API is enabled...")

    # Step 3: Configure consent screen
    click.echo("\n[3/4] Configure the OAuth consent screen")
    url = "https://console.cloud.google.com/apis/credentials/consent"
    click.echo(f"  Open: {url}")
    click.echo("  - User Type: External  -> Create")
    click.echo("  - App name: inboxcleaner")
    click.echo("  - User support email + Developer contact email: your email")
    click.echo("  - Save and Continue")
    click.echo("  - Scopes -> Add or Remove Scopes -> search 'gmail.modify' ->")
    click.echo("    check it -> Update -> Save and Continue")
    click.echo("  - Test users -> Add Users -> enter your email -> Add -> Save and Continue")
    click.echo("  - Back to Dashboard")
    click.launch(url)
    click.pause(info="\n  Press ENTER when the consent screen is configured...")

    # Step 4: Create OAuth client and download
    click.echo("\n[4/4] Create OAuth client credentials")
    url = "https://console.cloud.google.com/apis/credentials"
    click.echo(f"  Open: {url}")
    click.echo("  - Click Create Credentials -> OAuth client ID")
    click.echo("  - Application type: Desktop app")
    click.echo("  - Name: inboxcleaner-cli")
    click.echo("  - Click Create, then in the popup click Download JSON.")
    click.launch(url)
    click.pause(info="\n  Press ENTER when you've downloaded the JSON file...")

    src = click.prompt(
        "\n  Path to the downloaded JSON file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    _install_client_secret(Path(src), target)
    click.echo(f"\nCredentials installed at {target} (0600).")

    if click.confirm("\nRun `inboxcleaner login` now to complete OAuth?", default=True):
        ctx = click.get_current_context()
        ctx.invoke(login)
    else:
        click.echo("Run `inboxcleaner login` when ready.")


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
    _load_creds_or_die(client_secret, paths.token)
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
    creds = _load_creds_or_die(secret, paths.token)
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
        table.add_column("ID", justify="right")
        table.add_column("Name")
        table.add_column("Messages", justify="right")
        table.add_column("Total size", justify="right")
        table.add_column("Latest", justify="right")
        for s in summaries:
            table.add_row(
                str(s.id),
                s.name,
                str(s.message_count),
                _human_size(s.total_size),
                _human_date(s.latest_message_date),
            )
        Console().print(table)
    finally:
        conn.close()


@cli.command()
@click.argument("group_id", type=int)
def show(group_id: int) -> None:
    """Drill into a sender group: constituent senders and recent messages."""
    paths = Paths.default()
    paths.ensure_dirs()
    conn = connect(paths.db)
    try:
        group = repo.get_group(conn, group_id)
        if group is None:
            raise click.ClickException(f"No group with id {group_id}.")
        senders = repo.senders_for_group(conn, group_id)
        msg_count = conn.execute(
            "SELECT COUNT(*) AS n FROM message WHERE sender_id IN "
            "(SELECT id FROM sender WHERE group_id = ?) AND is_trashed = 0",
            (group_id,),
        ).fetchone()["n"]
        unsub_count = conn.execute(
            "SELECT COUNT(*) AS n FROM message WHERE sender_id IN "
            "(SELECT id FROM sender WHERE group_id = ?) "
            "AND is_trashed = 0 AND list_unsubscribe IS NOT NULL",
            (group_id,),
        ).fetchone()["n"]
        recent = conn.execute(
            """
            SELECT subject, internal_date FROM message
            WHERE sender_id IN (SELECT id FROM sender WHERE group_id = ?)
              AND is_trashed = 0
            ORDER BY internal_date DESC LIMIT 5
            """,
            (group_id,),
        ).fetchall()

        console = Console()
        console.print(
            f"[bold]{group.name}[/bold] (id={group.id}, {msg_count} messages, "
            f"{unsub_count} with List-Unsubscribe)"
        )

        senders_table = Table(title="Senders")
        senders_table.add_column("Email")
        senders_table.add_column("Display name")
        senders_table.add_column("Messages", justify="right")
        for s in senders:
            per_sender = conn.execute(
                "SELECT COUNT(*) AS n FROM message WHERE sender_id = ? AND is_trashed = 0",
                (s.id,),
            ).fetchone()["n"]
            senders_table.add_row(s.email, s.display_name or "", str(per_sender))
        console.print(senders_table)

        recent_table = Table(title="Recent messages")
        recent_table.add_column("Date")
        recent_table.add_column("Subject")
        for r in recent:
            recent_table.add_row(_human_date(r["internal_date"]), r["subject"] or "")
        console.print(recent_table)
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
    """Drop auto-created groups and re-run grouping over all senders."""
    paths = Paths.default()
    paths.ensure_dirs()
    conn = connect(paths.db)
    try:
        # Detach senders from auto groups; keep manual ones.
        conn.execute(
            """
            UPDATE sender SET group_id = NULL
            WHERE group_id IN (SELECT id FROM sender_group WHERE created_by = 'auto')
            """
        )
        conn.execute("DELETE FROM sender_group WHERE created_by = 'auto'")

        sender_rows = conn.execute("SELECT * FROM sender ORDER BY id").fetchall()
        assigned = 0
        for r in sender_rows:
            s = Sender(**dict(r))
            current_senders = [
                Sender(**dict(rr))
                for rr in conn.execute(
                    "SELECT * FROM sender WHERE group_id IS NOT NULL"
                ).fetchall()
            ]
            idx = GroupIndex(groups=repo.all_groups(conn), senders=current_senders)
            decision = assign_group(s, idx)
            if isinstance(decision, ExistingGroup):
                group_id = decision.group_id
            else:
                group_id = repo.create_group(conn, name=decision.name, created_by="auto").id
            repo.reassign_sender(conn, s.id, group_id)
            assigned += 1
        click.echo(f"Regrouped {assigned} senders.")
    finally:
        conn.close()


# Register CLI action subcommands (archive, trash, label, unsubscribe).
# Import is at the bottom to avoid circular imports — actions.py needs `cli`
# from this module.
from inboxcleaner.cli import actions  # noqa: E402, F401


def main() -> None:
    cli()
