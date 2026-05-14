"""FastAPI app for inboxcleaner's local web UI.

Read-only browsing + bulk actions on top of the same SQLite cache used
by the CLI. Routes are thin: they consult the repo for data and call
core.actions for mutations.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from inboxcleaner.core import actions, repo
from inboxcleaner.core.config import Paths
from inboxcleaner.core.db import connect
from inboxcleaner.core.gmail import GmailClient, RealGmailClient

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

    @app.get("/groups/{group_id}", response_class=HTMLResponse)
    def group_detail(request: Request, group_id: int) -> HTMLResponse:
        conn = _open_db()
        try:
            group = repo.get_group(conn, group_id)
            if group is None:
                raise HTTPException(status_code=404, detail=f"No group with id {group_id}")
            senders = repo.senders_for_group(conn, group_id)
            sender_counts = {
                s.id: conn.execute(
                    "SELECT COUNT(*) AS n FROM message WHERE sender_id = ? AND is_trashed = 0",
                    (s.id,),
                ).fetchone()["n"]
                for s in senders
            }
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
                SELECT id, subject, internal_date FROM message
                WHERE sender_id IN (SELECT id FROM sender WHERE group_id = ?)
                  AND is_trashed = 0
                ORDER BY internal_date DESC LIMIT 5
                """,
                (group_id,),
            ).fetchall()
            return TEMPLATES.TemplateResponse(
                request,
                "group_detail.html",
                {
                    "group": group,
                    "senders": senders,
                    "sender_counts": sender_counts,
                    "msg_count": msg_count,
                    "unsub_count": unsub_count,
                    "recent": recent,
                },
            )
        finally:
            conn.close()

    @app.post("/actions/preview", response_class=HTMLResponse)
    def actions_preview(request: Request, body: _ActionRequest) -> HTMLResponse:
        if body.target_kind not in ("group", "sender"):
            raise HTTPException(status_code=400, detail="invalid target_kind")
        if body.action not in ("archive", "trash", "label", "unsubscribe"):
            raise HTTPException(status_code=400, detail="invalid action")
        conn = _open_db()
        try:
            preview = actions.preview(
                conn,
                target_kind=body.target_kind,  # type: ignore[arg-type]
                target_id=body.target_id,
            )
            return TEMPLATES.TemplateResponse(
                request,
                "_action_modal.html",
                {
                    "preview": preview,
                    "action": body.action,
                    "target_kind": body.target_kind,
                    "target_id": body.target_id,
                },
            )
        finally:
            conn.close()

    @app.post("/actions/execute", response_class=HTMLResponse)
    async def actions_execute(
        request: Request,
        target_kind: str = Form(...),
        target_id: int = Form(...),
        action: str = Form(...),
        label_name: str | None = Form(None),
    ) -> HTMLResponse:
        if target_kind not in ("group", "sender"):
            raise HTTPException(status_code=400, detail="invalid target_kind")
        if action not in ("archive", "trash", "label", "unsubscribe"):
            raise HTTPException(status_code=400, detail="invalid action")
        if action == "label" and not label_name:
            raise HTTPException(status_code=400, detail="label requires label_name")
        client = _get_client()
        conn = _open_db()
        try:
            tk = target_kind  # type: ignore[assignment]
            result_urls: list[str] = []
            if action == "archive":
                count = await actions.archive(
                    client, conn, target_kind=tk, target_id=target_id
                )
                summary = f"Archived {count} messages."
            elif action == "trash":
                count = await actions.trash(
                    client, conn, target_kind=tk, target_id=target_id
                )
                summary = f"Trashed {count} messages."
            elif action == "label":
                count = await actions.apply_label(
                    client,
                    conn,
                    target_kind=tk,
                    target_id=target_id,
                    label_name=label_name,
                )
                summary = f'Labeled {count} messages as "{label_name}".'
            else:  # unsubscribe
                result = await actions.unsubscribe(
                    client, conn, target_kind=tk, target_id=target_id
                )
                result_urls = result.http_urls
                summary = (
                    f"Unsubscribe: {result.mailto_sent} sent, "
                    f"{len(result.http_urls)} URLs to visit, "
                    f"{len(result.skipped)} skipped."
                )
            return TEMPLATES.TemplateResponse(
                request,
                "_action_done.html",
                {
                    "summary": summary,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "result_urls": result_urls,
                },
            )
        finally:
            conn.close()

    return app


def _open_db() -> sqlite3.Connection:
    paths = Paths.default()
    paths.ensure_dirs()
    return connect(paths.db)


def _get_client() -> GmailClient:
    """Build a Gmail client. Monkeypatched in tests."""
    from inboxcleaner.cli.main import _load_creds_or_die

    paths = Paths.default()
    paths.ensure_dirs()
    if not paths.token.exists():
        raise HTTPException(
            status_code=401,
            detail="Not logged in. Run `inboxcleaner login` first.",
        )
    secret = paths.token.parent / "client_secret.json"
    creds = _load_creds_or_die(secret, paths.token)
    return RealGmailClient(creds)


class _ActionRequest(BaseModel):
    target_kind: str  # "group" or "sender"
    target_id: int
    action: str  # "archive" | "trash" | "label" | "unsubscribe"
    label_name: str | None = None


# Module-level app instance for `uvicorn inboxcleaner.web.app:app` and tests.
app = create_app()
