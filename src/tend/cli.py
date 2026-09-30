"""Entry point. `t <command>`, `t <key>`, `t <any text>` to capture, or `t` alone for interactive mode."""

import subprocess
import sys

from . import commands, hooks, keys, parse, tui
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
        fn = commands.lookup(argv[0])
        if not fn and (plugin := hooks.find_plugin(argv[0])):
            args = argv[1:] + (["--json"] if json_out else [])
            sys.exit(subprocess.run([plugin, *args], env=hooks.plugin_env()).returncode)
        app = App(json_out=json_out)
        if fn:
            fn(app, argv[1:])
        else:
            commands.cmd_add(app, argv)  # anything that isn't a command or plugin is a new task
    except (UsageError, parse.ParseError) as e:
        console.print(f" [{WARN}]{e}[/]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print()
        sys.exit(130)
