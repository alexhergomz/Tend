# Adding your plugin to the web UI

A Tend plugin is any program named `t-<name>` on your PATH. To add it to the web
UI, put a file named `t-<name>.ui.json` next to it. Tend web finds it when it
starts, and when you open **All plugins**.

```
~/.local/bin/
├── t-pushed
└── t-pushed.ui.json
```

The plugin stays a normal program, in any language. The UI runs it with the
arguments you choose, and shows what it prints.

## The file

```json
{
  "title": "Push-backs",
  "panels": [
    {"id": "most", "title": "Most pushed", "run": ["--table"], "format": "table"}
  ],
  "actions": [
    {"id": "history", "title": "Date history", "where": "task", "run": ["{id}"], "format": "text"},
    {"id": "clean", "title": "Clean up", "where": "global", "run": ["--clean"], "format": "text",
     "confirm": "Remove old entries?"}
  ]
}
```

| Field | Meaning |
|---|---|
| `title` | The plugin's name in the UI. |
| `panels` | Pages in the sidebar, under **Plugins**. Each one runs when you open it, and again with **Refresh**. |
| `actions` | Buttons. `"where": "task"` puts the button in every task's details; `"global"` puts it on the **All plugins** page. |
| `id` | Unique within the file. Letters, numbers and dashes. |
| `run` | The arguments for your program, as a list. `{id}` becomes the task's number (actions on a task only). |
| `format` | How the output is shown. See below. |
| `confirm` | Optional, actions only: a question to answer with Yes before the action runs. |

A mistake in the file doesn't stop anything: the **All plugins** page lists it.

## Formats

| Format | Print this | Shown as |
|---|---|---|
| `text` | anything | plain text, in a fixed-width font |
| `markdown` | Markdown | headings (`#`), lists, checkboxes (`- [ ]`, `- [x]`), `**bold**`, `` `code` `` and links |
| `table` | a JSON list of objects, like `[{"task": "#4 reply", "pushed": "2×"}]` | a table in Tend's style; the keys are the column names |
| `html` | a full HTML page | the page, in a sealed-off frame |

Prefer `table` and `markdown`: they look like the rest of Tend, in light and
dark. Use `html` for things those can't show, such as a chart. An `html` page
runs in a sandbox: its scripts run, but it can't reach Tend, its data or the
key, and it can't load anything from other sites. Put everything it needs inside
the page.

## What your program gets

The same as any plugin: the arguments from `run`, and these environment variables.

| Variable | Value |
|---|---|
| `TEND_DB` | path to the SQLite database |
| `TEND_CONFIG` | path to the config file |
| `TEND_VERSION` | Tend's version |

Read data with `t ls --json` (or any command's `--json`) or with SQL. Change data
with `t` commands, so history and undo keep working. The database and JSON are
described in [the data reference](../../docs/data.md), which is stable for all of
Tend 1.x.

Rules for the run:

- Print the result on stdout, in UTF-8. Up to 1 MB is shown.
- Finish within 30 seconds.
- Exit with 0. Any other exit code shows as an error, with what you printed on stderr.
- There is no input: stdin is empty.

## A complete example

`t-pushed` in [`examples/plugins/`](../../examples/plugins/) is about 50 lines of
Python. It has three modes:

```sh
t pushed            # for people in the terminal
t pushed --table    # JSON rows, for the "Most pushed" panel
t pushed 12         # the date history of task 12, for the button on each task
```

And its `t-pushed.ui.json` uses the last two. Copy both files to a folder on your
PATH, restart `t web`, and the page and the button appear.
