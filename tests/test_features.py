"""Optional features can be turned off completely."""

import json
import os
import subprocess
import sys


def _t(tmp_path, *args):
    env = {**os.environ, "TEND_DB": str(tmp_path / "t.db"), "TEND_CONFIG": str(tmp_path / "c.toml"),
           "TEND_HOOKS": str(tmp_path / "hooks"), "COLUMNS": "100"}
    return subprocess.run([sys.executable, "-m", "tend", *args], env=env, capture_output=True, text=True)


def test_features_list_and_toggle(tmp_path):
    out = json.loads(_t(tmp_path, "features", "--json").stdout)
    assert all(f["on"] for f in out.values()) and set(out) >= {"states", "planning", "energy"}
    _t(tmp_path, "features", "off", "states", "planning")
    out = json.loads(_t(tmp_path, "features", "--json").stdout)
    assert not out["states"]["on"] and not out["planning"]["on"] and out["energy"]["on"]
    assert "states = false" in (tmp_path / "c.toml").read_text()


def test_commands_of_a_disabled_feature_explain_themselves(tmp_path):
    _t(tmp_path, "features", "off", "planning")
    r = _t(tmp_path, "plan")
    assert r.returncode == 1 and "t features on planning" in r.stdout
    assert json.loads(_t(tmp_path, "ls", "--json").stdout) == []  # "plan" was not captured as a task
    assert "plan" not in _t(tmp_path, "help").stdout.split("Quick-add")[0].split()


def test_states_off_shows_waiting_tasks_as_todo(tmp_path):
    _t(tmp_path, "call", "landlord")
    _t(tmp_path, "wait", "1")
    assert json.loads(_t(tmp_path, "ls", "--json").stdout) == []
    _t(tmp_path, "features", "off", "states")
    tasks = json.loads(_t(tmp_path, "ls", "--json").stdout)
    assert [t["stage"] for t in tasks] == ["todo"]
    _t(tmp_path, "features", "on", "states")  # data was kept
    assert json.loads(_t(tmp_path, "ls", "--json").stdout) == []


def test_unknown_feature(tmp_path):
    r = _t(tmp_path, "features", "off", "gantt")
    assert r.returncode == 1 and "no feature 'gantt'" in r.stdout
