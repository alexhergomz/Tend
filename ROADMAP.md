# Roadmap

Tend 1.0 has everything that was planned. This page keeps the rules every
release follows, what each version added, and how new ideas get in.

## Rules for every release

1. **The core stays small.** The core is capture, triage, the three rules, the
   focus timer, split, skip, slipped tasks, goals, wins, undo, backups and JSON
   output. It can't be turned off.
2. **Everything else is a feature you can turn off.** Each new part ships with a
   switch in `[features]`. When it is off, its commands, keys and effects are
   gone. Your data is kept, so you can turn it on again later.
3. **Simple, reliable models only.** If something can't be done well with a
   simple rule, Tend stores the data and leaves the rest to plugins.
4. **New ideas start as plugins.** A plugin moves into Tend only if many people
   need it and it fits these rules.
5. **Your data is safe.** Every schema change has a migration, and a test that
   opens a database made by each earlier release.
6. **The promise holds.** In 1.x, nothing in [docs/data.md](docs/data.md) is
   removed or changes meaning (see its Stability section).

## What each version added

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
| 0.9 | First-run guide, shell completion, themes, `t doctor`, speed | core |
| 1.0 | Stability promise, migration tests for every release, man page, PyPI | core |
| 1.1 | Windows support | core |

The [changelog](CHANGELOG.md) has the details of each version.

## After 1.0

There is no feature list for 1.x on purpose. Tend should stay small enough to
trust. Changes after 1.0 are:

- **Fixes,** in patch releases (1.0.1, 1.0.2, …).
- **Small additions** that fit the rules above, in minor releases (1.1, 1.2, …).
  Each one is a feature you can turn off.
- **Anything bigger starts as a plugin.** Good plugin ideas, which can all be
  built on hooks, `--json` and the database:
  - **Sync between devices.** The database is one file, so Syncthing or similar
    works if only one device writes at a time. A real sync plugin can use the
    `on_change` hook and the `events` table.
  - **Phone or web apps.**
  - **Habit streaks** from the `series` of a repeating task.
  - **Reports and charts** of focus time, goals and estimates.
  - **AI suggestions,** such as splitting tasks or guessing estimates.
  - **Shared or team tasks.**

A 2.0 only happens if something in the stable interfaces truly has to change.
