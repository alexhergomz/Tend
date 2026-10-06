"""Plugins add to the web UI with a manifest: `t-<name>.ui.json`, next to the plugin.

    {
      "title": "Push history",
      "panels":  [{"id": "list", "title": "Most pushed", "run": ["--table"], "format": "table"}],
      "actions": [{"id": "md", "title": "Copy as Markdown", "where": "global", "run": [], "format": "markdown"},
                  {"id": "why", "title": "Date history", "where": "task", "run": ["{id}"], "format": "text"}]
    }

A panel is a page in the sidebar; an action is a button, on every task ("task")
or on the whole app ("global"). Both run the plugin with the given arguments
(`{id}` becomes the task number) and show what it prints, as:

    text      plain text
    markdown  headings, lists, checkboxes, bold, code and links
    table     a JSON list of objects, shown as a table in Tend's style
    html      a page of its own, in a sealed-off frame (no access to Tend)

EXTENDING.md, next to this plugin's README, describes the format in full.
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from tend import hooks

FORMATS = ("text", "markdown", "table", "html")
MAX_OUTPUT = 1_000_000  # bytes
TIMEOUT = 30  # seconds


@dataclass
class Extension:
    name: str  # the plugin, as in t-<name>
    program: str
    title: str
    panels: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"name": self.name, "title": self.title, "panels": self.panels, "actions": self.actions}


def _item(raw: dict, kind: str, problems: list[str], where: str) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("id") or not raw.get("title"):
        problems.append(f"{where}: each {kind} needs an id and a title")
        return None
    run = raw.get("run", [])
    fmt_ = raw.get("format", "text")
    if not isinstance(run, list) or not all(isinstance(a, str) for a in run):
        problems.append(f"{where}: 'run' of {raw['id']} should be a list of strings")
        return None
    if fmt_ not in FORMATS:
        problems.append(f"{where}: format of {raw['id']} should be one of {', '.join(FORMATS)}")
        return None
    item = {"id": str(raw["id"]), "title": str(raw["title"]), "run": run, "format": fmt_}
    if kind == "action":
        item["where"] = "task" if raw.get("where") == "task" else "global"
        item["confirm"] = str(raw["confirm"]) if raw.get("confirm") else None
    return item


def discover() -> tuple[list[Extension], list[str]]:
    """Extensions from the plugins on your PATH, and problems with any manifest."""
    found, problems = [], []
    for name, program in hooks.list_plugins():
        manifest = Path(program).with_name(f"t-{name}.ui.json")
        if not manifest.is_file():
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"{manifest.name}: can't be read ({e})")
            continue
        panels = [p for p in (_item(x, "panel", problems, manifest.name) for x in raw.get("panels", [])) if p]
        acts = [a for a in (_item(x, "action", problems, manifest.name) for x in raw.get("actions", [])) if a]
        found.append(Extension(name, program, str(raw.get("title") or name), panels, acts))
    return found, problems


def run(ext: Extension, item: dict, task_id: int | None = None) -> dict:
    """Run a panel or action. Returns {format, output, ok, error}."""
    args = []
    for a in item["run"]:
        if "{id}" in a:
            if task_id is None:
                return {"ok": False, "format": "text", "output": "", "error": "this action needs a task"}
            a = a.replace("{id}", str(int(task_id)))
        args.append(a)
    try:
        done = subprocess.run([*hooks.command(ext.program), *args], env=hooks.plugin_env(), capture_output=True,
                              timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "format": "text", "output": "", "error": f"t {ext.name} took longer than {TIMEOUT} s"}
    except OSError as e:
        return {"ok": False, "format": "text", "output": "", "error": f"can't run t {ext.name}: {e}"}
    output = done.stdout[:MAX_OUTPUT].decode("utf-8", errors="replace")
    result = {"ok": done.returncode == 0, "format": item["format"], "output": output,
              "error": done.stderr[:4000].decode("utf-8", errors="replace").strip() if done.returncode else ""}
    if item["format"] == "table" and result["ok"]:
        try:
            rows = json.loads(output)
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise ValueError
            result["rows"] = rows
        except ValueError:
            result.update(ok=False, error=f"t {ext.name} should print a JSON list of objects for a table")
    return result


def find(name: str, item_id: str) -> tuple[Extension, dict]:
    for ext in discover()[0]:
        if ext.name == name:
            for item in ext.panels + ext.actions:
                if item["id"] == item_id:
                    return ext, item
    raise LookupError(f"no {item_id!r} in plugin {name!r}")
