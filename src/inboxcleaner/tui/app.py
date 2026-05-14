"""Textual TUI for inboxcleaner.

Three-pane layout: groups (left), senders + recent (right top/bottom).
Keyboard-driven cleanup with the same backend the CLI and web UIs use.
"""
from __future__ import annotations

from datetime import datetime
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
        if groups.row_count > 0:
            groups.move_cursor(row=0)
            gid = self._selected_group_id()
            if gid is not None:
                self._load_detail_for(gid)

    def _selected_group_id(self) -> int | None:
        groups = self.query_one("#groups", DataTable)
        if groups.row_count == 0:
            return None
        try:
            row_key = groups.coordinate_to_cell_key(
                groups.cursor_coordinate
            ).row_key
        except (KeyError, IndexError, ValueError):
            return None
        return int(row_key.value) if row_key.value else None

    def _load_detail_for(self, group_id: int) -> None:
        senders_table = self.query_one("#senders", DataTable)
        recent_table = self.query_one("#recent", DataTable)
        senders_table.clear()
        recent_table.clear()
        conn = _open_db()
        try:
            senders = repo.senders_for_group(conn, group_id)
            for s in senders:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM message WHERE sender_id = ? AND is_trashed = 0",
                    (s.id,),
                ).fetchone()["n"]
                senders_table.add_row(s.email, s.display_name or "", str(count))
            rows = conn.execute(
                """
                SELECT subject, internal_date FROM message
                WHERE sender_id IN (SELECT id FROM sender WHERE group_id = ?)
                  AND is_trashed = 0
                ORDER BY internal_date DESC LIMIT 5
                """,
                (group_id,),
            ).fetchall()
            for r in rows:
                date_str = datetime.fromtimestamp(r["internal_date"] / 1000).strftime("%Y-%m-%d")
                recent_table.add_row(date_str, r["subject"] or "(no subject)")
        finally:
            conn.close()

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        if event.data_table.id != "groups":
            return
        gid = self._selected_group_id()
        if gid is not None:
            self._load_detail_for(gid)

    def action_refresh(self) -> None:
        self._load_groups()


def main() -> None:
    InboxCleanerApp().run()
