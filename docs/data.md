# Data reference

**Version 1** · database schema 4 · export format 1 · Tend 0.8

This page describes everything a plugin, hook or script can rely on: the
database, the JSON output, the export format, hook payloads and the plugin
environment. Until 1.0 these can still change. Each change is listed in the
release notes, and the database is migrated automatically.

## Database

One SQLite file. `t help` shows its path, and so does `TEND_DB` in plugins and hooks.
Dates are ISO strings (`2026-10-02`). Times are local ISO strings without a
time zone (`2026-10-02T14:30:00`).

Read the database freely. If you write to it, use `t` commands or `t import`
when you can: they keep the history in `events` and undo working.

### `tasks`

| Column | Type | Meaning |
|---|---|---|
| `id` | integer | Task number, as shown in `#12` |
| `title` | text | |
| `goal` | text | Goal name, or empty |
| `parent` | integer | The task this one was split from |
| `value` | 1–3 | nice to have · matters · really matters. Empty: not triaged |
| `size` | `S` `M` `L` | Empty: not triaged |
| `estimate_min` | integer | Estimate in minutes, if given |
| `due` | date | Hard deadline |
| `aim` | date | Soft target |
| `start_after` | date | Hidden until this date. For a waiting task: the date it comes back |
| `status` | `open` `done` `dropped` | |
| `stage` | `todo` `started` `waiting` | Where an open task is. Kept after it is done |
| `slips` | integer | Quiet rollovers of the soft target since the last decision |
| `skip_date` | date | The day it was skipped |
| `created` | time | |
| `done_at` | time | When it was done or dropped |
| `energy` | `high` `low` | Empty: any time |
| `first_due` | date | The first hard deadline it ever had |
| `first_aim` | date | The first soft target it ever had |
| `pushes` | integer | How many times a date moved later. Never reset |
| `started_at` | time | The first time it was started |
| `repeat` | text | Repeat rule, as written after `every:` (`mon,thu`, `2w`, `1st`) |
| `series` | integer | For copies of a repeating task: the id of the first one |

A person sees one **state**: `stage` while `status` is `open`, else `status`.

### `goals`

| Column | Type | Meaning |
|---|---|---|
| `name` | text | Lowercase, as in `+thesis` |
| `weekly_min` | integer | Weekly target in minutes. 0: no target |
| `why` | text | Optional reason |
| `created` | time | |

### `sessions`

One row per focus timer session.

| Column | Type | Meaning |
|---|---|---|
| `task_id` | integer | |
| `start`, `end` | time | |
| `mode` | `pomo` `flow` `box` | |
| `minutes` | real | Focused minutes, without pauses and breaks |

### `events`

Every change to a task, in order.

| Column | Type | Meaning |
|---|---|---|
| `ts` | time | |
| `kind` | text | `add`, `done`, `edit`, `status`, `rollover`, … |
| `summary` | text | One line for people |
| `changes` | JSON | A list of `{"table": "tasks", "id", "before", "after"}`. `before` is empty for a new task. Each side is a full row |
| `undone` | 0 or 1 | 1 after `t undo` |

`import` and `restore` entries have no changes. They mark the point where the
data was replaced or added to, and `t undo` stops there.

### `meta`

Small values Tend keeps for itself, such as the last review date. Not stable.

## JSON output

Add `--json` to any command. Times are ISO strings.

| Command | Output |
|---|---|
| `t next` | One ranked task, or `null` |
| `t ls` | A list of ranked tasks, in queue order |
| `t add`, `t edit`, `t done`, `t start`, `t wait`, `t status` | The task after the change |
| `t plan`, `t gantt` | `{"blocks", "events", "late", "corrections"}` |
| `t stats` | `{"time", "soft", "hard", "start_to_done", "pushes"}` |
| `t goals` | A list of goals with `this_week_min` |
| `t wins` | `{"since", "done", "focused_min"}` |
| `t features` | Each feature with `on`, `since`, `what`, `commands` |
| `t plugins` | `{"plugins", "hooks"}` |
| `t restore` | A list of copies with `n`, `path`, `kind`, `made`, `open_tasks` |
| `t notify` | `{"quiet", "reminders"}`, each reminder with `key`, `title`, `body`, `task_id`. Shows what is pending, sends nothing |

A **ranked task** is a task row plus:

| Field | Meaning |
|---|---|
| `rule` | 1 deadline at risk · 2 big rock · 3 WSJF |
| `score` | `(value + urgency) / size` |
| `urgency` | 1–3 |
| `slack_days` | Slack before the hard deadline, or `null` |
| `reason` | The line shown under the task |

## Export format

`t export` writes JSON lines. The first line is a header:

```json
{"format": "tend-export", "format_version": 1, "app_version": "0.7.0", "schema": 3, "exported_at": "2026-10-02T10:00:00"}
```

Every other line is one row: `{"table": "tasks", "row": {...}}`. Tables come in
this order: `goals`, `tasks`, `sessions`, `events`, `meta`. Rows have the
columns above.

`t import` accepts files with missing columns, which get their default. Only
`id`, `title` and `created` are required for a task. It refuses a file from a
newer Tend. The importers in `examples/plugins/` write this format, so you can
use them as a starting point for your own.

## Plugins

A program named `t-<name>` on your PATH runs as `t <name>`. It gets the
arguments, and these environment variables:

| Variable | Value |
|---|---|
| `TEND_DB` | Path to the database |
| `TEND_CONFIG` | Path to the config file |
| `TEND_VERSION` | Tend's version |

If you type `--json`, it is passed on to the plugin.

## Hooks

An executable file in `~/.config/tend/hooks/` named after an event, or any
executable file in `hooks/<event>.d/`. It gets the same environment as plugins,
and one JSON object on stdin:

```json
{"event": "on_done", "time": "2026-10-02T10:00:00", "task": {...}}
```

| Event | Extra fields |
|---|---|
| `on_add`, `on_done`, `on_drop`, `on_skip` | `task` |
| `on_status` | `task`, `old`, `new` (states) |
| `on_focus_start` | `task`, `mode` |
| `on_focus_end` | `task`, `mode`, `minutes`, `outcome` (`done` or `stop`) |
| `on_review` | none (`task` is `null`) |
| `on_remind` | `task` (or `null`), `title`, `body`, `key` |
| `on_change` | `kind`, `summary`, `changes` (as in `events`) |

Hooks run in the background, after the change is saved. Their output goes to
`hooks.log` next to the database.
