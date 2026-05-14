import os
from pathlib import Path
from inboxcleaner.core.config import Paths


def test_default_paths_match_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("INBOXCLEANER_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    p = Paths.default()
    assert p.token == tmp_path / "cfg" / "inboxcleaner" / "token.json"
    assert p.db == tmp_path / "data" / "inboxcleaner" / "inboxcleaner.db"
    assert p.log == tmp_path / "state" / "inboxcleaner" / "inboxcleaner.log"


def test_override_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path))
    p = Paths.default()
    assert p.db == tmp_path / "inboxcleaner.db"
    assert p.token == tmp_path / "token.json"
    assert p.log == tmp_path / "inboxcleaner.log"


def test_ensure_dirs_creates_parents(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOXCLEANER_HOME", str(tmp_path / "x" / "y"))
    p = Paths.default()
    p.ensure_dirs()
    assert p.db.parent.exists()
    assert p.token.parent.exists()
    assert p.log.parent.exists()
