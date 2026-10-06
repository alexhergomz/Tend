"""The web UI plugin: a real server on a free port, talked to like the page does."""

import json
import os
import queue
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def web(tmp_path, monkeypatch):
    """Start the server in its own thread (it owns the database, as in real use)."""
    monkeypatch.setenv("TEND_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("TEND_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.setenv("TEND_HOOKS", str(tmp_path / "hooks"))
    started = queue.Queue()

    def run():
        from tend.app import App
        from tend_web.server import Server

        server = Server(App(), 0)
        started.put(server)
        server.serve()

    threading.Thread(target=run, daemon=True).start()
    server = started.get(timeout=10)
    yield Client(server)
    server.httpd.shutdown()


class Client:
    def __init__(self, server):
        self.server, self.base = server, f"http://127.0.0.1:{server.port}"

    def call(self, path, body=None, key=True, host=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode())
        if key:
            req.add_header("X-Tend-Key", self.server.token)
        if host:
            req.add_header("Host", host)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, json.loads(raw) if raw.startswith(b"{") else {"text": raw.decode()}

    def get(self, path, **kw):
        return self.call(path, **kw)

    def post(self, path, body, **kw):
        return self.call(path, body, **kw)


def test_the_page_and_its_files_are_served(web):
    for path, kind in (("/", "text/html"), ("/static/app.js", "javascript"), ("/static/style.css", "text/css")):
        with urllib.request.urlopen(web.base + path) as r:
            assert kind in r.headers["Content-Type"]
            assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_api_needs_the_key_and_the_right_host(web):
    assert web.get("/api/state", key=False)[0] == 403
    assert web.get("/api/state", host="evil.example")[0] == 403  # a rebound domain name
    assert web.get("/api/state")[0] == 200
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(web.base + "/../../etc/passwd")


def test_capture_act_and_undo(web):
    status, data = web.post("/api/tasks", {"text": "pay rent due:tom v:3 s:S"})
    assert status == 200 and data["messages"] == ["Added pay rent"]
    st = web.get("/api/state")[1]
    top = st["queue"][0]
    assert top["title"] == "pay rent" and top["rule"] == 1 and {"text": "due tomorrow", "tone": "warn"} in top["chips"]
    assert web.post("/api/act", {"id": top["id"], "action": "done"})[1]["messages"][-1].startswith("✓ pay rent")
    assert web.get("/api/state")[1]["queue"] == []
    web.post("/api/undo", {})
    assert web.get("/api/state")[1]["queue"][0]["title"] == "pay rent"


def test_parse_preview_matches_the_command_line(web):
    p = web.get("/api/parse?text=" + urllib.request.quote("call mom +family e:20m @low"))[1]
    assert p["title"] == "call mom" and [c["text"] for c in p["chips"]] == ["family", "~20m", "low energy"]
    assert "can't read date" in web.get("/api/parse?text=x%20due:someday")[1]["error"]


def test_triage_split_wait_resolve_goals_focus(web):
    web.post("/api/tasks", {"text": "renew passport"})
    st = web.get("/api/state")[1]
    tid = st["inbox"][0]["id"]
    web.post("/api/triage", {"id": tid, "value": 3, "size": "L", "date": "+10d", "soft": True})
    t = web.get(f"/api/task?id={tid}")[1]
    assert (t["value"], t["size"]) == (3, "L") and t["aim"]
    web.post("/api/split", {"id": tid, "steps": ["find the form", "", "book photo e:20m"]})
    assert [s["title"] for s in web.get(f"/api/task?id={tid}")[1]["steps"]] == ["find the form", "book photo"]
    step = web.get(f"/api/task?id={tid}")[1]["steps"][0]["id"]
    web.post("/api/act", {"id": step, "action": "wait", "until": "+3d"})
    assert web.get(f"/api/task?id={step}")[1]["stage"] == "waiting"
    web.post("/api/goals", {"name": "Admin stuff", "weekly": "2h", "why": "less stress"})
    assert web.get("/api/state")[1]["goals"][0] == {"name": "admin-stuff", "weekly_min": 120, "why": "less stress",
                                                   "week_min": 0}
    web.post("/api/focus/start", {"id": tid + 2})
    web.post("/api/focus/end", {"id": tid + 2, "minutes": 25, "mode": "pomo", "done": True})
    wins = web.get("/api/wins")[1]
    assert wins["focused_min"] == 25 and wins["done"][0]["title"] == "book photo"


def test_bad_input_is_a_message(web):
    status, data = web.post("/api/tasks", {"text": "x due:32nd"})
    assert status == 400 and "day of the month" in data["error"]
    assert web.post("/api/act", {"id": 999, "action": "done"})[0] == 400
    assert web.post("/api/nothing", {})[0] == 404


def test_the_command_line_and_the_page_see_the_same_data(web, tmp_path):
    env = {**os.environ}
    subprocess.run([sys.executable, "-m", "tend", "write", "report", "v:3", "s:S"], env=env, check=True,
                   capture_output=True)
    assert web.get("/api/state")[1]["queue"][0]["title"] == "write report"


def test_settings_plan_review_export(web):
    web.post("/api/tasks", {"text": "a task v:2 s:M"})
    s = web.get("/api/settings")[1]
    assert {f["name"] for f in s["features"]} >= {"states", "planning"} and s["doctor"]
    assert "blocks" in web.get("/api/plan?days=7")[1]
    assert "empty_goals" in web.get("/api/review")[1]
    exported = web.get("/api/export")[1]["content"]
    assert exported.startswith('{"format": "tend-export"')


def _plugin(folder, name, code, manifest):
    if sys.platform == "win32":
        (folder / f"t-{name}.py").write_text(code, encoding="utf-8")
    else:
        path = folder / f"t-{name}"
        path.write_text(f"#!{sys.executable}\n{code}", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    (folder / f"t-{name}.ui.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_plugins_add_panels_and_buttons(web, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _plugin(bin_dir, "demo", "import sys, json\nargs = sys.argv[1:]\n"
            "if args == ['--rows']: print(json.dumps([{'a': 1, 'b': 'two'}]))\n"
            "elif args == ['--page']: print('<h1>hello</h1><script>1</script>')\n"
            "else: print('task', args)\n",
            {"title": "Demo", "panels": [{"id": "rows", "title": "Rows", "run": ["--rows"], "format": "table"},
                                         {"id": "page", "title": "Page", "run": ["--page"], "format": "html"}],
             "actions": [{"id": "show", "title": "Show", "where": "task", "run": ["{id}"], "format": "text"},
                         {"title": "no id"}]})
    (bin_dir / "t-broken.ui.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    ui = web.get("/api/ui")[1]
    demo = next(e for e in ui["extensions"] if e["name"] == "demo")
    assert [p["id"] for p in demo["panels"]] == ["rows", "page"] and [a["id"] for a in demo["actions"]] == ["show"]
    assert any("each action needs an id" in p for p in ui["problems"])

    assert web.post("/api/ui/run", {"plugin": "demo", "item": "rows"})[1]["rows"] == [{"a": 1, "b": "two"}]
    assert web.post("/api/ui/run", {"plugin": "demo", "item": "show", "task": 7})[1]["output"].strip() == "task ['7']"
    page = web.post("/api/ui/run", {"plugin": "demo", "item": "page"})[1]
    assert "output" not in page and page["frame"].startswith("/frame/")
    with urllib.request.urlopen(web.base + page["frame"]) as r:  # served once, sandboxed
        assert b"<h1>hello</h1>" in r.read() and "sandbox allow-scripts" in r.headers["Content-Security-Policy"]
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(web.base + page["frame"])
