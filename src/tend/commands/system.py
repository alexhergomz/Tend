"""Your data and setup: backups, export and import, reminders, features, plugins, help."""

import sys
from datetime import datetime
from pathlib import Path

from rich.markup import escape
from rich.table import Table

from .. import __version__, backup, config, features, fmt, hooks, registry, transfer, ui
from ..app import App, UsageError
from ..registry import command
from ..ui import ACCENT, ACCENT_B, DIM, WARN, console
from ._shared import confirm


# ── your data ───────────────────────────────────────────────────────────
@command("backup", group="Your data", help="save a copy of your data now (one is made every day)")
def cmd_backup(app: App, args):
    path = backup.make(app.store.db, app.cfg, "manual")
    if app.json:
        return app.emit({"path": str(path)})
    app.say(f" [{ACCENT}]✓[/] saved a copy [{DIM}]{escape(str(path))}[/]")
    app.say(f" [{DIM}]t restore lists every copy.[/]")


@command("restore", group="Your data", help="list copies, or go back to one", usage="[number] [--yes]",
         flags=("--yes",), details="Your current data is saved first, so a restore can be undone with another one.")
def cmd_restore(app: App, args):
    found = backup.copies(app.cfg)
    picks = [a for a in args if a.isdigit()]
    if not picks:
        if app.json:
            return app.emit([{"n": i, "path": str(c.path), "kind": c.kind, "made": c.made,
                              "open_tasks": c.open_tasks()} for i, c in enumerate(found, 1)])
        if not found:
            return app.say(f" [{DIM}]No copies yet. One is made every day you use Tend, or now with[/] t backup")
        console.print(f" [bold]Copies of your data[/] [{DIM}]· newest first · "
                      f"{escape(str(backup.folder(app.cfg)))}[/]")
        for i, c in enumerate(found, 1):
            n = c.open_tasks()
            tasks = fmt.count(n, "open task") if n is not None else "can't be read"
            console.print(f"  [{ACCENT_B}]{i:>2}[/]  {c.made:%a %b %d %H:%M}  "
                          f"[{DIM}]{c.kind:<7} {tasks} · {c.size_kb} KB[/]")
        console.print(f"\n [{DIM}]t restore <number> goes back to a copy. Your current data is saved first.[/]")
        return
    n = int(picks[0])
    if not 1 <= n <= len(found):
        raise UsageError(f"no copy {n}. t restore lists them.")
    chosen = found[n - 1]
    if not confirm(app, f"Replace your current data with the copy from {chosen.made:%a %b %d %H:%M}?", args):
        return app.say(f" [{DIM}]Nothing changed.[/]")
    try:
        before = backup.restore(app.store.db, app.cfg, chosen.path)
    except ValueError as e:
        raise UsageError(str(e)) from None
    app.store.changed()
    app.store.mark("restore", f"restored the copy from {chosen.made:%Y-%m-%d %H:%M}")
    if app.json:
        return app.emit({"restored": str(chosen.path), "saved_first": str(before)})
    app.say(f" [{ACCENT}]✓[/] restored the copy from {chosen.made:%a %b %d %H:%M}")
    app.say(f" [{DIM}]Your data from before is saved too. To go back: t restore 1[/]")
    app.bar("next")


@command("export", group="Your data", help="all data as JSON lines", usage="[file]",
         details="Without a file, the data goes to stdout and nothing else is printed.")
def cmd_export(app: App, args):
    files = [a for a in args if not a.startswith("-")]
    if not files or files[0] == "-":
        transfer.export(app.store, sys.stdout)
        return
    path = Path(files[0]).expanduser()
    with path.open("w", encoding="utf-8") as f:
        counts = transfer.export(app.store, f)
    if app.json:
        return app.emit({"path": str(path), **counts})
    app.say(f" [{ACCENT}]✓[/] exported {fmt.count(counts['tasks'], 'task')}, {fmt.count(counts['goals'], 'goal')}, "
            f"{fmt.count(counts['sessions'], 'focus session')} and {fmt.count(counts['events'], 'change')} "
            f"[{DIM}]→ {escape(str(path))}[/]")


