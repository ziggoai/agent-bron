"""The knowledge base's reading and search tools: installed into the vault's engine the first time they're needed."""
from __future__ import annotations

import fcntl
import importlib
import importlib.util
import re
import subprocess
from pathlib import Path

from ..vault import Vault
from .store import KbError

KB_REQUIREMENTS = Path(__file__).resolve().parents[2] / "kb-requirements.txt"
MODULES = ["pypdfium2", "ocrmac", "python_calamine", "docx", "pptx", "trafilatura", "fastembed", "numpy"]
SETUP = "Setting up the knowledge base tools (about 300 MB, one time)…"


def requirements_file(vault: Vault) -> Path:
    """The vault's own copy (System/Core/Engine); the engine runs from site-packages, where the file isn't."""
    own = vault.core / "Engine" / "kb-requirements.txt"
    return own if own.is_file() else KB_REQUIREMENTS


def missing() -> list[str]:
    return [m for m in MODULES if importlib.util.find_spec(m) is None]


def _lock_path(vault: Vault) -> Path:
    return vault.bron_dir / "kb" / "tools.lock"


def ensure(vault: Vault, *, say=print, run=subprocess.run) -> None:
    """One setup at a time: a second command waits for the first (mid-install the tools can already look present)
    and then finds them installed."""
    lock = _lock_path(vault)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        importlib.invalidate_caches()
        if missing():
            _install(vault, say, run)


def _install(vault: Vault, say, run) -> None:
    from ..update import find_uv

    say(SETUP)
    uv = find_uv()
    if uv is None:
        raise KbError("The knowledge base tools couldn't be installed: uv (the tool Bron uses to install them) wasn't found.")
    python = vault.bron_dir / "venv" / "bin" / "python"
    try:
        done = run([uv, "pip", "install", "--quiet", "--python", str(python), "-r", str(requirements_file(vault))],
                   capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KbError(f"The knowledge base tools couldn't be installed ({exc.__class__.__name__}).") from exc
    if done.returncode != 0:
        reason = _last_line(done.stderr or done.stdout, done.returncode)
        raise KbError(f"The knowledge base tools couldn't be installed ({reason}). Check the internet connection and try again.")


_DECORATION = re.compile(r"^[\s×│├╰─▶|>*-]+")


def _last_line(output: str, code: int) -> str:
    """The last line of the installer's output that says something (not a hint), without its decoration."""
    for line in reversed((output or "").splitlines()):
        line = _DECORATION.sub("", line).strip()
        if line and not re.match(r"(help|hint|note|warning):", line, re.IGNORECASE):
            line = re.sub(r"^error:\s*", "", line, flags=re.IGNORECASE).rstrip(".")
            return line[:200]
    return f"the installer stopped with error {code}"
