"""Textual TUI for inboxcleaner.

Three-pane layout: groups (left), senders + recent (right top/bottom).
Keyboard-driven cleanup with the same backend the CLI and web UIs use.
"""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label

from inboxcleaner.core import actions, repo
from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect
from inboxcleaner.core.gmail import GmailClient, RealGmailClient


def _open_db():
    paths = Paths.default()
    paths.ensure_dirs()
    return connect(paths.db)


def _get_client() -> GmailClient:
    """Build a Gmail client. Monkeypatched in tests."""
    from inboxcleaner.cli.main import _load_creds_or_die

    paths = Paths.default()
    paths.ensure_dirs()
    if not paths.token.exists():
        raise RuntimeError(
            "Not logged in. Run `inboxcleaner login` first."
        )
    secret = paths.token.parent / "client_secret.json"
    creds = _load_creds_or_die(secret, paths.token)
    return RealGmailClient(creds)


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


# Column key → how to extract a sortable value from a GroupSummary.
def _sort_value(summary, column: str):
    if column == "id":
        return summary.id
    if column == "name":
        return summary.name.lower() if summary.name else ""
    if column == "count":
        return summary.message_count
    if column == "size":
        return summary.total_size
    if column == "date":
        return summary.latest_message_date or 0
    return 0


# (label, key, fixed_width). Fixed widths keep columns from reflowing when
# we rebuild the table to apply a new sort — that reflow is what causes
# the rapid-click flicker.
_GROUP_COLUMNS: list[tuple[str, str, int]] = [
    ("ID", "id", 6),
    ("Name", "name", 30),
    ("Messages", "count", 10),
    ("Size", "size", 8),
    ("Latest", "date", 12),
]


