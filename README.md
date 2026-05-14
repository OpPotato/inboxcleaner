# inboxcleaner

Local-first tool to scan a Gmail inbox, group senders by company across multiple email addresses, and bulk-act on them (archive, trash, label, unsubscribe).

This is a personal project. The repository is public for visibility but **not accepting external contributions** — please don't open PRs or issues for feature requests.

## Quickstart

```bash
uv sync
uv run inboxcleaner login
uv run inboxcleaner sync
uv run inboxcleaner senders --sort count --limit 50
```

## Status

v1 in development. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the implementation plans.
