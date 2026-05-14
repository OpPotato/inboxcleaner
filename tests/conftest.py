import pytest

from inboxcleaner.core.db import connect


@pytest.fixture
def db_conn(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()