class ConfirmActionModal(ModalScreen[bool]):
    """Preview an action and ask the user to confirm."""

    def __init__(
        self,
        action: str,
        target_id: int,
        preview: actions.ActionPreview,
    ) -> None:
        super().__init__()
        self.action = action
        self.target_id = target_id
        self.preview = preview

    def compose(self) -> ComposeResult:
        sample_lines = "\n".join(
            f"  • {s.subject or '(no subject)'}" for s in self.preview.samples
        ) or "  (no samples)"
        with Container(id="dialog"):
            yield Label(f"[b]Confirm {self.action}[/b]")
            yield Label(
                f"{self.preview.message_count} messages, "
                f"{_human_size(self.preview.total_size)}"
            )
            yield Label("Sample subjects:")
            yield Label(sample_lines)
            with Horizontal():
                yield Button("Confirm", id="confirm", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class InboxCleanerApp(App):
    """The TUI entry point."""

    CSS_PATH = "styles.tcss"
    TITLE = "inboxcleaner"
    BINDINGS: ClassVar[list] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("a", "act('archive')", "Archive"),
        ("t", "act('trash')", "Trash"),
        ("l", "act('label')", "Label"),
        ("u", "act('unsubscribe')", "Unsubscribe"),
    ]

    # Click-to-sort state. None means "use repo's default order (count DESC)".
    _sort_column: str | None = None
    _sort_direction: str | None = None  # "desc" | "asc" | None

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="groups", cursor_type="row")
        with Vertical(id="right-pane"):
            yield DataTable(id="senders", cursor_type="row")
            yield DataTable(id="recent", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        senders = self.query_one("#senders", DataTable)
        senders.add_columns("Email", "Display", "Count")
        recent = self.query_one("#recent", DataTable)
        recent.add_columns("Date", "Subject")
        # Add the groups columns once with fixed widths. Subsequent re-sorts
        # only update labels (sort indicator) and rows — never re-add columns,
        # which is what was causing the rapid-click flicker.
        groups = self.query_one("#groups", DataTable)
        for label, key, width in _GROUP_COLUMNS:
            groups.add_column(label, key=key, width=width)
        self._load_groups()

    def _update_sort_indicators(self) -> None:
        """Mutate the persistent column labels to show the active sort."""
        from rich.text import Text
        from textual.widgets._data_table import ColumnKey

        groups = self.query_one("#groups", DataTable)
        for label, key, _ in _GROUP_COLUMNS:
            indicator = ""
            if self._sort_column == key:
                indicator = " ↓" if self._sort_direction == "desc" else " ↑"
            try:
                groups.columns[ColumnKey(key)].label = Text(label + indicator)
            except KeyError:
                continue
        # Tell Textual the header changed so it repaints just the header row.
        groups.refresh()

    def _load_groups(self) -> None:
        groups = self.query_one("#groups", DataTable)
        prev_gid = self._selected_group_id() if groups.row_count > 0 else None
        groups.clear()  # rows only; columns persist

        conn = _open_db()
        try:
            summaries = repo.groups_with_counts(conn)  # default: count DESC
        finally:
            conn.close()
        if self._sort_column is not None:
            summaries = sorted(
                summaries,
                key=lambda s: _sort_value(s, self._sort_column),
                reverse=(self._sort_direction == "desc"),
            )

        for s in summaries:
            groups.add_row(
                str(s.id), s.name, str(s.message_count),
                _human_size(s.total_size),
                _human_date(s.latest_message_date),
                key=str(s.id),
            )

        self._update_sort_indicators()

        if groups.row_count > 0:
            target_row = 0
            if prev_gid is not None:
                for i, key in enumerate(groups.rows):
                    if key.value == str(prev_gid):
                        target_row = i
                        break
            groups.move_cursor(row=target_row)
            gid = self._selected_group_id()
            if gid is not None:
                self._load_detail_for(gid)

    def on_data_table_header_selected(
        self, event: DataTable.HeaderSelected
    ) -> None:
        if event.data_table.id != "groups":
            return
        col_key = event.column_key.value if event.column_key is not None else None
        if col_key is None:
            return
        if self._sort_column == col_key:
            # Cycle: desc → asc → unsorted → desc
            if self._sort_direction == "desc":
                self._sort_direction = "asc"
            elif self._sort_direction == "asc":
                self._sort_column = None
                self._sort_direction = None
            else:
                self._sort_direction = "desc"
        else:
            self._sort_column = col_key
            self._sort_direction = "desc"
        self._load_groups()

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

    def action_act(self, action_name: str) -> None:
        gid = self._selected_group_id()
        if gid is None:
            self.notify("No group selected.", severity="warning")
            return
        conn = _open_db()
        try:
            preview = actions.preview(
                conn, target_kind="group", target_id=gid
            )
        finally:
            conn.close()

        async def after_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            client = _get_client()
            conn2 = _open_db()
            try:
                if action_name == "archive":
                    count = await actions.archive(
                        client, conn2, target_kind="group", target_id=gid
                    )
                    summary = f"Archived {count} messages."
                elif action_name == "trash":
                    count = await actions.trash(
                        client, conn2, target_kind="group", target_id=gid
                    )
                    summary = f"Trashed {count} messages."
                elif action_name == "label":
                    count = await actions.apply_label(
                        client, conn2,
                        target_kind="group", target_id=gid,
                        label_name="inboxcleaner",
                    )
                    summary = f"Labeled {count} messages as inboxcleaner."
                else:  # unsubscribe
                    result = await actions.unsubscribe(
                        client, conn2, target_kind="group", target_id=gid
                    )
                    summary = (
                        f"Unsubscribe: {result.mailto_sent} sent, "
                        f"{len(result.http_urls)} URLs, "
                        f"{len(result.skipped)} skipped."
                    )
            finally:
                conn2.close()
            self.notify(summary)
            self._load_groups()  # refresh counts

        self.push_screen(
            ConfirmActionModal(action_name, gid, preview),
            after_confirm,
        )

    def action_refresh(self) -> None:
        self._load_groups()


def main() -> None:
    InboxCleanerApp().run()
