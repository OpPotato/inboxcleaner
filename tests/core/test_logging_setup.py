import logging

from inboxcleaner.core.config import Paths
from inboxcleaner.core.logging_setup import configure_logging


def test_configure_logging_writes_to_log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    paths = Paths.default()
    configure_logging(paths)
    logger = logging.getLogger("inboxcleaner.test")
    logger.warning("hello world")
    for h in logging.getLogger("inboxcleaner").handlers:
        h.flush()
    contents = paths.log.read_text()
    assert "hello world" in contents
    assert "WARNING" in contents


def test_configure_logging_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    paths = Paths.default()
    configure_logging(paths)
    handlers_before = list(logging.getLogger("inboxcleaner").handlers)
    configure_logging(paths)
    handlers_after = list(logging.getLogger("inboxcleaner").handlers)
    assert len(handlers_after) == len(handlers_before)
