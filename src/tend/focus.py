"""Focus timer with three modes:

pomo  25 min work, 5 min break (configurable)
flow  counts up with no forced stop; press b for a break sized to the time you worked
box   hard stop after N minutes
"""

import contextlib
import shutil
import subprocess
import time
from dataclasses import dataclass

from rich.console import Group
from rich.live import Live
from rich.rule import Rule
from rich.text import Text

from . import fmt, keys
from .ui import ACCENT, ACCENT_B, DIM, WARN, console

BAR = 32


@dataclass
class Result:
    minutes: float
    outcome: str  # done | stop


def notify(msg: str):
    console.bell()
    if shutil.which("notify-send"):
        with contextlib.suppress(OSError):
            subprocess.Popen(["notify-send", "-a", "Tend", "Tend", msg],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(title: str, meta: Text, mode: str, cfg: dict, box_min: int | None = None) -> Result:
    fc = cfg["focus"]
    work_target = {"pomo": fc["pomo_work"] * 60, "box": (box_min or fc["box_minutes"]) * 60}.get(mode)
    phase, target, elapsed = "work", work_target, 0.0
    paused, worked, rounds, message = False, 0.0, 1, ""
    outcome = "stop"

    def earned_break() -> float:
        return max(3 * 60, elapsed * fc["flow_break_ratio"])

    def render():
        label, color = {"work": ("Focus", ACCENT), "break": ("Break", WARN), "between": ("Paused", DIM)}[phase]
        if paused:
            label, color = "Paused", DIM
        head = Text.assemble((" ● ", color), (f"{label}  ", f"{color}.bold"), (title, "bold"), "  ", meta)
        if phase == "between":
            body = Text("   " + message, style=DIM)
        elif target:
            frac = min(elapsed / target, 1)
            filled = int(frac * BAR)
            body = Text.assemble("   ", ("━" * filled, color), ("━" * (BAR - filled), DIM),
                                 f"  {fmt.clock(target - elapsed)}", (" left", DIM))
        else:
            body = Text.assemble("   ", (fmt.clock(elapsed), f"{color}.bold"), (" elapsed", DIM),
                                 (f" · break earned {fmt.minutes(earned_break() / 60)}", DIM))
        extra = Text(f"   {mode} · round {rounds} · {fmt.minutes(worked / 60)} focused", style=DIM)
        opts = {"work": ["p pause", "d done", "q stop"] + (["b break"] if mode == "flow" else []),
                "break": ["p pause", "s skip break", "d done", "q stop"],
                "between": ["c continue", "d done", "q stop"]}[phase]
        bar = Text(" ")
        for o in opts:
            k, name = o.split(" ", 1)
            bar.append(k, ACCENT_B)
            bar.append(f" {name}   ", DIM)
        return Group(head, body, extra, Rule(style=DIM), bar)

    last = time.monotonic()
    with keys.raw(), Live(render(), console=console, refresh_per_second=4, transient=True) as live:
        try:
            while True:
                k = keys.getkey(0.25)
                now = time.monotonic()
                dt, last = now - last, now
                if not paused and phase in ("work", "break"):
                    elapsed += dt
                    if phase == "work":
                        worked += dt

                if k == "q":
                    break
                if k == "d":
                    outcome = "done"
                    break
                if k == "p" and phase != "between":
                    paused = not paused
                elif k == "b" and phase == "work" and mode == "flow":
                    phase, target, elapsed = "break", earned_break(), 0.0
                elif k == "s" and phase == "break":
                    elapsed = target
                elif k == "c" and phase == "between":
                    phase, target, elapsed, paused = "work", work_target, 0.0, False
                    rounds += 1

                if target and elapsed >= target and phase == "work":
                    if mode == "pomo":
                        notify(f"Pomodoro done. Take {fc['pomo_break']} minutes.")
                        phase, target, elapsed = "break", fc["pomo_break"] * 60, 0.0
                    else:
                        notify("Time's up.")
                        phase, target, message = "between", None, "Time's up. Continue, finish, or stop here."
                elif target and elapsed >= target and phase == "break":
                    notify("Break over.")
                    phase, target, message = "between", None, "Break over. Ready for another round?"
                live.update(render())
        except KeyboardInterrupt:
            pass
    return Result(worked / 60, outcome)
