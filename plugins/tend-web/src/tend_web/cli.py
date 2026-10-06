"""`t web`: start the local web UI and open it in your browser."""

import argparse
import sys
import webbrowser

from tend import __version__ as tend_version
from tend import config
from tend.app import App

from . import __version__
from .server import Server


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(prog="t web", description="A calm local web UI for Tend.")
    parser.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (0 picks a free one)")
    parser.add_argument("--no-open", action="store_true", help="don't open the browser")
    parser.add_argument("--version", action="version", version=f"tend-web {__version__} (Tend {tend_version})")
    args = parser.parse_args(argv)
    try:
        app = App()
    except config.ConfigError as e:
        sys.exit(f"Your config file has a problem: {e}\nFix it, or run t doctor.")
    try:
        server = Server(app, args.port)
    except OSError:
        server = Server(app, 0)  # the port is taken: pick a free one
    print(f"Tend is open at {server.url}\nKeep this window open while you use it. Ctrl+C stops it.", flush=True)
    if not args.no_open:
        webbrowser.open(server.url)
    try:
        server.serve()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
