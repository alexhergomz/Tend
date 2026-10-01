from dataclasses import asdict, dataclass, fields
from datetime import date

SIZES = {"S": 1, "M": 2, "L": 3}  # WSJF denominator
SIZE_MINUTES = {"S": 30, "M": 120, "L": 240}  # assumed effort when no estimate is given
DATE_FIELDS = ("due", "aim", "start_after", "skip_date", "first_due", "first_aim")
ENERGY = ("high", "low")
STAGES = ("todo", "started", "waiting")  # where an open task is
STATES = (*STAGES, "done", "dropped")  # what people see: stage while open, else status


@dataclass
class Task:
    id: int | None
    title: str
    goal: str | None = None
    parent: int | None = None
    value: int | None = None  # 1 nice to have · 2 matters · 3 really matters
    size: str | None = None  # S / M / L
    estimate_min: int | None = None
    due: date | None = None  # hard deadline
    aim: date | None = None  # soft target
    start_after: date | None = None
    status: str = "open"  # open · done · dropped
    slips: int = 0
    skip_date: date | None = None
    created: str = ""
    done_at: str | None = None
    energy: str | None = None  # high / low / None (any time)
    first_due: date | None = None  # the first hard deadline this task had
    first_aim: date | None = None  # the first soft target this task had
    pushes: int = 0  # times a date moved later, never reset
    stage: str = "todo"  # todo / started / waiting, while status is open
    started_at: str | None = None  # first time work started
    repeat: str | None = None  # rule after every:, such as "mon" or "2w"
    series: int | None = None  # id of the first task of a repeating series

    @property
    def state(self) -> str:
        """One word for people: todo, started, waiting, done or dropped."""
        return self.stage if self.status == "open" else self.status

    @property
    def triaged(self) -> bool:
        return self.value is not None and self.size is not None

    def to_row(self) -> dict:
        row = asdict(self)
        for k in DATE_FIELDS:
            if row[k] is not None:
                row[k] = row[k].isoformat()
        return row

    @classmethod
    def from_row(cls, row) -> "Task":
        data = {name: row[name] for name in _NAMES}
        for k in DATE_FIELDS:
            if data[k]:
                data[k] = date.fromisoformat(data[k])
        return cls(**data)

    def to_json(self) -> dict:
        return self.to_row()


_NAMES = tuple(f.name for f in fields(Task))


@dataclass
class Goal:
    name: str
    weekly_min: int = 0
    why: str | None = None
