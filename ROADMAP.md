# Roadmap to 1.0

## Rules for every release

1. **The core stays small.** The core is everything from 0.1: capture, triage,
   the three rules, focus timer, split, skip, slipped tasks, goals, wins, undo
   and JSON output. It can't be turned off.
2. **Everything else is a feature you can turn off.** Each new part ships with a
   switch in `[features]`. When it is off, its commands, keys and effects are
   gone. Your data is kept, so you can turn it on again later.
3. **Simple, reliable models only.** If something can't be done well with a
   simple rule, tend stores the data and leaves the rest to plugins.
4. **New ideas start as plugins.** A plugin moves into tend only if many people
   need it and it fits these rules.
5. **Your data is safe.** Every schema change has a migration and a test.

## Done

| Version | What | Feature switch |
|---|---|---|
| 0.1 | Capture, triage, three rules, focus timer, slipped tasks, undo, JSON | core |
| 0.2 | Weekly review | `review` |
| 0.2 | Estimate calibration (date corrections added in 0.5), `t stats` | `learning` |
| 0.3 | `t plan`, `t gantt`, calendar import, `.ics` export | `planning` |
| 0.4 | Hooks | `hooks` |
| 0.4 | Plugins | `plugins` |
| 0.5 | Energy windows | `energy` |
| 0.6 | Task states: todo, started, waiting | `states` |
| 0.6 | Feature switches (`t features`) | core |
| 0.7 | Daily backups, `t backup`, `t restore` | core |
| 0.7 | `t export`, `t import`, data reference (`docs/data.md`) | core |
| 0.7 | Importers for todo.txt, Taskwarrior and CSV | plugins in `examples/` |
| 0.8 | Repeating tasks (`every:`) | `repeat` |
| 0.8 | Reminders (`t notify`, timer install, `on_remind` hook) | `reminders` |

## 0.9: Easy to start, pleasant to use

- **First run.** On an empty database, `t` shows a three-step guide: add a task,
  run `t next`, and try `t focus`. It doesn't come back after that.
- **Shell completion** for bash, zsh and fish, including task ids with titles and
  goal names. `t completion zsh` prints the script.
- **Colors.** Respects `NO_COLOR`. A `[ui] theme` option with `dark`, `light`
  and `plain`. `plain` uses no color and no box characters, for screen readers
  and logs.
- **`t doctor`.** Checks the config, calendar URLs, hook permissions, the PATH
  for plugins, and database integrity. Each problem comes with a fix.
- **Speed.** Startup under 150 ms with 5,000 tasks, checked by a test.

## 1.0: Stable

1.0 is a promise, not a feature list.

- **Stable public interfaces:** the database schema, `--json` output, hook
  payloads and the plugin environment. From 1.0 on, a breaking change needs a
  new major version. Old fields are kept and marked as deprecated for at least
  one minor version first.
- **Migrations tested from every earlier version**, using saved databases from
  each release.
- **Packaging.** Published on PyPI so `pipx install` and `uv tool install` work
  without cloning. Release notes in `CHANGELOG.md` and a man page.
- **No known bugs that lose data or hide a deadline.**

## Not planned: good plugin ideas

These are useful, but they don't fit the core. They can all be built on hooks,
`--json` and the database.

- **Sync between devices.** The database is one file, so Syncthing or similar
  works if only one device writes at a time. A real sync plugin can use the
  `on_change` hook and the `events` table.
- **Phone or web apps.**
- **AI suggestions,** such as splitting tasks or guessing estimates.
- **Shared or team tasks.**
- **Reports and charts** of focus time, goals and estimates.
