import contextlib
import logging

import pytest

from inboxcleaner.core.db import connect


@pytest.fixture
def db_conn(tmp_path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def _clear_inboxcleaner_logger():
    logger = logging.getLogger("inboxcleaner")
    for h in list(logger.handlers):
        logger.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()
    if hasattr(logger, "_inboxcleaner_configured"):
        delattr(logger, "_inboxcleaner_configured")


@pytest.fixture(autouse=True)
def _reset_inboxcleaner_logger():
    """Clear handlers + idempotency flag on the inboxcleaner namespace logger between tests.

    Without this, configure_logging() from one test leaks a RotatingFileHandler
    into the next, breaking test isolation.
    """
    _clear_inboxcleaner_logger()
    yield
    _clear_inboxcleaner_logger()
