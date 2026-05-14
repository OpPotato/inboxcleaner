# inboxcleaner

Local-first tool to scan a Gmail inbox, group senders by company across multiple email addresses, and bulk-act on them (archive, trash, label, unsubscribe).

This is a personal project. The repository is public for visibility but **not accepting external contributions** — please don't open PRs or issues for feature requests.

## Quickstart

~~~bash
uv sync
uv run inboxcleaner login                                    # OAuth flow (one-time)
uv run inboxcleaner sync                                     # initial sync; subsequent runs are incremental
uv run inboxcleaner senders --sort count --limit 30          # browse the top groups
uv run inboxcleaner show <group_id>                          # drill into a group
uv run inboxcleaner trash --group <group_id> --dry-run       # preview what would be trashed
uv run inboxcleaner trash --group <group_id>                 # confirm + execute (recoverable from Gmail Trash for 30 days)
~~~

All mutating commands (`archive`, `trash`, `label --name X`, `unsubscribe`) accept `--group ID` or `--sender ID`, plus `--dry-run` (preview only) and `--yes` (skip confirmation).

## Status

v1 in development. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the implementation plans.
