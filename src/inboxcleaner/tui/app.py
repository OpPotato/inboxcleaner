"""Textual TUI for inboxcleaner.

Three-pane layout: groups (left), senders + recent (right top/bottom).
Keyboard-driven cleanup with the same backend the CLI and web UIs use.
"""
from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header

from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect


def _open_db():
    paths = Paths.default()
    paths.ensure_dirs()
    return connect(paths.db)


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

    def action_refresh(self) -> None:
        """Reload everything from the DB (filled in by Task 2)."""
        pass


def main() -> None:
    InboxCleanerApp().run()