@command("import", group="Your data", help="load an export", usage="<file | -> [--replace] [--yes]",
         flags=("--replace", "--yes"),
         details="""Into an empty database: an exact copy. Otherwise the tasks are added, and tasks you already
have are skipped. --replace swaps all your data for the file. A copy is saved first.""")
def cmd_import(app: App, args):
    files = [a for a in args if not a.startswith("-") or a == "-"]
    if not files:
        raise UsageError("usage: t import <file> [--replace]   (- reads from stdin)")
    try:
        if files[0] == "-":
            header, data = transfer.read(sys.stdin)
        else:
            with Path(files[0]).expanduser().open(encoding="utf-8") as f:
                header, data = transfer.read(f)
    except OSError as e:
        raise UsageError(f"can't read {files[0]}: {e.strerror}") from None
    except transfer.TransferError as e:
        raise UsageError(str(e)) from None
    has_data = any(app.store.db.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
                   for t in ("tasks", "goals", "sessions"))
    replace = "--replace" in args or not has_data  # an empty database becomes an exact copy
    if replace and has_data and not confirm(app, "Replace ALL your current data with this file?", args):
        return app.say(f" [{DIM}]Nothing changed.[/]")
    saved = backup.make(app.store.db, app.cfg, "before") if has_data else None
    counts = transfer.replace_all(app.store, header, data) if replace else transfer.add(app.store, data)
    app.store.changed()
    app.store.mark("import", f"import from {files[0]}")
    if app.json:
        return app.emit({"mode": "replace" if replace else "add", **counts,
                         "saved_first": str(saved) if saved else None})
    msg = (f"{'loaded' if replace else 'added'} {fmt.count(counts['tasks'], 'task')}, "
           f"{fmt.count(counts['goals'], 'goal')} and {fmt.count(counts['sessions'], 'focus session')}")
    if counts.get("skipped"):
        msg += f" · {counts['skipped']} already here, skipped"
    app.say(f" [{ACCENT}]✓[/] {msg}")
    if saved:
        app.say(f" [{DIM}]Your data from before is saved. To go back: t restore 1[/]")
    app.bar("next")


# ── setup ───────────────────────────────────────────────────────────────
@command("notify", group="Setup", help="send new reminders", feature="reminders",
         usage="[--install | --uninstall | --test | --dry-run]",
         flags=("--install", "--uninstall", "--test", "--dry-run"),
         details="""Run by a timer: --install sets up a systemd user timer (Linux) or a launchd agent (macOS).
Each reminder is sent once, and none outside the working day.""")
def cmd_notify(app: App, args):
    import subprocess

    from .. import reminders

    every = app.cfg["reminders"]["every_minutes"]
    if "--install" in args:
        try:
            for line in reminders.install(every):
                app.say(f" [{ACCENT}]✓[/] {escape(line)}")
        except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
            raise UsageError(str(e)) from None
        return app.say(f" [{DIM}]Tend now checks every {every} minutes. t notify --test sends a test reminder.[/]")
    if "--uninstall" in args:
        for line in reminders.uninstall() or ["no timer was installed"]:
            app.say(f" [{DIM}]{escape(line)}[/]")
        return
    if "--test" in args:
        ok = reminders.send("Tend", "Reminders work.")
        return app.say(f" [{ACCENT}]✓[/] sent a test reminder" if ok else
                       f" [{WARN}]This system has no notify-send or osascript. Hooks still get reminders.[/]")
    now = datetime.now()
    todo = reminders.pending(app, now)
    quiet = app.cfg["reminders"]["quiet_outside_day"] and not reminders.in_working_day(app, now)
    dry = "--dry-run" in args
    if app.json:
        return app.emit({"quiet": quiet, "reminders": [r.to_json() for r in todo]})
    if quiet and not dry:
        return app.say(f" [{DIM}]Outside the working day: {fmt.count(len(todo), 'reminder')} wait for later.[/]")
    for r in todo:
        if not dry:
            reminders.send(r.title, r.body)
            app.hook("on_remind", app.store.task(r.task_id) if r.task_id else None,
                     title=r.title, body=r.body, key=r.key)
        app.say(f" [{ACCENT}]●[/] [bold]{escape(r.title)}[/] [{DIM}]{escape(r.body)}[/]")
    if not dry:
        reminders.mark_sent(app, todo, now)
    if not todo:
        app.say(f" [{DIM}]Nothing new to remind you of.[/]")


