"""The Windows-only paths, tested on any system with stand-ins for what Windows provides."""

import sys
from pathlib import Path

from tend import config, hooks, keys


class FakeConsole:
    """Stands in for msvcrt: a queue of keys from the Windows console."""

    def __init__(self, typed: str):
        self.typed = list(typed)

    def kbhit(self):
        return bool(self.typed)

    def getwch(self):
        return self.typed.pop(0)


def test_keys_on_windows(monkeypatch):
    monkeypatch.setattr(keys, "WINDOWS", True)
    monkeypatch.setattr(keys, "msvcrt", FakeConsole("d\r\xe0Hq\x1b"), raising=False)
    got = [keys.getkey(0.1) for _ in range(5)]
    assert got == ["d", "enter", None, "q", "esc"]  # \xe0 H is an arrow key: ignored
    assert keys.getkey(0.05) is None  # nothing typed: times out


def test_windows_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    for var in ("TEND_CONFIG", "TEND_DB", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert config.config_path() == tmp_path / "Roaming" / "tend" / "config.toml"
    assert config.data_path() == tmp_path / "Local" / "tend" / "tend.db"


def test_windows_hooks_and_plugins(monkeypatch, tmp_path):
    monkeypatch.setattr(hooks, "WINDOWS", True)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    for name in ("on_done.bat", "on_add.py", "notes.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert hooks.runnable(tmp_path / "on_done.bat") and hooks.runnable(tmp_path / "on_add.py")
    assert not hooks.runnable(tmp_path / "notes.txt")
    assert hooks.command(Path("C:/h/on_add.py"))[0] == sys.executable
    assert hooks.command(Path("C:/h/on_done.bat"))[:2] == ["cmd", "/c"]
    (tmp_path / "t-hello.py").write_text("print('hi')", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert hooks.find_plugin("hello") == str(tmp_path / "t-hello.py")
