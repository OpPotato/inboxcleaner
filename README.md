# inboxcleaner

Local-first tool to scan a Gmail inbox, group senders by company across multiple email addresses, and bulk-act on them (archive, trash, label, unsubscribe).

This is a personal project. The repository is public for visibility but **not accepting external contributions** — please don't open PRs or issues for feature requests.

## Quickstart

~~~bash
uv sync
uv run inboxcleaner setup            # one-time guided Cloud Console setup
uv run inboxcleaner sync             # initial sync; subsequent runs are incremental
uv run inboxcleaner web              # browse + clean up in your browser (recommended)
# ...or stay in the terminal:
uv run inboxcleaner senders --sort count --limit 30
uv run inboxcleaner trash --group <group_id>
~~~

`setup` walks you through creating your own Google Cloud project (so you don't share credentials with the project author) and runs `login` for you. `inboxcleaner web` then starts a local server on `127.0.0.1:8765` and opens your browser. The CLI commands (`show`, `archive`, `trash`, `label`, `unsubscribe`) still work for terminal-driven cleanup — each accepts `--group ID` or `--sender ID`, plus `--dry-run` and `--yes`.

## Status

v1 in development. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the implementation plans.
