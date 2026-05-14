"""Mutating CLI commands (archive, trash, label, unsubscribe).

Each command resolves a --group or --sender target, fetches a dry-run
preview via core.actions.preview(), prints it, and either exits (with
--dry-run), executes immediately (with --yes), or prompts for confirmation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import click
from rich.console import Console
from rich.table import Table

# _human_size and _human_date already live in cli.main from Task 16 —
# reuse them here rather than duplicating to keep formats consistent.
from inboxcleaner.cli.main import _human_date, _human_size
from inboxcleaner.cli.main import cli as _cli
from inboxcleaner.core import actions, repo
from inboxcleaner.core.actions import ActionPreview
from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect
from inboxcleaner.core.gmail import GmailClient, RealGmailClient
from inboxcleaner.core.models import TargetKind


def _get_client() -> GmailClient:
    """Build a Gmail client from the cached OAuth token. Imported lazily
    so tests can monkeypatch this to return a FakeGmailClient.
    """
    # Local import to avoid a circular import with cli.main.
    from inboxcleaner.cli.main import _load_creds_or_die

    paths = Paths.default()
    paths.ensure_dirs()
    if not paths.token.exists():
        raise click.ClickException("Not logged in. Run `inboxcleaner login` first.")
    secret = paths.token.parent / "client_secret.json"
    creds = _load_creds_or_die(secret, paths.token)
    return RealGmailClient(creds)


def _resolve_target(
    conn, group: int | None, sender: int | None
) -> tuple[TargetKind, int]:
    """Validate that exactly one of --group/--sender is given and that
    the target exists in the DB.
    """
    if (group is None) == (sender is None):
        raise click.UsageError("Specify exactly one of --group or --sender.")
    if group is not None:
        if repo.get_group(conn, group) is None:
            raise click.ClickException(f"No group with id {group}.")
        return "group", group
    row = conn.execute("SELECT id FROM sender WHERE id = ?", (sender,)).fetchone()
    if row is None:
        raise click.ClickException(f"No sender with id {sender}.")
    return "sender", sender


def _print_preview(preview: ActionPreview, console: Console) -> None:
    console.print(
        f"[bold]{preview.target_kind} {preview.target_id}[/bold]: "
        f"{preview.message_count} messages, "
        f"{_human_size(preview.total_size)}"
    )
    if not preview.samples:
        return
    table = Table(title="Sample messages")
    table.add_column("Date")
    table.add_column("Subject")
    for s in preview.samples:
        table.add_row(_human_date(s.internal_date), s.subject or "")
    console.print(table)


async def _confirm_and_run(
    target_kind: TargetKind,
    target_id: int,
    dry_run: bool,
    yes: bool,
    runner: Callable,
) -> None:
    """Shared preview + confirm + execute flow.

    `runner` is an async callable taking (client, conn) and performing the
    action. It returns whatever the action returns (int for archive/trash/label,
    UnsubscribeResult for unsubscribe). The result is echoed via click.echo.
    """
    paths = Paths.default()
    paths.ensure_dirs()
    conn = connect(paths.db)
    try:
        preview = actions.preview(conn, target_kind=target_kind, target_id=target_id)
        _print_preview(preview, Console())
        if dry_run:
            click.echo("(--dry-run: no changes applied)")
            return
        if preview.message_count == 0:
            click.echo("No messages to act on.")
            return
        if not yes and not click.confirm("Proceed?", default=False):
            click.echo("Aborted.")
            return
        client = _get_client()
        result = await runner(client, conn)
        click.echo(f"Done: {result}")
    finally:
        conn.close()


def _target_options(fn):
    """Add --group/--sender option pair to a command."""
    fn = click.option("--sender", "sender", type=int, default=None,
                      help="Operate on a single sender by id.")(fn)
    fn = click.option("--group", "group", type=int, default=None,
                      help="Operate on all senders in a group by id.")(fn)
    return fn


def _common_options(fn):
    fn = click.option("--yes", is_flag=True, help="Skip confirmation prompt.")(fn)
    fn = click.option("--dry-run", is_flag=True,
                      help="Show preview and exit without contacting Gmail.")(fn)
    return fn


@_cli.command()
@_target_options
@_common_options
def archive(group: int | None, sender: int | None, dry_run: bool, yes: bool) -> None:
    """Archive messages (remove INBOX label) for a group or sender."""
    asyncio.run(_run_archive(group, sender, dry_run, yes))


async def _run_archive(group, sender, dry_run, yes) -> None:
    paths = Paths.default()
    paths.ensure_dirs()
    conn = connect(paths.db)
    try:
        target_kind, target_id = _resolve_target(conn, group, sender)
    finally:
        conn.close()

    async def runner(client, conn):
        return await actions.archive(
            client, conn, target_kind=target_kind, target_id=target_id
        )

    await _confirm_and_run(target_kind, target_id, dry_run, yes, runner)


@_cli.command()
@_target_options
@_common_options
def trash(group: int | None, sender: int | None, dry_run: bool, yes: bool) -> None:
    """Move messages to Gmail Trash (recoverable for 30 days)."""
    asyncio.run(_run_trash(group, sender, dry_run, yes))


async def _run_trash(group, sender, dry_run, yes) -> None:
    paths = Paths.default()
    paths.ensure_dirs()
    conn = connect(paths.db)
    try:
        target_kind, target_id = _resolve_target(conn, group, sender)
    finally:
        conn.close()

    async def runner(client, conn):
        return await actions.trash(
            client, conn, target_kind=target_kind, target_id=target_id
        )

    await _confirm_and_run(target_kind, target_id, dry_run, yes, runner)


@_cli.command()
@_target_options
@click.option("--name", "label_name", required=True, help="Label name to apply.")
@_common_options
def label(
    group: int | None,
    sender: int | None,
    label_name: str,
    dry_run: bool,
    yes: bool,
) -> None:
    """Apply a Gmail label to messages (auto-creates the label if needed)."""
    asyncio.run(_run_label(group, sender, label_name, dry_run, yes))


async def _run_label(group, sender, label_name, dry_run, yes) -> None:
    paths = Paths.default()
    paths.ensure_dirs()
    conn = connect(paths.db)
    try:
        target_kind, target_id = _resolve_target(conn, group, sender)
    finally:
        conn.close()

    async def runner(client, conn):
        return await actions.apply_label(
            client, conn,
            target_kind=target_kind, target_id=target_id,
            label_name=label_name,
        )

    await _confirm_and_run(target_kind, target_id, dry_run, yes, runner)
