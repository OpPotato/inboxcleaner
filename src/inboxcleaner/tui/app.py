"""Textual TUI for inboxcleaner.

Three-pane layout: groups (left), senders + recent (right top/bottom).
Keyboard-driven cleanup with the same backend the CLI and web UIs use.
"""
from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header

from inboxcleaner.core import repo
from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect


def _open_db():
    paths = Paths.default()
    paths.ensure_dirs()
    return connect(paths.db)


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


class InboxCleanerApp(App):
    """The TUI entry point."""

    CSS_PATH = "styles.tcss"
    TITLE = "inboxcleaner"
    BINDINGS: ClassVar[list] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="groups", cursor_type="row")
        with Vertical(id="right-pane"):
            yield DataTable(id="senders", cursor_type="row")
            yield DataTable(id="recent", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        groups = self.query_one("#groups", DataTable)
        groups.add_columns("ID", "Name", "Messages", "Size")
        senders = self.query_one("#senders", DataTable)
        senders.add_columns("Email", "Display", "Count")
        recent = self.query_one("#recent", DataTable)
        recent.add_columns("Date", "Subject")
        self._load_groups()

    def _load_groups(self) -> None:
        groups = self.query_one("#groups", DataTable)
        groups.clear()
        conn = _open_db()
        try:
            summaries = repo.groups_with_counts(conn)  # already ordered by count DESC
        finally:
            conn.close()
        for s in summaries:
            groups.add_row(
                str(s.id), s.name, str(s.message_count),
                _human_size(s.total_size),
                key=str(s.id),
            )

    def action_refresh(self) -> None:
        self._load_groups()


def main() -> None:
    InboxCleanerApp().run()
