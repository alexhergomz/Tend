"""A small local web server for the web UI. Only on 127.0.0.1, and every API call needs the key.

The key is made fresh each time the server starts and passed to the browser in
the address (after #, so it is never sent in a request line or logged). Other
websites can't read it, and a request without it is refused. The Host header is
checked too, so a website can't reach the server through a rebound domain name.
"""

import hmac
import json
import mimetypes
import secrets
import sys
import traceback
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from tend import parse
from tend.app import App, UsageError

from . import api, extensions

STATIC = resources.files("tend_web") / "static"
MAX_BODY = 10 * 1024 * 1024


def _json(obj) -> bytes:
    def default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=default).encode()


class Server:
    def __init__(self, app: App, port: int = 0):
        app.tui = True  # messages are collected for the page, not printed
        self.app = app
        self.token = secrets.token_urlsafe(24)
        self.frames: dict[str, str] = {}  # one-time HTML pages from plugins, by a random id
        self.httpd = HTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#key={self.token}"

    def serve(self):
        try:
            self.httpd.serve_forever()
        finally:
            self.httpd.server_close()

    def call(self, method: str, path: str, body: dict, params: dict) -> tuple[int, dict]:
        """Run one API call. Everything runs in one thread, so the database is used safely."""
        app = self.app
        app.store.changed()  # the command line may have changed the data meanwhile
        app.reload()
        app.flash.clear()
        try:
            if path == "/api/ui":
                found, problems = extensions.discover()
                return 200, {"extensions": [e.to_json() for e in found], "problems": problems}
            if path == "/api/ui/run":
                ext, item = extensions.find(body.get("plugin", ""), body.get("item", ""))
                result = extensions.run(ext, item, body.get("task"))
                if result["ok"] and result["format"] == "html":
                    frame = secrets.token_urlsafe(18)
                    self.frames[frame] = result.pop("output")
                    while len(self.frames) > 20:
                        self.frames.pop(next(iter(self.frames)))
                    result["frame"] = f"/frame/{frame}"
                return 200, result
            handler = api.ROUTES.get((method, path))
            if not handler:
                return 404, {"error": f"no {method} {path}"}
            result = handler(app, body, params)
            return 200, {**(result or {}), "messages": [api.plain(m) for m in app.flash]}
        except (UsageError, parse.ParseError, LookupError, ValueError, KeyError) as e:
            return 400, {"error": str(e).strip("'") or e.__class__.__name__,
                         "messages": [api.plain(m) for m in app.flash]}
        except api.NotFound as e:
            return 404, {"error": str(e)}
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return 500, {"error": f"{e.__class__.__name__}: {e}"}

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet: the terminal stays clean
                pass

            def _host_ok(self) -> bool:
                return self.headers.get("Host", "") in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

            def _send(self, status: int, body: bytes, kind: str = "application/json"):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                 "frame-src 'self' data: blob:; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def _api(self, method: str):
                key = self.headers.get("X-Tend-Key", "")
                if not hmac.compare_digest(key.encode(), server.token.encode()):
                    return self._send(403, _json({"error": "missing or wrong key: open the address t web printed"}))
                url = urlparse(self.path)
                params = {k: v[-1] for k, v in parse_qs(url.query).items()}
                body = {}
                if method == "POST":
                    size = int(self.headers.get("Content-Length") or 0)
                    if size > MAX_BODY:
                        return self._send(413, _json({"error": "too big"}))
                    try:
                        body = json.loads(self.rfile.read(size) or b"{}")
                    except json.JSONDecodeError:
                        return self._send(400, _json({"error": "the body should be JSON"}))
                status, result = server.call(method, url.path, body, params)
                self._send(status, _json(result))

            def _static(self):
                name = urlparse(self.path).path.lstrip("/") or "index.html"
                if "/" in name.removeprefix("static/") or ".." in name:
                    return self._send(404, b"not found", "text/plain")
                path = STATIC / name.removeprefix("static/")
                if not path.is_file():
                    return self._send(404, b"not found", "text/plain")
                kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
                if kind.startswith("text/") or kind.endswith(("javascript", "json", "svg+xml")):
                    kind += "; charset=utf-8"
                self._send(200, path.read_bytes(), kind)

            def _frame(self):
                """A plugin's HTML page, once, in a sandbox: it runs, but can't reach Tend or the key."""
                html = server.frames.pop(self.path.removeprefix("/frame/"), None)
                if html is None:
                    return self._send(404, b"gone: open the panel again", "text/plain")
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "sandbox allow-scripts; default-src 'none'; "
                                 "style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: https:")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._host_ok():
                    return self._send(403, b"forbidden", "text/plain")
                if self.path.startswith("/api/"):
                    return self._api("GET")
                if self.path.startswith("/frame/"):
                    return self._frame()
                self._static()

            def do_POST(self):
                if not self._host_ok():
                    return self._send(403, b"forbidden", "text/plain")
                if not self.path.startswith("/api/"):
                    return self._send(404, b"not found", "text/plain")
                self._api("POST")

        return Handler
