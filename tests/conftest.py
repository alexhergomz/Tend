"""On GitHub Actions, report each failing test as an error annotation, so it can be read without the logs."""

import os


def pytest_runtest_logreport(report):
    if os.environ.get("GITHUB_ACTIONS") and report.failed:
        text = str(report.longrepr)[-1500:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        title = report.nodeid.replace("::", " > ")  # "::" would end the title early
        print(f"\n::error title={title}::{text}")
