import os
from dataclasses import dataclass
from pathlib import Path


def _xdg(var: str, default_subdir: str) -> Path:
    base = os.environ.get(var)
    if base:
        return Path(base)
    return Path.home() / default_subdir


@dataclass(frozen=True)
class Paths:
    token: Path
    db: Path
    log: Path
    config_file: Path

    @classmethod
    def default(cls) -> "Paths":
        override = os.environ.get("INBOXCLEANER_HOME")
        if override:
            base = Path(override)
            return cls(
                token=base / "token.json",
                db=base / "inboxcleaner.db",
                log=base / "inboxcleaner.log",
                config_file=base / "config.toml",
            )
        cfg = _xdg("XDG_CONFIG_HOME", ".config") / "inboxcleaner"
        data = _xdg("XDG_DATA_HOME", ".local/share") / "inboxcleaner"
        state = _xdg("XDG_STATE_HOME", ".local/state") / "inboxcleaner"
        return cls(
            token=cfg / "token.json",
            db=data / "inboxcleaner.db",
            log=state / "inboxcleaner.log",
            config_file=cfg / "config.toml",
        )

    def ensure_dirs(self) -> None:
        for p in (self.token, self.db, self.log, self.config_file):
            p.parent.mkdir(parents=True, exist_ok=True)
        if self.token.exists():
            self.token.chmod(0o600)
