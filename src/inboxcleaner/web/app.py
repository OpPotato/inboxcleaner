"""FastAPI app for inboxcleaner's local web UI.

Read-only browsing + bulk actions on top of the same SQLite cache used
by the CLI. Routes are thin: they consult the repo for data and call
core.actions for mutations.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from inboxcleaner.core import repo
from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect

TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)


def create_app() -> FastAPI:
    app = FastAPI(title="inboxcleaner")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        conn = _open_db()
        try:
            account_row = conn.execute(
                "SELECT email, last_sync_at FROM account LIMIT 1"
            ).fetchone()
            message_count = conn.execute(
                "SELECT COUNT(*) AS n FROM message WHERE is_trashed = 0"
            ).fetchone()["n"]
            group_count = conn.execute(
                "SELECT COUNT(*) AS n FROM sender_group"
            ).fetchone()["n"]
            return TEMPLATES.TemplateResponse(
                request,
                "index.html",
                {
                    "account": account_row,
                    "last_sync": account_row["last_sync_at"] if account_row else None,
                    "message_count": message_count,
                    "group_count": group_count,
                },
            )
        finally:
            conn.close()

    @app.get("/groups", response_class=HTMLResponse)
    def groups(
        request: Request,
        sort: str = "count",
        limit: int = 200,
        category: str = "all",
    ) -> HTMLResponse:
        conn = _open_db()
        try:
            summaries = repo.groups_with_counts(conn)
            if category != "all":
                keep_ids = {
                    r["group_id"]
                    for r in conn.execute(
                        """
                        SELECT DISTINCT s.group_id FROM sender s
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

            template = (
                "_groups_table.html"
                if request.headers.get("HX-Request") == "true"
                else "groups.html"
            )
            return TEMPLATES.TemplateResponse(
                request,
                template,
                {"summaries": summaries, "sort": sort, "category": category},
            )
        finally:
            conn.close()

    return app


def _open_db() -> sqlite3.Connection:
    paths = Paths.default()
    paths.ensure_dirs()
    return connect(paths.db)


# Module-level app instance for `uvicorn inboxcleaner.web.app:app` and tests.
app = create_app()
