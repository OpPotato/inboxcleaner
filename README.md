# inboxcleaner

Local-first tool to scan a Gmail inbox, group senders by company across multiple email addresses, and bulk-act on them (archive, trash, label, unsubscribe).

This is a personal project. The repository is public for visibility but **not accepting external contributions** — please don't open PRs or issues for feature requests.

## Quickstart

~~~bash
uv sync
uv run inboxcleaner setup            # one-time guided Cloud Console setup
uv run inboxcleaner sync             # initial sync; subsequent runs are incremental
uv run inboxcleaner web              # browse + clean up in your browser
uv run inboxcleaner tui              # ...or in your terminal (keyboard-driven)
# ...or stay in the CLI:
uv run inboxcleaner senders --sort count --limit 30
uv run inboxcleaner trash --group <group_id>
~~~

Three frontends share the same SQLite cache and OAuth credentials. `web` is mouse-friendly with an HTMX confirm modal; `tui` is keyboard-driven (`a/t/l/u` for archive/trash/label/unsubscribe, `r` refresh, `q` quit); the CLI commands are best for scripting. `setup` walks you through creating your own Google Cloud project (no shared developer credentials) and runs `login` for you.

## Status

v1 in development. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the implementation plans.
