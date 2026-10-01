"""Optional features. The core (everything from 0.1) is always on; each feature
here can be turned off in the [features] config section or with
`t features off <name>`. A feature that is off disappears: its commands, keys,
help lines and effects on ranking and planning are all gone.
"""

import re

from . import config, registry

# name: (since version, what it does). Commands name their feature in the registry.
FEATURES = {
    "review": ("0.2", "weekly review and its reminder"),
    "learning": ("0.2", "corrections learned from your history, and t stats"),
    "planning": ("0.3", "t plan, t gantt and calendar import"),
    "hooks": ("0.4", "scripts that run after events"),
    "plugins": ("0.4", "t-<name> programs run as t <name>"),
    "energy": ("0.5", "energy windows and @high / @low tasks"),
    "states": ("0.6", "started and waiting states"),
    "repeat": ("0.8", "repeating tasks (every:mon)"),
    "reminders": ("0.8", "desktop reminders from a timer"),
}


def commands_of(name: str) -> list[str]:
    return [c.name for c in registry.COMMANDS.values() if c.feature == name and not c.hidden]


def enabled(cfg: dict, name: str) -> bool:
    on = cfg.get("features", {}).get(name, True)
    if name == "learning" and not cfg["priority"].get("calibrate", True):
        return False  # the older switch still works
    return bool(on)


def command_enabled(cfg: dict, command: str) -> bool:
    cmd = registry.COMMANDS.get(command)
    return cmd is None or cmd.feature is None or enabled(cfg, cmd.feature)


def set_enabled(name: str, on: bool):
    """Write `name = true|false` into [features], keeping comments and everything else."""
    path = config.config_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    value = "true" if on else "false"
    header = next((i for i, line in enumerate(lines) if re.match(r"\s*\[features\]", line)), None)
    if header is None:
        lines += ["", "[features]", f"{name} = {value}"]
    else:
        end = next((i for i in range(header + 1, len(lines)) if re.match(r"\s*\[", lines[i])), len(lines))
        key = re.compile(rf"^(\s*{name}\s*=\s*)(true|false)", re.I)
        for i in range(header + 1, end):
            if key.match(lines[i]):
                lines[i] = key.sub(rf"\g<1>{value}", lines[i])
                break
        else:
            lines.insert(header + 1, f"{name} = {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
