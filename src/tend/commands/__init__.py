"""All commands. Importing this package registers them (see registry.py)."""

from .. import features, registry
from ..app import App, UsageError
from . import capture, deciding, doing, looking, system  # noqa: F401  (registers the commands)


def lookup(word: str, app: App | None = None):
    """The function for a command name, key or alias. A command whose feature is off explains how to turn it on."""
    cmd = registry.find(word)
    if not cmd:
        return None
    if app and cmd.feature and not features.enabled(app.cfg, cmd.feature):
        def off(app, args):
            raise UsageError(f"t {cmd.name} is part of '{cmd.feature}', which is turned off. "
                             f"Turn it on: t features on {cmd.feature}")
        return off
    return cmd.fn
