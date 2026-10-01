"""The docs describe the program as it is: these fail when one changes without the other."""

import re
import sqlite3
from pathlib import Path

from tend import config, features, hooks, manpage, registry
from tend.store import SCHEMA

ROOT = Path(__file__).parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
DATA = (ROOT / "docs" / "data.md").read_text(encoding="utf-8")


def test_man_page_is_up_to_date():
    page = (ROOT / "docs" / "t.1").read_text(encoding="utf-8")
    assert page == manpage.render(), "run: python -m tend.manpage > docs/t.1"


def test_readme_lists_every_command_with_its_key():
    rows = {name: key for key, name in re.findall(r"^\| (?:`(.)`)? *\| `([a-z_]+)` \|", README, re.M)}
    for cmd in registry.listed():
        assert cmd.name in rows, f"README: add {cmd.name} to the Commands table"
        assert rows[cmd.name] == cmd.key, f"README: {cmd.name} has key {cmd.key!r}"


def test_readme_settings_match_the_template():
    assert config.TEMPLATE.strip() in README, "README: copy config.TEMPLATE into the Settings section"


def test_every_feature_and_hook_is_documented():
    for name in features.FEATURES:
        assert f"| `{name}` |" in README, f"README: document the {name} feature"
    for event in hooks.EVENTS:
        assert f"`{event}`" in README and f"`{event}`" in DATA, f"document the {event} hook"


def test_data_reference_lists_every_column():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    for table in ("tasks", "goals", "sessions", "events"):
        for (_, column, *_rest) in db.execute(f"PRAGMA table_info({table})"):
            assert f"`{column}`" in DATA, f"docs/data.md: document {table}.{column}"
