# Tend web

A calm local web UI for [Tend](../../README.md), as a plugin. On hard days, big
buttons can be easier than remembering commands. Run `t web` and Tend opens in
your browser.

![The one next task, with big buttons](https://raw.githubusercontent.com/alexhergomz/Tend/main/plugins/tend-web/docs/now.png)

It is the same Tend: the same three rules, the same plan, the same data. A
change you make in the browser shows up in the terminal, and the other way round.

## Install

Tend web is a separate package, so Tend itself stays small. Install it next to
Tend:

```sh
pipx inject tend-cli tend-web --include-apps      # if you installed Tend with pipx
uv tool install tend-cli --with-executables-from tend-web   # with uv
```

From the source folder:

```sh
uv tool install --editable . --with-editable ./plugins/tend-web --with-executables-from tend-web
```

This adds the program `t-web`, which Tend runs as `t web`. Check it with
`t plugins`. Plugins must be on (`t features on plugins`); they are by default.

## Use

```sh
t web               # opens http://127.0.0.1:8765 in your browser
t web --port 9000   # another port (0 picks a free one)
t web --no-open     # print the address, don't open the browser
```

Keep the terminal window open while you use it. Ctrl+C stops it.

| Page | What it does |
|---|---|
| **Now** | The one next task and why, with **Focus** and **Done**. Skip, split, wait and drop are one click away. |
| **Queue** | Every task in order, with the reason for its place. Click one for details and changes. |
| **Inbox** | New tasks, one at a time: three questions, each one click. |
| **Slipped** | Tasks whose date passed: do it today, pick a new date, split, or drop. |
| **Day plan** and **Week** | Today's schedule around your calendar, and the next 7 or 14 days as a chart. |
| **Goals** | Weekly progress, targets, and new goals. |
| **Wins**, **Patterns** | What you finished, and what Tend learned about your estimates and dates. |
| **Weekly review** | The seven steps, on one page. |
| **Settings** | Theme, feature switches, backups, export and import, reminders, and the check-up from `t doctor`. |

The box at the top adds a task from any page. It shows what it understood as you
type, so `call mom due:fri e:20m` shows "due Fri" and "~20m" before you press Enter.

**Focus** opens a full-screen timer: Pomodoro, Flow or Timebox, the same as
`t focus`. It plays a soft sound and shows a notification when a phase ends.

![The focus timer](https://raw.githubusercontent.com/alexhergomz/Tend/main/plugins/tend-web/docs/focus.png)

Every action shows a short notice with **Undo**. The keys are the same as in
interactive mode: `n` now, `l` queue, `f` focus, `d` done, `s` skip, `x` split,
`h` wait, `k` drop, `u` undo, `a` or `/` to add, `?` for the full list.

The look follows your system's light or dark setting. The ◐ button switches it.

| | |
|---|---|
| ![The week chart](https://raw.githubusercontent.com/alexhergomz/Tend/main/plugins/tend-web/docs/week.png) | ![Sorting the inbox](https://raw.githubusercontent.com/alexhergomz/Tend/main/plugins/tend-web/docs/inbox.png) |
| ![Dark theme](https://raw.githubusercontent.com/alexhergomz/Tend/main/plugins/tend-web/docs/dark.png) | ![A panel from a plugin](https://raw.githubusercontent.com/alexhergomz/Tend/main/plugins/tend-web/docs/plugin.png) |

## Private by design

- The server only listens on your own computer (`127.0.0.1`). Nothing is sent
  anywhere, and the page loads nothing from the internet.
- Every start makes a new secret key, which `t web` puts in the address it opens.
  A request without the key is refused, so other websites in your browser can't
  read or change your tasks.
- Requests for any other host name are refused too, which blocks a trick called
  DNS rebinding.
- HTML from plugins runs in a sealed-off frame with no access to Tend or the key.

## Add your plugin to the UI

Any Tend plugin can add a page to the sidebar, or a button on every task, with a
small JSON file next to it. [EXTENDING.md](EXTENDING.md) explains how. The
examples in [`examples/plugins/`](../../examples/plugins/) do it: `t-pushed`
adds a "Most pushed" page and a "Date history" button, and `t-md` adds a
"Checklist" page.

## Versions

Tend web uses Tend's own Python code to be fast, so each version works with a
range of Tend versions: 1.0 works with Tend 1.1 and 1.2. Third-party plugins
should use Tend's stable interfaces instead (`--json`, the database and hooks).

| Version | What |
|---|---|
| 1.0.0 | First release: every Tend feature, plugin panels and buttons, light and dark |

MIT license.
