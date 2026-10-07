"""Reports from finished reading jobs, waiting to be told to the user once (in the next briefing or message)."""
from __future__ import annotations

import json
import os
import time

from .. import statefile
from ..vault import Vault
from .store import kb_dir

KEEP = 50  # shown reports kept for reference


def _path(vault: Vault):
    return kb_dir(vault) / "notices.jsonl"


def _parse(line: str) -> dict | None:
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) and isinstance(entry.get("text"), str) else None


def add(vault: Vault, text: str, *, job_id: str = "", shown: bool = False) -> None:
    """Note a report. One report per job: a second one for the same job (a resumed job finishing) is dropped.
    `shown`: the user has seen it already (the command that made it printed it)."""
    path = _path(vault)
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text}
    if job_id:
        entry["job"] = job_id
    if shown:
        entry["shown"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    with statefile.locked(path):
        if job_id and any((e or {}).get("job") == job_id for e in map(_parse, statefile.read_lines(path))):
            return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def take(vault: Vault) -> list[str]:
    """The reports not shown yet, oldest first; they are marked as shown."""
    path = _path(vault)
    if not path.is_file():
        return []
    with statefile.locked(path):
        entries = [e for e in (_parse(line) for line in statefile.read_lines(path)) if e is not None]
        fresh = [e["text"] for e in entries if not e.get("shown")]
        if not fresh:
            return []
        for e in entries:
            e["shown"] = True
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries[-KEEP:]), encoding="utf-8")
        tmp.replace(path)
    return fresh


def take_jobs(vault: Vault, job_ids: list[str]) -> list[str]:
    """These jobs' reports, shown or not (a conversation waiting for its own reading is told it even when another
    conversation was told first); they are marked as shown."""
    path = _path(vault)
    if not path.is_file():
        return []
    wanted = set(job_ids)
    with statefile.locked(path):
        entries = [e for e in (_parse(line) for line in statefile.read_lines(path)) if e is not None]
        mine = [e for e in entries if e.get("job") in wanted]
        if not mine:
            return []
        for e in mine:
            e["shown"] = True
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries[-KEEP:]), encoding="utf-8")
        tmp.replace(path)
    return [e["text"] for e in mine]
