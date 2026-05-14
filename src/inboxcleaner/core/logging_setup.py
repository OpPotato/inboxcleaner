import logging
from logging.handlers import RotatingFileHandler

from inboxcleaner.core.config import Paths

_CONFIGURED_FLAG = "_inboxcleaner_configured"


def configure_logging(paths: Paths, level: int = logging.INFO) -> None:
    """Set up rotating-file logging for the `inboxcleaner` namespace.

    Idempotent — repeated calls are no-ops.
    """
    root = logging.getLogger("inboxcleaner")
    if getattr(root, _CONFIGURED_FLAG, False):
        return
    paths.ensure_dirs()
    handler = RotatingFileHandler(
        paths.log, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)
    setattr(root, _CONFIGURED_FLAG, True)
