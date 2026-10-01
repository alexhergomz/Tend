"""Single-keypress input, on POSIX terminals and on Windows. Falls back to line input without a terminal."""

import sys
import time
from contextlib import contextmanager

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import msvcrt
else:
    import os
    import select
    import termios
    import tty


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


@contextmanager
def raw():
    """Keys arrive one at a time, without Enter. Nothing to set up on Windows."""
    if WINDOWS or not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _name(s: str) -> str | None:
    if s.startswith("\x1b"):
        return "esc" if s == "\x1b" else None  # arrow keys and the like are ignored
    if s in ("\r", "\n"):
        return "enter"
    if s == "\x03":
        raise KeyboardInterrupt
    return s[:1] or None


def getkey(timeout: float | None = None) -> str | None:
    """Read one key while in raw(). Returns None on timeout."""
    if WINDOWS:
        end = None if timeout is None else time.monotonic() + timeout
        while not msvcrt.kbhit():
            if end is not None and time.monotonic() >= end:
                return None
            time.sleep(0.02)
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # a function or arrow key: two characters, ignored
            msvcrt.getwch()
            return None
        return _name(ch)
    fd = sys.stdin.fileno()
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None
    return _name(os.read(fd, 16).decode(errors="ignore"))


def readkey() -> str:
    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        if not line:
            return "q"
        return line.strip()[:1].lower() or "enter"
    with raw():
        while (k := getkey()) is None:
            pass
    return k
