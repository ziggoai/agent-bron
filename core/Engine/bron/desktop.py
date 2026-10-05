"""A Mac notification banner when background work finishes, so nobody has to keep checking. It never fails the work:
off a Mac, or when Notification Centre can't be reached, nothing is shown."""
from __future__ import annotations

import subprocess
import sys


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def show(text: str, *, title: str = "Bron", run=subprocess.run) -> None:
    if sys.platform != "darwin":
        return
    script = f"display notification {_quoted(' '.join(text.split()))} with title {_quoted(title)}"
    try:
        run(["/usr/bin/osascript", "-e", script], capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def notify(text: str) -> None:
    """What the engine calls; unit tests replace it (tests/conftest.py) so they never show a real banner."""
    show(text)
