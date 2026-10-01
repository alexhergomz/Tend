"""Entry point: `t <command>`, `t <key>`, `t <any text>` to capture, or `t` alone for interactive mode."""

import sys

from . import __version__, config, hooks, keys, parse, registry
from .ui import WARN, console

USAGE_FLAGS = ("-h", "--help")


def main(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_out = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv[:1] in (["--version"], ["-V"]):
        return print(f"Tend {__version__}")
    if argv[:1] and argv[0] in USAGE_FLAGS:
        argv = ["help"]

    from . import commands, tui
    from .app import App, UsageError

    try:
        if len(argv) >= 2 and argv[1] in USAGE_FLAGS and registry.find(argv[0]):
            argv = ["help", argv[0]]  # t <command> --help
        if not argv:
            if keys.interactive() and not json_out:
                return tui.run(App(tui=True))
            argv = ["next"]
        app = App(json_out=json_out)
        fn = commands.lookup(argv[0], app)
        if not fn and app.on("plugins") and (plugin := hooks.find_plugin(argv[0])):
            import subprocess

            args = argv[1:] + (["--json"] if json_out else [])
            sys.exit(subprocess.run([plugin, *args], env=hooks.plugin_env()).returncode)
        if fn:
            fn(app, argv[1:])
        else:
            commands.capture.cmd_add(app, argv)  # anything that isn't a command or plugin is a new task
    except (UsageError, parse.ParseError) as e:
        console.print(f" [{WARN}]{e}[/]")
        sys.exit(1)
    except config.ConfigError as e:
        console.print(f" [{WARN}]Your config file has a problem:[/] {e}\n"
                      " Fix it, or run t doctor for a full check.")
        sys.exit(2)
    except KeyboardInterrupt:
        console.print()
        sys.exit(130)
