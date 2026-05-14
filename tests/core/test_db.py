from inboxcleaner.core.db import connect


def test_connect_applies_pragmas_and_schema(tmp_path):
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    try:
        cur = conn.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0].lower() == "wal"
        cur = conn.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1
        # Schema applied: tables exist
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"account", "sender", "sender_group", "message", "action_log", "sync_lock"} <= tables
    finally:
        conn.close()


def test_connect_creates_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "test.db"
    conn = connect(db_path)
    try:
        assert db_path.exists()
    finally:
        conn.close()
