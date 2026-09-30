"""Single-keypress input. Falls back to line input when stdin isn't a terminal."""

import os
import select
import sys
import termios
import tty
from contextlib import contextmanager


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


@contextmanager
def raw():
    if not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def getkey(timeout: float | None = None) -> str | None:
    """Read one key while in raw(). Returns None on timeout."""
    fd = sys.stdin.fileno()
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None
    s = os.read(fd, 16).decode(errors="ignore")
    if s.startswith("\x1b"):
        return "esc" if s == "\x1b" else None  # ignore arrow keys etc.
    if s in ("\r", "\n"):
        return "enter"
    return s[:1] or None


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
