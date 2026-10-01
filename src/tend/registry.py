"""Every command declares itself here, once: name, key, help, and where it belongs.

Help, the command bar, interactive mode, feature switches, shell completion and
the man page all read from this registry, so they never disagree.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

GROUPS = ["Doing", "Capturing", "Deciding", "Looking", "Your data", "Setup"]


@dataclass
class Command:
    name: str
    fn: Callable
    group: str
    help: str  # one line
    key: str = ""  # one letter: `t <key>`, and the key in interactive mode
    usage: str = ""  # arguments, as in "[id] [--once | --stop]"
    details: str = ""  # a few lines for `t help <command>`
    feature: str | None = None  # the optional feature it belongs to
    screen: bool = False  # interactive mode: show its output on a full screen
    aliases: tuple[str, ...] = ()
    hidden: bool = False  # not listed anywhere (internal commands)
    takes_id: bool = False  # first argument may be a task id (for completion)
    standalone: bool = False  # runs without loading your data: fn(args, json_out)
    flags: tuple[str, ...] = field(default_factory=tuple)  # for completion


COMMANDS: dict[str, Command] = {}


def command(name: str, *, group: str, help: str, **kw):
    """Decorator: register a command function."""
    def wrap(fn):
        COMMANDS[name] = Command(name=name, fn=fn, group=group, help=help, **kw)
        return fn
    return wrap


def _load():
    """Commands register themselves on import; make sure that happened."""
    from . import commands  # noqa: F401


def by_key() -> dict[str, Command]:
    _load()
    return {c.key: c for c in COMMANDS.values() if c.key}


def find(word: str) -> Command | None:
    """A command by name, key or alias."""
    _load()
    if word in COMMANDS:
        return COMMANDS[word]
    for c in COMMANDS.values():
        if word == c.key or word in c.aliases:
            return c
    return None


def listed() -> list[Command]:
    """Visible commands, by group, in the order they were registered."""
    _load()
    return sorted((c for c in COMMANDS.values() if not c.hidden), key=lambda c: GROUPS.index(c.group))
