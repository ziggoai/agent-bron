"""What the user points the knowledge base at: Drive links, files and folders, the inbox, web links.

Drive links are found on this Mac by their Drive ID (Google Drive for desktop keeps it on every item).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import statefile
from ..vault import Vault
from .store import kb_dir

ATTR = "com.google.drivefs.item-id#S"
MAX_ENTRIES = 200_000
MAX_SECONDS = 120
SAVE_EVERY = 2000
NATIVE = {".gdoc", ".gsheet", ".gslides"}
SHORTCUTS = ".shortcut-targets-by-id"  # Drive for desktop keeps folders shared with the user here, by folder id
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


def shortcut_dirs(home: Path | None = None) -> list[Path]:
    """Where Google Drive for desktop keeps the folders shared with the user: <account>/.shortcut-targets-by-id."""
    override = os.environ.get("BRON_DRIVE_ROOT")
    if override:
        candidates = [Path(override) / SHORTCUTS, Path(override).parent / SHORTCUTS]
    else:
        base = (home or Path.home()) / "Library" / "CloudStorage"
        candidates = [account / SHORTCUTS for account in sorted(base.glob("GoogleDrive-*"))] if base.is_dir() else []
    return [c for c in candidates if c.is_dir()]


def drive_roots(home: Path | None = None) -> list[Path]:
    override = os.environ.get("BRON_DRIVE_ROOT")
    if override:
        p = Path(override)
        if not p.is_dir():
            return []
        return [p] + [s for s in shortcut_dirs() if not is_under(s, p)]  # one inside p is walked from p
    base = (home or Path.home()) / "Library" / "CloudStorage"
    roots: list[Path] = []
    if base.is_dir():
        for account in sorted(base.glob("GoogleDrive-*")):
            # "My Drive" and "Shared drives" first; the names are localised ("Meu Drive"), so every top folder counts
            subs = [s for s in sorted(account.iterdir(), key=lambda s: s.name not in ("My Drive", "Shared drives"))
                    if s.is_dir() and not s.name.startswith(".")]
            roots += subs
    return roots + shortcut_dirs(home)


def shared_folder(item_id: str) -> Path | None:
    """A folder shared with the user, straight from its id, without a walk: .shortcut-targets-by-id/<folder id>."""
    for base in shortcut_dirs():
        candidate = base / item_id
        if candidate.is_dir():
            return candidate
    return None


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
    return name.startswith(".") and name != SHORTCUTS  # folders shared with the user live in .shortcut-targets-by-id


SYSTEM_FILES = {"desktop.ini", "thumbs.db", "icon\r"}  # made by Windows and macOS, never a document


def system_file(name: str) -> bool:
    """A file the computer made rather than a person: skipped when a folder is read. `~$` files are Office's
    owner files, left next to a document someone has open."""
    return name.lower() in SYSTEM_FILES or name.startswith("~$")


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
        out += [Path(dirpath) / f for f in filenames if not _hidden(f) and not system_file(f)]
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


@dataclass
class Resolved:
    items: list[Item]
    failed: list[str]
    folders: list[str]  # the names of the folders asked for (a folder is read in the background)
    folder_paths: list[Path] = field(default_factory=list)  # where those folders are (a shared one: its inner folder)


def _folder_name(path: Path) -> str:
    """The folder's own name; a shared folder's id folder is named after the one folder inside it."""
    if path.parent.name == SHORTCUTS:
        try:
            inside = [p for p in path.iterdir() if p.is_dir() and not _hidden(p.name)]
        except OSError:
            inside = []
        if len(inside) == 1:
            return inside[0].name
    return path.name


def _own_path(path: Path) -> Path:
    """The folder itself; a shared folder's id folder stands for the one folder inside it."""
    name = _folder_name(path)
    return path / name if name != path.name else path


def _is_generic(path: Path) -> bool:
    """A place that says nothing about the documents: the disk's top, the home folder, a Drive's top."""
    return (path.parent == path or path == Path.home() or path.parent == Path.home()
            or path.name in ("My Drive", "Shared drives", SHORTCUTS) or path.parent.name == "CloudStorage")


def folder_label(found: "Resolved", items: list[Item]) -> str:
    """How a background reading is named in its ticket: "the Acme Ltda/Contracts folder" for one folder; for several
    folders or loose files, the deepest folder they share ("the Acme Ltda folder"); empty when nothing is shared."""
    paths = found.folder_paths
    if len(paths) == 1 and len(found.folders) == 1:
        own = _own_path(paths[0])
        return f"the {own.parent.name}/{own.name} folder" if not _is_generic(own.parent) else f"the {own.name} folder"
    places = [Path(i.path) for i in items if i.kind in ("file", "drive") and i.path]
    if not places or len(places) != len(items):
        return ""
    try:
        common = Path(os.path.commonpath([str(p.parent) for p in places]))
    except ValueError:
        return ""
    return "" if _is_generic(common) else f"the {common.name} folder"


def resolve(vault: Vault, targets: list[str], *, inbox: bool = False) -> tuple[list[Item], list[str]]:
    found = resolve_targets(vault, targets, inbox=inbox)
    return found.items, found.failed


def resolve_targets(vault: Vault, targets: list[str], *, inbox: bool = False) -> Resolved:
    targets = [as_link(t.strip()) for t in targets if t.strip()]
    wanted = {drive_id(t) for t in targets if _is_drive_link(t)} - {None}
    direct = {i: p for i in wanted if (p := shared_folder(i)) is not None}
    rest = wanted - set(direct)
    located, out_of_budget = _search(vault, rest) if rest else ({}, False)
    located = {**located, **direct}
    items: list[Item] = []
    failed: list[str] = []
    folders: list[str] = []
    folder_paths: list[Path] = []
    for target in targets:
        if _is_drive_link(target):
            did = drive_id(target)
            path = located.get(did) if did else None
            if path is None:
                note = " (searched for 2 minutes)" if out_of_budget else ""
                failed.append(f"Couldn't find {target} in Google Drive on this Mac{note}. "
                              "Open Google Drive for desktop and make sure the file is available.")
            elif path.is_dir():
                folders.append(_folder_name(path))
                folder_paths.append(path)
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
                folders.append(path.name)
                folder_paths.append(path)
                items += [_item_for_file(f, keep=keep) for f in _files_under(path)]
            elif path.is_file():
                items.append(_item_for_file(path, keep=keep))
            else:
                failed.append(f"There's no file at {target}.")
    if inbox:
        folder = inbox_dir(vault)
        if folder.is_dir():
            items += [_item_for_file(f, keep=True) for f in _files_under(folder)]
    return Resolved(items, failed, folders, folder_paths)
