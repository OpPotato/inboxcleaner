"""In-process sync orchestration shared by the web and TUI frontends.

The CLI's `inboxcleaner sync` command does its own thing and writes to its
own progress bar. This module lets a long-lived UI (web server, TUI app)
trigger a sync, watch its progress, and not block on it.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect
from inboxcleaner.core.gmail import GmailClient
from inboxcleaner.core.sync import DEFAULT_QUERY, incremental_sync, initial_sync


@dataclass
class SyncStatus:
    in_progress: bool = False
    done: int = 0
    total: int = 0
    last_message_count: int | None = None
    last_history_id: str | None = None
    error: str | None = None


# Module-level singleton. Both web (per-process) and TUI use this same object.
_status = SyncStatus()


def status() -> SyncStatus:
    return _status


def reset() -> None:
    """Reset all fields. Used in tests."""
    global _status
    _status = SyncStatus()


async def run_sync(client_factory: Callable[[], GmailClient]) -> SyncStatus:
    """Run a sync end-to-end, updating the module-level status object.

    Idempotent: if a sync is already in progress, returns the current status
    without starting a new one.
    """
    if _status.in_progress:
        return _status
    _status.in_progress = True
    _status.done = 0
    _status.total = 0
    _status.error = None
    try:
        paths = Paths.default()
        paths.ensure_dirs()
        client = client_factory()
        conn = connect(paths.db)
        try:
            profile = await client.get_profile()
            email = profile["emailAddress"]
            row = conn.execute(
                "SELECT id, history_id FROM account WHERE email = ?", (email,)
            ).fetchone()

            def progress(done: int, total: int) -> None:
                _status.done = done
                _status.total = total

            if row is None or row["history_id"] is None:
                result = await initial_sync(
                    client, conn,
                    account_email=email, query=DEFAULT_QUERY, progress=progress,
                )
            else:
                result = await incremental_sync(
                    client, conn,
                    account_id=row["id"], progress=progress,
                )
            _status.last_message_count = result.message_count
            _status.last_history_id = result.history_id
        finally:
            conn.close()
    except Exception as exc:
        _status.error = str(exc)
    finally:
        _status.in_progress = False
    return _status


# Live task references kept here so asyncio doesn't garbage-collect them
# before they finish (ruff RUF006).
_background_tasks: set[asyncio.Task] = set()


def trigger_sync_in_background(client_factory: Callable[[], GmailClient]) -> bool:
    """Kick off `run_sync` as a fire-and-forget asyncio task.

    Returns True if a new sync was started, False if one was already running.
    Must be called from within a running asyncio event loop.
    """
    if _status.in_progress:
        return False
    task = asyncio.create_task(run_sync(client_factory))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True
