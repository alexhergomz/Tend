from dataclasses import asdict, dataclass, fields
from datetime import date

SIZES = {"S": 1, "M": 2, "L": 3}  # WSJF denominator
SIZE_MINUTES = {"S": 30, "M": 120, "L": 240}  # assumed effort when no estimate is given
DATE_FIELDS = ("due", "aim", "start_after", "skip_date", "first_due", "first_aim")
ENERGY = ("high", "low")


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
        data = {f.name: row[f.name] for f in fields(cls)}
        for k in DATE_FIELDS:
            if data[k]:
                data[k] = date.fromisoformat(data[k])
        return cls(**data)

    def to_json(self) -> dict:
        return self.to_row()


@dataclass
class Goal:
    name: str
    weekly_min: int = 0
    why: str | None = None
