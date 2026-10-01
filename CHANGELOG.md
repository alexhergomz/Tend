# Changelog

All notable changes to Tend. The format follows [Keep a Changelog](https://keepachangelog.com),
and versions follow [Semantic Versioning](https://semver.org). From 1.0 on, the
interfaces listed under "Stability" in the README only change in a new major version.

## 1.0.0 · 2026-10-01

The first stable release. No new commands: this release makes Tend ready to rely on.

### Added
- Stability promise for the database, JSON output, export format, hooks and plugins
  ([docs/data.md](docs/data.md#stability)).
- Man page (`docs/t.1`), made from the same source as `t help`.
- Tests that open a database made by every earlier release and check that nothing is lost.
- Packaged for PyPI as `tend-cli` (the command is still `t`).

### Changed
- The data reference is version 1.0.
- A step of a split task has the deadline of the task it came from, if that is earlier.
  Ranked tasks in `--json` have a new `deadline` field.
- Monthly and yearly repeats keep the day of the first one: "every month" from Jan 31
  goes Feb 28, Mar 31, Apr 30.

### Fixed
- A hard deadline at risk was hidden when its task was waiting for a later date, had an
  `after:` date, or had been split into steps. Now it always shows (rule 1).
- With a feature turned off, changing a task could erase that feature's data (a repeat
  rule, an energy tag, a waiting state).
- Dropping a task during `t resolve` or the weekly review could reopen one of its steps.
- `t restore` could delete the copy it was about to restore, and crashed on a copy made
  by an older version.
- `t undo` on data from an older version lost history added by the migration, and
  undoing a new task left its focus time behind.
- `t import` kept the old `series` number of repeating tasks.
- Clear messages instead of crashes for dates like `0th`, huge estimates, an export to
  a missing folder, and broken calendar events (which are now skipped).
- A repeating calendar event with an end date now includes its last day.
- "Back from waiting" reminders were lost when another command woke the task first.

## 0.9.0 · 2026-10-01

### Added
- A welcome screen with three steps when there are no tasks yet.
- Shell completion for bash, zsh and fish: `t completion <shell>`. It completes commands,
  task ids with titles, goals, dates and details.
- Themes: `[ui] theme = "dark" | "light" | "plain"`. `plain` has no color and only ASCII.
  `NO_COLOR` is respected.
- `t doctor` checks the config, data, backups, calendars, hooks, plugins and reminders,
  with a fix for each problem. It works even with a broken config.
- `t --version`, `t help <command>` and `t <command> --help`. Help is grouped by topic.

### Changed
- A config file that can't be used now gives one clear message instead of a crash.
  Every setting is checked.
- `t ls` shows the first 20 tasks. `t ls --all` shows every one.
- Much faster with many tasks: about 0.12 s for `t next` with 5,000 tasks.

### Fixed
- Some bold labels in the focus timer and gantt chart lost their color.

## 0.8.0 · 2026-09-30

### Added
- Repeating tasks with `every:` (day, weekday, mon,thu, 3d, 2w, month, year, 1st, 15th,
  last). Only one copy exists at a time, so missed repeats never pile up.
- `t drop` asks whether to skip one repeat or stop the series (`--once`, `--stop`).
- Reminders: `t notify`, with `--install` for a systemd user timer or a launchd agent.
- The `on_remind` hook, for example to forward reminders to a phone.
- Dates like `1st` and `15th`.

## 0.7.0 · 2026-09-30

### Added
- A daily backup on the first run of each day. `t backup` and `t restore`.
- `t export` and `t import` (JSON lines). Undo stops at an import or a restore.
- Importer plugins for todo.txt, Taskwarrior and CSV in `examples/plugins/`.
- The data reference, `docs/data.md`.

## 0.6.0 · 2026-09-30

### Added
- Task states: todo, started, waiting, done, dropped. `t start`, `t wait`, `t status`.
- Started tasks win ties, and the status line warns when too many are started.
- Waiting tasks come back on their date, and when their deadline is at risk.
- Feature switches: every part added after 0.1 can be turned off with `t features`.

## 0.5.0 · 2026-09-29

### Added
- Energy windows and `@high` / `@low` tasks. `t next --low`.
- Date corrections: soft targets and deadlines count as earlier when you usually
  finish late. Push-backs are counted for plugins. `t stats`.

## 0.4.0 · 2026-09-29

### Added
- Hooks: scripts in `~/.config/tend/hooks/` that get each event as JSON.
- Plugins: any `t-<name>` program on your PATH runs as `t <name>`.

## 0.3.0 · 2026-09-29

### Added
- `t plan`: a schedule built with the same three rules, around your calendar.
- `t gantt`: the next days as a chart.
- Calendar import from `.ics` files and URLs. `t plan --ics` exports the plan.

## 0.2.0 · 2026-09-29

### Added
- Estimate calibration from focus sessions.
- The weekly review, `t review`.

## 0.1.0 · 2026-09-29

### Added
- Capture, triage, and `t next` with three rules: deadlines at risk, one big rock a day,
  and WSJF for everything else.
- Focus timer (pomodoro, flow, timebox), split, skip, slipped tasks, goals, wins, undo.
- `--json` on every command. One SQLite file for all data.
