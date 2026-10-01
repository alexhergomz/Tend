"""Shell completion. `t completion <shell>` prints a script that calls `t _complete`.

`t _complete <words...> <current>` prints one candidate per line, as
`value<TAB>description`. It reads the database without changing it.
"""

import sqlite3
from pathlib import Path

from . import config, features, hooks, registry

DATES = ["today", "tom", "mon", "tue", "wed", "thu", "fri", "sat", "sun", "+3d", "+1w", "1st", "eow", "eom", "none"]
RULES = ["day", "weekday", "mon", "mon,thu", "week", "2w", "month", "1st", "15th", "last", "none"]
TOKENS = [("due:", "hard deadline"), ("aim:", "soft target"), ("after:", "hide until"), ("v:", "value 1-3"),
          ("s:", "size S, M or L"), ("e:", "estimate, like e:45m"), ("every:", "repeat"), ("+", "goal"),
          ("@high", "needs energy"), ("@low", "easy work")]
STATES = ["todo", "started", "waiting", "done", "dropped"]

SCRIPTS = {
    "bash": r"""# Tend completion for bash. Add to ~/.bashrc:  eval "$(t completion bash)"
_tend_complete() {
    local line="${COMP_LINE:0:COMP_POINT}" cur="" c
    local -a words
    read -ra words <<< "$line"
    if [[ "$line" != *" " ]]; then cur="${words[-1]}"; unset 'words[-1]'; fi
    local IFS=$'\n'
    COMPREPLY=()
    for c in $("${words[0]}" _complete "${words[@]:1}" "$cur" 2>/dev/null | cut -f1); do
        [[ "$cur" == *:* ]] && c="${c#"${cur%:*}":}"
        COMPREPLY+=("$c")
    done
}
complete -o default -o nosort -F _tend_complete t tend
""",
    "zsh": r"""# Tend completion for zsh. Add to ~/.zshrc, after compinit:  source <(t completion zsh)
_tend() {
    local -a values shown
    local value desc
    while IFS=$'\t' read -r value desc; do
        values+=("$value")
        shown+=("$value${desc:+  -- $desc}")
    done < <("${words[1]}" _complete "${(@)words[2,CURRENT-1]}" "${words[CURRENT]}" 2>/dev/null)
    (( ${#values} )) && compadd -l -Q -d shown -a values
}
compdef _tend t tend
""",
    "fish": r"""# Tend completion for fish. Save as ~/.config/fish/completions/t.fish:  t completion fish > ...
complete -c t -f -a '(t _complete (commandline -opc)[2..-1] (commandline -ct))'
complete -c tend -f -a '(tend _complete (commandline -opc)[2..-1] (commandline -ct))'
""",
}


def _db():
    path = config.data_path()
    if not path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _open_tasks() -> list[tuple[str, str]]:
    db = _db()
    if not db:
        return []
    try:
        rows = db.execute("SELECT id, title FROM tasks WHERE status = 'open' ORDER BY id DESC LIMIT 100").fetchall()
    except sqlite3.Error:
        return []
    return [(str(i), title) for i, title in rows]


def _goals() -> list[str]:
    db = _db()
    if not db:
        return []
    try:
        return [r[0] for r in db.execute("SELECT name FROM goals ORDER BY name")]
    except sqlite3.Error:
        return []


def _paths(current: str) -> list[tuple[str, str]]:
    base = Path(current).expanduser()
    folder, prefix = (base, "") if current.endswith("/") else (base.parent, base.name)
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    head = current[: len(current) - len(prefix)]
    return [(head + p.name + ("/" if p.is_dir() else ""), "") for p in entries
            if p.name.startswith(prefix) and not p.name.startswith(".")]


def candidates(words: list[str], current: str) -> list[tuple[str, str]]:
    try:
        cfg = config.merge(config.read_user())
    except config.ConfigError:
        cfg = config.merge({})
    on = lambda c: features.command_enabled(cfg, c.name)

    # details can be added to any task, whatever the command
    for prefix, values in (("due:", DATES), ("aim:", DATES), ("after:", DATES), ("every:", RULES),
                           ("v:", ["1", "2", "3"]), ("s:", ["S", "M", "L"]), ("e:", ["15m", "30m", "1h", "2h"])):
        if current.startswith(prefix):
            return _match([(prefix + v, "") for v in values], current)
    if current.startswith("+"):
        return _match([("+" + g, "goal") for g in _goals()], current)
    if current.startswith("@"):
        return _match([("@high", "needs energy"), ("@low", "easy work"), ("@any", "clear")], current)

    if not words:
        found = [(c.name, c.help) for c in registry.listed() if on(c)]
        if features.enabled(cfg, "plugins"):
            found += [(name, "plugin") for name, _ in hooks.list_plugins()]
        return _match(found, current)

    cmd = registry.find(words[0])
    if not cmd:  # writing a new task: offer the details
        return _match(TOKENS, current) if current else []
    rest = words[1:]
    if current.startswith("-"):
        return _match([(f, "") for f in cmd.flags if f.startswith("-")], current)
    if cmd.name in ("import", "export"):
        return _paths(current)
    if cmd.name == "help":
        return _match([(c.name, c.help) for c in registry.listed()], current) if not rest else []
    if cmd.name == "completion":
        return _match([(s, "") for s in SCRIPTS], current)
    if cmd.name == "features":
        if not rest:
            return _match([("on", ""), ("off", "")], current)
        return _match([(n, w) for n, (_, w) in features.FEATURES.items()], current)
    if cmd.name == "goals":
        if not rest:
            return _match([("add", "add or change a goal"), ("rm", "remove a goal")], current)
        return _match([(g, "") for g in _goals()], current) if rest[0] == "rm" and len(rest) == 1 else []
    found = []
    if cmd.takes_id and not any(w.lstrip("#").isdigit() for w in rest):
        found += _open_tasks()
    if cmd.name == "status":
        found += [(s, "") for s in STATES]
    if cmd.name in ("edit", "add"):
        found += TOKENS
    found += [(f, "") for f in cmd.flags if not f.startswith("-") and f not in STATES]
    return _match(found, current)


def _match(items: list[tuple[str, str]], current: str) -> list[tuple[str, str]]:
    return [(v, d) for v, d in items if v.startswith(current)]


def complete(args: list[str]) -> str:
    words, current = (args[:-1], args[-1]) if args else ([], "")
    return "\n".join(f"{v}\t{d}" for v, d in candidates(words, current))
