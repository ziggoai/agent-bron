"""What the user points the knowledge base at: Drive links, files and folders, the inbox, web links.

Drive links are found on this Mac by their Drive ID (Google Drive for desktop keeps it on every item).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .. import statefile
from ..vault import Vault
from .store import kb_dir

ATTR = "com.google.drivefs.item-id#S"
MAX_ENTRIES = 200_000
MAX_SECONDS = 120
SAVE_EVERY = 2000
NATIVE = {".gdoc", ".gsheet", ".gslides"}
_ID_PATTERNS = (
    re.compile(r"/(?:file|document|spreadsheets|presentation)(?:/u/\d+)?/d/(?!e/)([\w-]+)"),
    re.compile(r"/folders/([\w-]+)"),
    re.compile(r"[?&]id=([\w-]+)"),
)


@dataclass
class Item:
    kind: str  # "drive" | "file" | "web" | "native"
    identity: str
    source: str
    name: str
    path: str = ""
    url: str = ""


_BARE_DRIVE = re.compile(r"^(drive|docs)\.google\.com/", re.IGNORECASE)


def as_link(target: str) -> str:
    """A Drive or Docs link typed without https:// (drive.google.com/…, docs.google.com/…) is still a link."""
    return "https://" + target if _BARE_DRIVE.match(target) else target


def _is_web(target: str) -> bool:
    return target.startswith(("http://", "https://"))


def _is_drive_link(target: str) -> bool:
    return _is_web(target) and bool(re.match(r"https?://(drive|docs)\.google\.com/", target))


def drive_id(link: str) -> str | None:
    link = as_link(link.strip())
    if not _is_drive_link(link):
        return None
    for pattern in _ID_PATTERNS:
        m = pattern.search(link)
        if m:
            return m.group(1)
    return None


def drive_roots(home: Path | None = None) -> list[Path]:
    override = os.environ.get("BRON_DRIVE_ROOT")
    if override:
        p = Path(override)
        return [p] if p.is_dir() else []
    base = (home or Path.home()) / "Library" / "CloudStorage"
    roots: list[Path] = []
    if base.is_dir():
        for account in sorted(base.glob("GoogleDrive-*")):
            # "My Drive" and "Shared drives" first; the names are localised ("Meu Drive"), so every top folder counts
            subs = [s for s in sorted(account.iterdir(), key=lambda s: s.name not in ("My Drive", "Shared drives"))
                    if s.is_dir() and not s.name.startswith(".")]
            roots += subs
    return roots


_libc = None


def _read_attr(path: Path | str) -> str | None:
    """The Drive ID of an item, or None when it has none (or can't be read)."""
    global _libc
    try:
        if hasattr(os, "getxattr"):
            return os.getxattr(str(path), ATTR, follow_symlinks=False).decode("utf-8", "replace") or None
        if _libc is None:
            _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        buf = ctypes.create_string_buffer(512)
        n = _libc.getxattr(os.fsencode(str(path)), ATTR.encode(), buf, 512, 0, 1)  # 1 = XATTR_NOFOLLOW
        if n < 0:
            return None
        return buf.raw[:n].decode("utf-8", "replace") or None
    except (OSError, AttributeError, ValueError):
        return None


def _cache_path(vault: Vault) -> Path:
    return kb_dir(vault) / "drive-ids.json"


def _load_cache(vault: Vault) -> dict:
    data = statefile.read_json(_cache_path(vault), {})
    return data if isinstance(data, dict) else {}


def _hidden(name: str) -> bool:
    return name.startswith(".")


def _save_cache(vault: Vault, cache: dict) -> None:
    live = {k: v for k, v in cache.items() if os.path.exists(v)}
    statefile.write_json(_cache_path(vault), live)