@command("features", group="Setup", help="turn optional parts on and off", usage="[on | off <name> ...]",
         flags=tuple(["on", "off"]),
         details="The core is always on. A feature that is off disappears; its data is kept.")
def cmd_features(app: App, args):
    if len(args) >= 2 and args[0] in ("on", "off"):
        for name in args[1:]:
            if name not in features.FEATURES:
                raise UsageError(f"no feature '{name}'. Features: {', '.join(features.FEATURES)}")
            features.set_enabled(name, args[0] == "on")
        app.cfg = config.load()
        app.say(f" [{ACCENT}]✓[/] {' '.join(args[1:])} turned {args[0]}")
    elif args:
        raise UsageError("usage: t features [on|off <name>...]")
    if app.json:
        return app.emit({n: {"on": app.on(n), "since": v, "what": w, "commands": features.commands_of(n)}
                         for n, (v, w) in features.FEATURES.items()})
    console.print(f" [bold]Features[/] [{DIM}]· the core is always on · t features off <name> removes a part[/]")
    tbl = Table.grid(padding=(0, 2))
    for name, (since, what) in features.FEATURES.items():
        on = app.on(name)
        cmds = ", ".join("t " + c for c in features.commands_of(name))
        style = "bold" if on else DIM
        tbl.add_row(f"  [{ACCENT}]on[/]" if on else f"  [{DIM}]off[/]", f"[{style}]{name}[/]", f"[{DIM}]{since}[/]",
                    what if on else f"[{DIM}]{what}[/]", f"[{DIM}]{cmds}[/]")
    console.print(tbl)
    app.bar("stats")


@command("plugins", group="Setup", help="list plugins and hooks", feature="plugins")
def cmd_plugins(app: App, args):
    found = hooks.list_plugins()
    hook_files = [(e, p) for e in hooks.EVENTS for p in hooks.scripts(e)]
    if app.json:
        return app.emit({"plugins": [{"name": n, "path": p} for n, p in found],
                         "hooks": [{"event": e, "path": str(p)} for e, p in hook_files]})
    console.print(f" [bold]Plugins[/] [{DIM}]· programs named t-<name> on your PATH[/]")
    for name, path in found:
        console.print(f"   t {escape(name):<14}[{DIM}]{escape(path)}[/]")
    if not found:
        console.print(f"   [{DIM}]none[/]")
    console.print(f"\n [bold]Hooks[/] [{DIM}]· {escape(str(hooks.hooks_dir()))}[/]")
    for event, path in hook_files:
        console.print(f"   {event:<16}[{DIM}]{escape(str(path))}[/]")
    if not hook_files:
        console.print(f"   [{DIM}]none · events: {', '.join(hooks.EVENTS)}[/]")


@command("help", key="?", group="Setup", help="all commands, or one in detail", usage="[command]", screen=True)
def cmd_help(app: App, args):
    if args:
        cmd = registry.find(args[0])
        if not cmd or cmd.hidden:
            raise UsageError(f"no command '{args[0]}'. t help lists them all.")
        return ui.command_help(cmd)
    ui.help_screen(lambda c: features.command_enabled(app.cfg, c.name), __version__,
                   config.config_path(), config.data_path(), app.on("plugins") or app.on("hooks"))
