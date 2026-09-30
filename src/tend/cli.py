"""Entry point. `t <command>`, `t <key>`, `t <any text>` to capture, or `t` alone for interactive mode."""

import sys

from . import commands, keys, parse, tui
from .app import App, UsageError
from .ui import WARN, console


def main(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_out = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv and argv[0] in ("-h", "--help"):
        argv = ["help"]

    try:
        if not argv:
            if keys.interactive() and not json_out:
                return tui.run(App(tui=True))
            argv = ["next"]
        app = App(json_out=json_out)
        fn = commands.lookup(argv[0])
        if fn:
            fn(app, argv[1:])
        else:
            commands.cmd_add(app, argv)  # anything that isn't a command is a new task
    except (UsageError, parse.ParseError) as e:
        console.print(f" [{WARN}]{e}[/]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print()
        sys.exit(130)