def _search(vault: Vault, ids: set[str], roots=None) -> tuple[dict[str, Path], bool]:
    """One walk for a whole batch of IDs. Returns (found, ran_out_of_budget)."""
    cache = _load_cache(vault)
    found: dict[str, Path] = {}
    for i in ids:
        cached = cache.get(i)
        if cached and os.path.exists(cached) and _read_attr(cached) == i:
            found[i] = Path(cached)
    wanted = set(ids) - set(found)
    if not wanted:
        return found, False
    roots = drive_roots() if roots is None else [Path(r) for r in roots]
    state = {"seen": 0, "unsaved": 0}
    deadline = time.monotonic() + MAX_SECONDS
    out_of_budget = False

    def remember(path: Path) -> None:
        seen = _read_attr(path)
        if not seen:
            return
        if cache.get(seen) != str(path):
            cache[seen] = str(path)
            state["unsaved"] += 1
        if seen in wanted:
            found[seen] = path
            wanted.discard(seen)

    pending = [Path(r) for r in roots if Path(r).is_dir()]
    try:
        while pending and wanted:
            folder = pending.pop(0)
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except OSError:
                continue
            subdirs, files = [], []
            for e in entries:
                if _hidden(e.name):
                    continue
                try:
                    (subdirs if e.is_dir(follow_symlinks=False) else files).append(Path(e.path))
                except OSError:
                    continue
            for p in subdirs + files:  # directories before files
                state["seen"] += 1
                if state["seen"] > MAX_ENTRIES or time.monotonic() > deadline:
                    out_of_budget = True
                    break
                remember(p)
                if state["unsaved"] >= SAVE_EVERY:
                    _save_cache(vault, cache)
                    state["unsaved"] = 0
                if not wanted:
                    break
            if out_of_budget:
                break
            pending = subdirs + pending
    finally:
        _save_cache(vault, cache)
    return found, out_of_budget and bool(wanted)


def find_drive_items(vault: Vault, ids: set[str], *, roots=None) -> dict[str, Path]:
    return _search(vault, set(ids), roots)[0]


def find_drive_item(vault: Vault, item_id: str, *, roots=None) -> Path | None:
    return find_drive_items(vault, {item_id}, roots=roots).get(item_id)


def _files_under(folder: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not _hidden(d)]
        out += [Path(dirpath) / f for f in filenames if not _hidden(f)]
    return sorted(out)


def inbox_dir(vault: Vault) -> Path:
    return vault.root / "Knowledge" / "Inbox"


def files_dir(vault: Vault) -> Path:
    return vault.root / "Knowledge" / "Files"


def is_under(path: Path | str, folder: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(os.path.abspath(folder))
        return True
    except ValueError:
        return False


def _item_for_file(path: Path, *, from_drive_id: str | None = None, keep: bool = False) -> Item:
    """`keep`: a file Bron keeps a copy of (the inbox). It is a plain file even if it carries a Drive ID,
    because a file dragged out of the Drive folder keeps its ID attribute."""
    did = from_drive_id or _read_attr(path) or ""
    if path.suffix.lower() in NATIVE:
        src = f"https://drive.google.com/open?id={did}" if did else str(path)
        return Item("native", f"drive:{did}" if did else f"file:{path}", src, path.name, str(path))
    if did and not keep:
        return Item("drive", f"drive:{did}", f"https://drive.google.com/open?id={did}", path.name, str(path))
    return Item("file", f"file:{path}", str(path), path.name, str(path))


def resolve(vault: Vault, targets: list[str], *, inbox: bool = False) -> tuple[list[Item], list[str]]:
    targets = [as_link(t.strip()) for t in targets if t.strip()]
    wanted = {drive_id(t) for t in targets if _is_drive_link(t)} - {None}
    located, out_of_budget = _search(vault, wanted) if wanted else ({}, False)
    items: list[Item] = []
    failed: list[str] = []
    for target in targets:
        if _is_drive_link(target):
            did = drive_id(target)
            path = located.get(did) if did else None
            if path is None:
                note = " (searched for 2 minutes)" if out_of_budget else ""
                failed.append(f"Couldn't find {target} in Google Drive on this Mac{note}. "
                              "Open Google Drive for desktop and make sure the file is available.")
            elif path.is_dir():
                items += [_item_for_file(f) for f in _files_under(path)]
            else:
                items.append(_item_for_file(path, from_drive_id=did))
        elif _is_web(target):
            url = target.split("#", 1)[0]
            items.append(Item("web", f"web:{url}", url, url, "", url))
        else:
            path = Path(os.path.expanduser(target))
            if not path.is_absolute():
                path = Path.cwd() / path
            keep = is_under(path, inbox_dir(vault))
            if path.is_dir():
                items += [_item_for_file(f, keep=keep) for f in _files_under(path)]
            elif path.is_file():
                items.append(_item_for_file(path, keep=keep))
            else:
                failed.append(f"There's no file at {target}.")
    if inbox:
        folder = inbox_dir(vault)
        if folder.is_dir():
            items += [_item_for_file(f, keep=True) for f in _files_under(folder)]
    return items, failed
