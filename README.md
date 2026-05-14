# inboxcleaner

Local-first tool to scan a Gmail inbox, group senders by company across multiple email addresses, and bulk-act on them (archive, trash, label, unsubscribe).

This is a personal project. The repository is public for visibility but **not accepting external contributions** — please don't open PRs or issues for feature requests.

## Quickstart

~~~bash
uv sync
uv run inboxcleaner setup            # one-time guided Cloud Console setup
uv run inboxcleaner sync             # initial sync; subsequent runs are incremental
uv run inboxcleaner senders --sort count --limit 30
uv run inboxcleaner show <group_id>                          # drill into a group
uv run inboxcleaner trash --group <group_id> --dry-run       # preview
uv run inboxcleaner trash --group <group_id>                 # confirm + execute
~~~

`setup` walks you through creating your own Google Cloud project (so you don't share credentials with the project author) and runs `login` for you. After that, sync and use any of the action commands (`archive`, `trash`, `label --name X`, `unsubscribe`) with `--group ID` or `--sender ID`, plus `--dry-run` and `--yes`.

## Status

v1 in development. See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for the implementation plans.
