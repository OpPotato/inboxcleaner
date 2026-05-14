CREATE TABLE IF NOT EXISTS account (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    history_id    TEXT,
    last_sync_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sender_group (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    created_by    TEXT NOT NULL CHECK (created_by IN ('auto', 'manual')),
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS sender (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL,
    display_name  TEXT,
    domain        TEXT NOT NULL,
    group_id      INTEGER REFERENCES sender_group(id),
    UNIQUE(email, display_name)
);
CREATE INDEX IF NOT EXISTS idx_sender_group  ON sender(group_id);
CREATE INDEX IF NOT EXISTS idx_sender_domain ON sender(domain);

CREATE TABLE IF NOT EXISTS message (
    id               TEXT PRIMARY KEY,
    account_id       INTEGER NOT NULL REFERENCES account(id),
    thread_id        TEXT NOT NULL,
    sender_id        INTEGER NOT NULL REFERENCES sender(id),
    subject          TEXT,
    internal_date    INTEGER NOT NULL,
    size_estimate    INTEGER,
    category         TEXT,
    labels           TEXT NOT NULL DEFAULT '[]',
    list_unsubscribe TEXT,
    is_trashed       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_message_sender ON message(sender_id);
CREATE INDEX IF NOT EXISTS idx_message_date   ON message(internal_date DESC);

CREATE TABLE IF NOT EXISTS action_log (
    id             INTEGER PRIMARY KEY,
    performed_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    action_type    TEXT NOT NULL,
    target_kind    TEXT NOT NULL,
    target_id      INTEGER NOT NULL,
    message_count  INTEGER NOT NULL,
    details        TEXT
);

CREATE TABLE IF NOT EXISTS sync_lock (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    pid         INTEGER,
    started_at  TIMESTAMP
);
