"""Interactive mode: one task on screen, the command bar pinned below it, single keypresses."""

from . import commands, keys, ui
from .app import App, UsageError
from .ui import ACCENT, DIM, WARN, console

SCREENS = {"l", "g", "w", "?", "p", "c", "v", "r", "t", "i"}  # these show a full screen, then wait for a key


def run(app: App):
    console.show_cursor(False)
    try:
        _loop(app)
    finally:
        console.show_cursor(True)
    done = len(app.store.done_since(app.today))
    if done:
        console.print(f" [{ACCENT}]✓[/] {done} done today")


def _loop(app: App):
    while True:
        app.reload()
        ranked = app.ranked()
        top = ranked[0] if ranked else None
        app.store.set_meta("current", top.task.id if top else None)
        counts = app.status(ranked)

        console.clear()
        ui.status_line(counts)
        console.print()
        for msg in app.flash:
            console.print(msg)
        app.flash.clear()
        if top:
            console.print(ui.card(top, app.today))
        else:
            console.print(f" [{DIM}]Nothing to do. Press[/] a [{DIM}]to capture something.[/]")
        console.print()
        ui.footer(app.footer_keys("next" if top else "empty", counts) + ["q"], cli=False)

        k = keys.readkey()
        if k in ("q", "esc"):
            console.clear()
            return
        fn = commands.lookup(k)
        if not fn:
            continue
        try:
            if k in SCREENS:
                console.clear()
                app.tui, app.nested = False, True  # full screens print directly, no command bar
                try:
                    fn(app, [])
                finally:
                    app.tui, app.nested = True, False
                console.print(f"\n [{DIM}]any key to go back[/]")
                keys.readkey()
            else:
                fn(app, [])
        except UsageError as e:
            app.flash.append(f" [{WARN}]{e}[/]")
