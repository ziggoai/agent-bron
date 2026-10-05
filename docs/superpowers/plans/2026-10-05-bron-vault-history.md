# Bron Vault History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Bron vault keeps a private git history saved at each turn, credited to the user or the named agent, with plain-word undo and an optional off-Mac copy.

**Architecture:**
- A new package `bron.history`:
  - `gitcmd.py`: finding and running git safely;
  - `repo.py`: settings, creating the repository, the ignore section;
  - `save.py`: timed lock, credited saves, the two trigger entry points;
  - `log.py`: numbered saves, listing, showing, resolving `--to`;
  - `restore.py`: restore and undo;
  - `backup.py`: off-Mac copy, notices, recover;
  - `cli.py`: `bron history …`.
- The existing triggers call into it: `user-prompt` saves the user's edits synchronously; `stop` and `session-end` spawn detached `bron history` processes.
- Install, update, the 0.9.0 migration, the briefing and the health check each get a small hook-in.

**Tech Stack:** Python 3.12 (stdlib only: `subprocess`, `fcntl`, `dataclasses`), git via subprocess, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-05-bron-vault-history-design.md`

## Global Constraints

- **Speed:** the user-prompt step takes under 50 ms when nothing changed and under 100 ms with a few changed pages, on a 300-file vault. The stop trigger never waits for git.
- **History is never rewritten:** no `reset`, no `--force`, no `rebase`, no `commit --amend`, no deleting saves.
- **Nothing global:** git config is written only with `git config --local`. Never touch `~/.gitconfig`.
- **No pop-ups:** never run `/usr/bin/git` unless `xcode-select -p` shows the tools are installed (spec §3.3).
- **Only this repository:** every git call sets `GIT_DIR=<vault>/.git` and `GIT_WORK_TREE=<vault>`, so git never uses a repository in a parent folder.
- **Every git call sets** `GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0` and `LC_ALL=C`. Pushes add `GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10"`.
- **A trigger must never fail a turn:** every history call from `hooks.py` is wrapped and its errors logged to `.bron/logs/history.log`.
- **Imports:** `bron.history` imports nothing heavy at module level (no `kb`, no `loader.load`). Read `System/Settings.md` with `frontmatter.read`, not the full loader.
- **Repository config Bron sets:** `user.name=Bron`, `user.email=bron@vault.local`, `commit.gpgsign=false`, `core.hooksPath=` (empty), `core.fsmonitor=false`, `core.quotepath=false`, `gc.auto=0`, `bron.history=true`. Plus the marker file `.git/bron-history`.
- **Branch:** `main` only.
- **Ignore section markers:** `# >>> Bron (managed; edit outside these lines)` and `# <<< Bron`.
- **Save subjects and trailers:** exactly as spec §4.3.
- **Version:** this ships as 0.9.0.
- **User-facing text:** plain words, no git jargon. Save numbers are shown as `#n`.
- **AGENTS.md** stays under 8 KB.

## Review Focus

1. **A vault inside another git repository** (for example a vault folder inside a project repo). History must use only `<vault>/.git` and never write to the parent repository.
2. **File names with accents and spaces** ("Cofre Ágora", "Atlantico Partners, L.P..md"). Listing, show, restore and undo must handle them.
3. **A brand-new history:** `undo 1`, `restore --to` a time before the first save, `show 0`, and `show` past the last save should give plain errors, not tracebacks.
4. **Two saves at once** (a background ticket's stop save during the user's message). One waits or skips; neither crashes and no edits are lost.
5. **A backup destination that disappears** (Drive folder renamed, repo unreachable). The backup fails quietly, the notice appears once, and the next turn is not slowed.

Each line has its test in the owning task (Tasks 1, 3, 4, 5 and 6).

---

## File map

| File | Responsibility |
|---|---|
| `core/Engine/bron/history/__init__.py` | package docstring only |
| `core/Engine/bron/history/gitcmd.py` | `find_git`, `git_path` (cached), `run`, `GitUnavailable`, `GitError` |
| `core/Engine/bron/history/repo.py` | `HistorySettings`, `read_settings`, `state`, `ignore_text`, `write_ignore`, `apply_config`, `ensure` |
| `core/Engine/bron/history/save.py` | `Author`, `timed_lock`, `changed`, `commit`, `agent_name`, `on_prompt`, `save_turn` |
| `core/Engine/bron/history/log.py` | `Save`, `numbers`, `saves`, `format_line`, `resolve`, `show` |
| `core/Engine/bron/history/restore.py` | `restore`, `undo` |
| `core/Engine/bron/history/backup.py` | `set_destination`, `run_backup`, `record_notice`, `take_notice`, `recover`, `status_text` |
| `core/Engine/bron/history/cli.py` | `add_parser`, `handle` |
| `core/Engine/bron/hooks.py` | calls `on_prompt`; spawns the turn save and backup |
| `core/Engine/bron/cli.py` | registers `history` |
| `core/Engine/bron/model.py`, `loader.py` | `Settings.history_enabled`, `Settings.history_backup` |
| `template/System/Settings.md` | the `history:` block and its explanation |
| `core/Engine/bron/install.py` | `ensure` after sync |
| `core/Engine/bron/update.py` | `ensure` and the "now on version" save after an update or undo |
| `core/Engine/bron/migrations/vault_history.py`, `migrations/__init__.py` | 0.9.0: adds the `history:` block to existing Settings |
| `core/Engine/bron/briefing.py` | the history notice line |
| `core/Engine/bron/check.py` | `_history` issues |
| `core/Skills/history/SKILL.md` | the agents' procedure |
| `core/Manual/history.md`, `core/Manual/index.md` | the manual page and its row |
| `core/Templates/AGENTS.md.tmpl` | one line |
| `CHANGELOG.md` | 0.9.0 |
| `tests/test_history_*.py`, `tests/live/test_history.py` | tests |

Tests run with: `core/Engine/.venv/bin/python -m pytest tests/<file> -q -p no:cacheprovider`. The full suite is `core/Engine/.venv/bin/python -m pytest tests -q -p no:cacheprovider` (about 2 minutes; 1,437 passing before this plan).

Shared test helper (create in Task 2, used from then on): `tests/histkit.py`.

---

### Task 1: Finding and running git (`gitcmd.py`)

**Files:**
- Create: `core/Engine/bron/history/__init__.py`, `core/Engine/bron/history/gitcmd.py`
- Test: `tests/test_history_git.py`

**Interfaces:**
- Produces:
  - `find_git(path_env: str | None = None, xcode_select: tuple[str, ...] = ("xcode-select", "-p")) -> str | None`
  - `git_path(vault: Vault, *, refresh: bool = False) -> str | None`
  - `run(vault: Vault, *args: str, env: dict | None = None, input: bytes | None = None, check: bool = True, timeout: float = 60) -> subprocess.CompletedProcess` (bytes output)
  - `class GitUnavailable(RuntimeError)`, `class GitError(RuntimeError)`
  - `STATE = "history.json"` (in `.bron/state/`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_git.py
"""Finding git without Apple's pop-up, and running it only against the vault's own repository."""
import os
import stat
import subprocess

import pytest

from bron.history import gitcmd


def fake_exe(folder, name, script="#!/bin/sh\nexit 0\n"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_a_git_on_path_that_is_not_apples_shim_wins(tmp_path):
    git = fake_exe(tmp_path / "brew", "git")
    assert gitcmd.find_git(path_env=f"/usr/bin{os.pathsep}{tmp_path / 'brew'}") == str(git)


def test_the_shim_is_used_only_when_the_developer_tools_are_installed(tmp_path):
    tools = tmp_path / "CommandLineTools"
    fake_exe(tools / "usr" / "bin", "git")
    yes = fake_exe(tmp_path / "bin", "xsel-yes", f"#!/bin/sh\necho {tools}\n")
    no = fake_exe(tmp_path / "bin", "xsel-no", "#!/bin/sh\nexit 2\n")
    assert gitcmd.find_git(path_env="/usr/bin", xcode_select=(str(yes),)) == "/usr/bin/git"
    assert gitcmd.find_git(path_env="/usr/bin", xcode_select=(str(no),)) is None


def test_the_choice_is_cached_in_the_state_file(vault, monkeypatch):
    calls = []
    monkeypatch.setattr(gitcmd, "find_git", lambda: calls.append(1) or "/usr/bin/git")
    assert gitcmd.git_path(vault) == "/usr/bin/git"
    assert gitcmd.git_path(vault) == "/usr/bin/git"
    assert len(calls) == 1
    gitcmd.git_path(vault, refresh=True)
    assert len(calls) == 2


def test_no_git_raises_unavailable(vault, monkeypatch):
    monkeypatch.setattr(gitcmd, "git_path", lambda v, refresh=False: None)
    with pytest.raises(gitcmd.GitUnavailable):
        gitcmd.run(vault, "status")


def test_git_never_uses_a_repository_in_a_parent_folder(vault):
    parent = vault.root.parent
    subprocess.run(["git", "init", "-q", str(parent)], check=True)
    # The vault has no .git of its own: a status must fail, not report the parent repository.
    done = gitcmd.run(vault, "status", "--porcelain", check=False)
    assert done.returncode != 0
    assert not (vault.root / ".git").exists()


def test_a_failing_command_raises_with_gits_message(vault):
    gitcmd.run(vault, "init", "-q", "--initial-branch=main")
    with pytest.raises(gitcmd.GitError, match="nope"):
        gitcmd.run(vault, "rev-parse", "--verify", "nope")
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_git.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'bron.history'`.

- [ ] **Step 3: Write the implementation**

```python
# core/Engine/bron/history/__init__.py
"""The vault's change history: a private git repository saved at each turn (spec 2026-10-05-bron-vault-history)."""
```

```python
# core/Engine/bron/history/gitcmd.py
"""Finding and running git for the vault history, without ever opening Apple's "install developer tools" window,
and only ever against the vault's own repository (never one in a parent folder)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..statefile import read_json, update_json
from ..vault import Vault

SHIM = "/usr/bin/git"
STATE = "history.json"


class GitUnavailable(RuntimeError):
    """No git that can run without a pop-up."""


class GitError(RuntimeError):
    """A git command failed; the message is git's own."""


def find_git(path_env: str | None = None, xcode_select: tuple[str, ...] = ("xcode-select", "-p")) -> str | None:
    """A git on PATH that isn't Apple's shim, else the shim when the command line tools are installed, else None."""
    for folder in (os.environ.get("PATH", "") if path_env is None else path_env).split(os.pathsep):
        if not folder:
            continue
        candidate = Path(folder) / "git"
        if str(candidate) == SHIM:
            continue
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    try:
        done = subprocess.run(list(xcode_select), capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    tools = done.stdout.strip()
    if done.returncode == 0 and tools and (Path(tools) / "usr" / "bin" / "git").is_file():
        return SHIM
    return None


def git_path(vault: Vault, *, refresh: bool = False) -> str | None:
    """The git to use, cached in .bron/state/history.json; found again when missing, gone, or refresh=True."""
    state = vault.state_dir / STATE
    cached = "" if refresh else str(read_json(state, {}).get("git") or "")
    if cached and Path(cached).is_file():
        return cached
    found = find_git()

    def put(data: dict) -> None:
        data["git"] = found or ""

    update_json(state, {}, put)
    return found


def run(vault: Vault, *args: str, env: dict | None = None, input: bytes | None = None, check: bool = True,
        timeout: float = 60) -> subprocess.CompletedProcess:
    """git <args> against <vault>/.git and the vault folder only. Output is bytes."""
    exe = git_path(vault)
    if not exe:
        raise GitUnavailable("git isn't available on this Mac")
    full = {**os.environ, "GIT_DIR": str(vault.root / ".git"), "GIT_WORK_TREE": str(vault.root),
            "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", **(env or {})}
    done = subprocess.run([exe, *args], cwd=vault.root, capture_output=True, env=full, input=input, timeout=timeout)
    if check and done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip() or done.stdout.decode("utf-8", "replace").strip()
        raise GitError(f"git {args[0]}: {message}")
    return done
```

Note: with `GIT_DIR` set to a folder that doesn't exist, git refuses (`not a git repository`) instead of searching parent folders. That's what the parent-repository test checks. `git init` with `GIT_DIR` set creates exactly `<vault>/.git`.

- [ ] **Step 4: Run them to see them pass**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_git.py -q -p no:cacheprovider`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/history/__init__.py core/Engine/bron/history/gitcmd.py tests/test_history_git.py
git commit -m "History: find git without Apple's pop-up and run it only on the vault's own repository"
```

---

### Task 2: The repository (`repo.py`)

**Files:**
- Create: `core/Engine/bron/history/repo.py`, `tests/histkit.py`
- Test: `tests/test_history_repo.py`

**Interfaces:**
- Consumes: `gitcmd.run`, `gitcmd.git_path`, `gitcmd.GitUnavailable`
- Produces:
  - `@dataclass(frozen=True) class HistorySettings: enabled: bool = True; backup: str = ""`
  - `read_settings(vault) -> HistorySettings`
  - `state(vault) -> str`: one of `"off"`, `"missing"`, `"foreign"`, `"ready"`. It doesn't call git: `"ready"` means enabled, `.git` exists and the marker exists.
  - `MARKER = "bron-history"` (in `.git/`)
  - `START`, `END`, `IGNORED`
  - `ignore_text(existing: str) -> str`, `write_ignore(vault) -> bool`
  - `apply_config(vault) -> None`
  - `ensure(vault, subject: str) -> str`: returns `"off"`, `"foreign"`, `"unavailable"`, `"created"` or `"ready"`. After creating or finding the repository, it saves pending changes as Bron with `subject`.
  - `BRON_NAME = "Bron"`, `BRON_EMAIL = "bron@vault.local"`
- `tests/histkit.py` produces `hvault(vault) -> Vault` (ensures history and returns the vault), `log_subjects(vault) -> list[str]` (newest first), and `trailers(vault, rev="HEAD") -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/histkit.py
"""Helpers for the history tests."""
import subprocess

from bron.history import repo


def hvault(vault):
    assert repo.ensure(vault, "Bron: vault created") == "created"
    return vault


def git(vault, *args):
    return subprocess.run(["git", f"--git-dir={vault.root / '.git'}", f"--work-tree={vault.root}", *args],
                          capture_output=True, text=True, check=True).stdout


def log_subjects(vault):
    return git(vault, "log", "--format=%s").splitlines()


def trailers(vault, rev="HEAD"):
    out = git(vault, "log", "-1", "--format=%(trailers:only,unfold)", rev)
    return dict(line.split(": ", 1) for line in out.splitlines() if ": " in line)
```

```python
# tests/test_history_repo.py
"""Creating the vault's history: settings, the ignore section, a repository someone else made."""
import subprocess

from bron.history import repo
from histkit import git, hvault, log_subjects
from vaultkit import set_meta


def test_ensure_creates_the_repository_with_bron_s_own_config_and_a_first_save(vault):
    assert repo.ensure(vault, "Bron: vault created") == "created"
    assert repo.state(vault) == "ready"
    assert log_subjects(vault) == ["Bron: vault created"]
    config = git(vault, "config", "--local", "--list")
    for line in ("user.name=Bron", "user.email=bron@vault.local", "commit.gpgsign=false", "core.hookspath=",
                 "core.quotepath=false", "gc.auto=0", "bron.history=true"):
        assert line in config, line
    assert git(vault, "branch", "--show-current").strip() == "main"


def test_ensure_twice_saves_only_what_changed(vault):
    hvault(vault)
    assert repo.ensure(vault, "Bron: now on version 0.9.0") == "ready"
    assert log_subjects(vault) == ["Bron: vault created"]
    (vault.knowledge_dir / "Topics" / "New.md").write_text("x\n")
    repo.ensure(vault, "Bron: now on version 0.9.1")
    assert log_subjects(vault)[0] == "Bron: now on version 0.9.1"


def test_machine_data_and_generated_files_stay_out(vault):
    hvault(vault)
    for rel in (".bron/state/x.json", ".claude/settings.json", "AGENTS.md", ".obsidian/workspace.json", ".DS_Store"):
        path = vault.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    assert git(vault, "status", "--porcelain") == ""


def test_the_users_own_ignore_lines_are_kept(vault):
    (vault.root / ".gitignore").write_text("mine.txt\n")
    hvault(vault)
    text = (vault.root / ".gitignore").read_text()
    assert text.startswith("mine.txt\n") and repo.START in text and repo.END in text
    again = repo.ignore_text(text.replace(".bron/", ".bron-old/"))
    assert again.count(repo.START) == 1 and ".bron/\n" in again and "mine.txt" in again


def test_a_repository_bron_did_not_make_is_left_alone(vault):
    subprocess.run(["git", "init", "-q", str(vault.root)], check=True)
    assert repo.ensure(vault, "Bron: vault created") == "foreign"
    assert repo.state(vault) == "foreign"
    assert subprocess.run(["git", "-C", str(vault.root), "log"], capture_output=True).returncode != 0  # no commits made


def test_history_off_in_settings_creates_nothing(vault):
    set_meta(vault.settings_file, history={"enabled": False, "backup": ""})
    assert repo.ensure(vault, "Bron: vault created") == "off"
    assert not (vault.root / ".git").exists()
    assert repo.read_settings(vault) == repo.HistorySettings(enabled=False, backup="")


def test_settings_default_to_on_without_a_history_block(vault):
    assert repo.read_settings(vault) == repo.HistorySettings(enabled=True, backup="")


def test_no_git_means_unavailable_and_nothing_created(vault, monkeypatch):
    from bron.history import gitcmd
    monkeypatch.setattr(gitcmd, "git_path", lambda v, refresh=False: None)
    assert repo.ensure(vault, "Bron: vault created") == "unavailable"
    assert not (vault.root / ".git").exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_repo.py -q -p no:cacheprovider`
Expected: FAIL, `ImportError: cannot import name 'repo'`.

- [ ] **Step 3: Write the implementation**

```python
# core/Engine/bron/history/repo.py
"""The vault's history repository: its settings, creating it, Bron's part of .gitignore, and whether it's Bron's."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .. import frontmatter as fm
from ..vault import Vault
from . import gitcmd

BRON_NAME = "Bron"
BRON_EMAIL = "bron@vault.local"
MARKER = "bron-history"
START = "# >>> Bron (managed; edit outside these lines)"
END = "# <<< Bron"
IGNORED = (".bron/", ".claude/", ".codex/", ".agents/", "AGENTS.md", "CLAUDE.md", ".obsidian/workspace.json",
           ".obsidian/workspace-mobile.json", ".obsidian/workspaces.json", ".trash/", ".DS_Store")
CONFIG = (("user.name", BRON_NAME), ("user.email", BRON_EMAIL), ("commit.gpgsign", "false"), ("core.hooksPath", ""),
          ("core.fsmonitor", "false"), ("core.quotepath", "false"), ("gc.auto", "0"), ("bron.history", "true"))


@dataclass(frozen=True)
class HistorySettings:
    enabled: bool = True
    backup: str = ""


def read_settings(vault: Vault) -> HistorySettings:
    """The history block of System/Settings.md; anything unreadable counts as the defaults."""
    try:
        block = fm.read(vault.settings_file).meta.get("history")
    except Exception:  # noqa: BLE001 - settings problems are the health check's job
        return HistorySettings()
    if not isinstance(block, dict):
        return HistorySettings()
    enabled = block.get("enabled", True)
    backup = block.get("backup") or ""
    return HistorySettings(enabled=enabled if isinstance(enabled, bool) else True,
                           backup=backup.strip() if isinstance(backup, str) else "")


def state(vault: Vault) -> str:
    """off, missing, foreign or ready, without running git (cheap enough for every message)."""
    if not read_settings(vault).enabled:
        return "off"
    git_dir = vault.root / ".git"
    if not git_dir.exists():
        return "missing"
    return "ready" if (git_dir / MARKER).is_file() else "foreign"


def ignore_text(existing: str) -> str:
    """The .gitignore text with Bron's section in place (replaced if there, appended if not)."""
    block = "\n".join([START, *IGNORED, END]) + "\n"
    if START in existing and END in existing:
        before, rest = existing.split(START, 1)
        after = rest.split(END, 1)[1].lstrip("\n")
        return before + block + after
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return existing + block


def write_ignore(vault: Vault) -> bool:
    path = vault.root / ".gitignore"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    new = ignore_text(old)
    if new == old:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def apply_config(vault: Vault) -> None:
    for key, value in CONFIG:
        gitcmd.run(vault, "config", "--local", key, value)
    (vault.root / ".git" / MARKER).write_text("This repository is Bron's change history of the vault.\n", encoding="utf-8")


def ensure(vault: Vault, subject: str) -> str:
    """Create the history if needed (on install, update and migration) and save what's pending as Bron."""
    from .save import BRON, commit  # save imports repo

    found = state(vault)
    if found in ("off", "foreign"):
        return found
    if not gitcmd.git_path(vault):
        return "unavailable"
    created = found == "missing"
    write_ignore(vault)
    if created:
        gitcmd.run(vault, "init", "-q", "--initial-branch=main")
    apply_config(vault)
    commit(vault, author=BRON, subject=subject, trailers={})
    return "created" if created else "ready"
```

Note: `commit` comes from Task 3. To keep Task 2 runnable on its own, write a temporary minimal `save.py` in this task with `Author`, `BRON` and a `commit` that runs `add -A`, checks `diff --cached --quiet` and commits. Task 3 replaces it with the full module and keeps the same signatures. Use this minimal version:

```python
# core/Engine/bron/history/save.py  (minimal for Task 2; Task 3 completes it)
"""Saving the vault's changes, credited to the user, an agent or Bron."""
from __future__ import annotations

from dataclasses import dataclass

from ..vault import Vault
from . import gitcmd


@dataclass(frozen=True)
class Author:
    name: str
    email: str


BRON = Author("Bron", "bron@vault.local")


def commit(vault: Vault, *, author: Author, subject: str, trailers: dict[str, str]) -> bool:
    """Stage everything and save it with this author; False when there was nothing to save."""
    gitcmd.run(vault, "add", "-A")
    if gitcmd.run(vault, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    lines = [f"{key}: {value}" for key, value in trailers.items() if value]
    message = subject + ("\n\n" + "\n".join(lines) if lines else "") + "\n"
    gitcmd.run(vault, "commit", "-q", "--no-verify", "-F", "-", input=message.encode("utf-8"),
               env={"GIT_AUTHOR_NAME": author.name, "GIT_AUTHOR_EMAIL": author.email})
    return True
```

- [ ] **Step 4: Run them to see them pass**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_git.py tests/test_history_repo.py -q -p no:cacheprovider`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/history/repo.py core/Engine/bron/history/save.py tests/histkit.py tests/test_history_repo.py
git commit -m "History: create the vault's repository with its own config and Bron's ignore section"
```

---

### Task 3: Credited saves and the timed lock (`save.py`)

**Files:**
- Modify: `core/Engine/bron/history/save.py` (replace the Task 2 minimal version)
- Test: `tests/test_history_save.py`

**Interfaces:**
- Consumes: `gitcmd.run`, `repo.state`, `repo.read_settings`
- Produces (keeping `Author`, `BRON`, `commit` from Task 2):
  - `timed_lock(vault, seconds: float) -> ContextManager[bool]`, on `.bron/state/history.lock`
  - `changed(vault) -> bool`
  - `agent_name(vault) -> str`
  - `user_author(vault) -> Author`, `agent_author(name: str) -> Author`
  - `TURNS = "history-turns.json"`
  - `on_prompt(vault, *, cli: str, session_id: str, prompt: str, lock_seconds: float = 0.5) -> None`
  - `save_turn(vault, *, cli: str, session_id: str, lock_seconds: float = 2.0) -> bool`
  - `short(text: str, limit: int = 80) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_save.py
"""Saves credited to the user and to agents, with the trailers history filters by."""
import fcntl

from bron.history import save
from histkit import hvault, log_subjects, trailers
from vaultkit import set_meta


def edit(vault, rel="Knowledge/Topics/Rent.md", text="- a fact\n"):
    path = vault.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def test_the_users_edits_are_saved_before_the_agents_turn(vault):
    hvault(vault)
    set_meta(vault.settings_file, user_name="Guilherme")
    edit(vault)
    save.on_prompt(vault, cli="claude", session_id="s1", prompt="Update the rent page with the new lease terms please")
    assert log_subjects(vault)[0] == "You: edits in the vault"
    edit(vault, text="- the agent's fact\n")
    assert save.save_turn(vault, cli="claude", session_id="s1") is True
    assert log_subjects(vault)[0] == "Bron (Claude Code): Update the rent page with the new lease terms please"
    t = trailers(vault)
    assert t["Bron-Agent"] == "bron" and t["Bron-App"] == "claude" and t["Bron-Session"] == "s1"
    assert "Bron-Includes-User-Edits" not in t


def test_the_user_save_is_credited_to_the_users_name(vault):
    hvault(vault)
    set_meta(vault.settings_file, user_name="Guilherme")
    edit(vault)
    save.on_prompt(vault, cli="codex", session_id="s1", prompt="hi")
    from histkit import git
    assert git(vault, "log", "-1", "--format=%an <%ae>").strip() == "Guilherme <user@vault.local>"


def test_nothing_changed_means_no_save(vault):
    hvault(vault)
    save.on_prompt(vault, cli="claude", session_id="s1", prompt="hi")
    assert save.save_turn(vault, cli="claude", session_id="s1") is False
    assert log_subjects(vault) == ["Bron: vault created"]


def test_a_long_request_is_cut_to_80_characters(vault):
    assert save.short("word " * 40).endswith("…") and len(save.short("word " * 40)) <= 80
    assert save.short("  two\n lines ") == "two lines"


def test_a_ticket_run_names_the_ticket(vault, monkeypatch):
    hvault(vault)
    monkeypatch.setenv("BRON_TICKET", "T-0007")
    monkeypatch.setenv("BRON_AGENT", "Bron")
    save.on_prompt(vault, cli="claude", session_id="s2", prompt="Work ticket T-0007")
    edit(vault)
    save.save_turn(vault, cli="claude", session_id="s2")
    assert log_subjects(vault)[0].startswith("Bron (Claude Code), ticket T-0007")
    assert trailers(vault)["Bron-Ticket"] == "T-0007"


def test_a_busy_lock_skips_the_user_save_and_the_agent_save_says_so(vault):
    hvault(vault)
    edit(vault)
    lock = vault.state_dir / "history.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        save.on_prompt(vault, cli="claude", session_id="s3", prompt="hi", lock_seconds=0.05)
        assert log_subjects(vault) == ["Bron: vault created"]  # skipped, not waited for
        assert save.save_turn(vault, cli="claude", session_id="s3", lock_seconds=0.05) is False  # gives up
    assert save.save_turn(vault, cli="claude", session_id="s3") is True
    assert trailers(vault)["Bron-Includes-User-Edits"] == "yes"


def test_history_off_saves_nothing(vault):
    hvault(vault)
    set_meta(vault.settings_file, history={"enabled": False, "backup": ""})
    edit(vault)
    save.on_prompt(vault, cli="claude", session_id="s1", prompt="hi")
    assert save.save_turn(vault, cli="claude", session_id="s1") is False
    assert log_subjects(vault) == ["Bron: vault created"]


def test_accented_and_comma_file_names_are_saved(vault):
    hvault(vault)
    edit(vault, rel="Knowledge/Organisations/Atlantico Partners, L.P..md")
    edit(vault, rel="Knowledge/Organisations/São Paulo Ágora.md")
    save.on_prompt(vault, cli="claude", session_id="s1", prompt="hi")
    from histkit import git
    names = git(vault, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert "Knowledge/Organisations/Atlantico Partners, L.P..md" in names
    assert "Knowledge/Organisations/São Paulo Ágora.md" in names
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_save.py -q -p no:cacheprovider`
Expected: FAIL, `AttributeError: module 'bron.history.save' has no attribute 'on_prompt'`.

- [ ] **Step 3: Write the implementation** (the whole file)

```python
# core/Engine/bron/history/save.py
"""Saving the vault's changes, credited to the user, an agent or Bron (spec §4).

on_prompt runs inside the user-prompt trigger, so it has a 50 ms budget: one `git status`, and a save only when
something changed. save_turn runs in a detached process started by the stop trigger."""
from __future__ import annotations

import contextlib
import fcntl
import os
import time
from dataclasses import dataclass
from typing import Iterator

from .. import frontmatter as fm
from ..model import CLI_NAMES, slug
from ..statefile import read_json, update_json
from ..vault import Vault
from . import gitcmd, repo

TURNS = "history-turns.json"
KEEP_TURNS = 50


@dataclass(frozen=True)
class Author:
    name: str
    email: str


BRON = Author(repo.BRON_NAME, repo.BRON_EMAIL)


def agent_author(name: str) -> Author:
    return Author(name, f"{slug(name) or 'agent'}@vault.local")


def _meta(vault: Vault) -> dict:
    try:
        return fm.read(vault.settings_file).meta
    except Exception:  # noqa: BLE001
        return {}


def user_author(vault: Vault) -> Author:
    name = str(_meta(vault).get("user_name") or "").strip()
    return Author(name or "You", "user@vault.local")


def agent_name(vault: Vault) -> str:
    """The agent this session runs as: BRON_AGENT, else the default agent (as the briefing decides)."""
    return os.environ.get("BRON_AGENT") or str(_meta(vault).get("default_agent") or "Bron")


def short(text: str, limit: int = 80) -> str:
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


@contextlib.contextmanager
def timed_lock(vault: Vault, seconds: float) -> Iterator[bool]:
    """Yields True with the history lock held, or False if it stayed busy for `seconds`."""
    path = vault.state_dir / "history.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        deadline = time.monotonic() + seconds
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.02)
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def changed(vault: Vault) -> bool:
    out = gitcmd.run(vault, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    return bool(out)


def commit(vault: Vault, *, author: Author, subject: str, trailers: dict[str, str]) -> bool:
    """Stage everything and save it with this author; False when there was nothing to save."""
    gitcmd.run(vault, "add", "-A")
    if gitcmd.run(vault, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    lines = [f"{key}: {value}" for key, value in trailers.items() if value]
    message = subject + ("\n\n" + "\n".join(lines) if lines else "") + "\n"
    gitcmd.run(vault, "commit", "-q", "--no-verify", "-F", "-", input=message.encode("utf-8"),
               env={"GIT_AUTHOR_NAME": author.name, "GIT_AUTHOR_EMAIL": author.email})
    return True


def _remember_turn(vault: Vault, session_id: str, prompt: str, skipped: bool) -> None:
    def put(data: dict) -> None:
        data[session_id or "-"] = {"prompt": short(prompt), "skipped": skipped, "time": time.time()}
        for old in sorted(data, key=lambda k: data[k].get("time", 0))[:-KEEP_TURNS]:
            del data[old]

    update_json(vault.state_dir / TURNS, {}, put)


def _take_turn(vault: Vault, session_id: str) -> dict:
    found: dict = {}

    def take(data: dict) -> None:
        found.update(data.pop(session_id or "-", {}) or {})

    update_json(vault.state_dir / TURNS, {}, take)
    return found


def on_prompt(vault: Vault, *, cli: str, session_id: str, prompt: str, lock_seconds: float = 0.5) -> None:
    """user-prompt trigger: save the user's edits made since the last save, then note the turn for save_turn."""
    if repo.state(vault) != "ready":
        return
    skipped = False
    if not os.environ.get("BRON_TICKET"):  # a headless ticket run has no user editing alongside it
        with timed_lock(vault, lock_seconds) as got:
            if not got:
                skipped = True
            elif changed(vault):
                commit(vault, author=user_author(vault), subject="You: edits in the vault",
                       trailers={"Bron-Session": session_id})
    _remember_turn(vault, session_id, prompt, skipped)


def _ticket_title(vault: Vault, ticket: str) -> str:
    from ..tickets import list_tickets

    tickets, _ = list_tickets(vault)
    return next((t.title for t in tickets if t.id == ticket), "")


def _running(vault: Vault, own: str) -> str:
    from ..tickets import list_tickets

    tickets, _ = list_tickets(vault)
    return ", ".join(t.id for t in tickets if t.status == "in-progress" and t.id != own)


def save_turn(vault: Vault, *, cli: str, session_id: str, lock_seconds: float = 2.0) -> bool:
    """The detached save after an agent's reply. False when off, busy or nothing changed."""
    if repo.state(vault) != "ready":
        return False
    turn = _take_turn(vault, session_id)
    agent = agent_name(vault)
    app = CLI_NAMES.get(cli, cli)
    ticket = os.environ.get("BRON_TICKET", "")
    if ticket:
        subject = f"{agent} ({app}), ticket {ticket}: {short(_ticket_title(vault, ticket) or turn.get('prompt', ''))}"
    else:
        subject = f"{agent} ({app}): {turn.get('prompt') or 'a reply'}"
    trailers = {"Bron-Agent": slug(agent), "Bron-App": cli, "Bron-Session": session_id, "Bron-Ticket": ticket,
                "Bron-Also-Running": _running(vault, ticket),
                "Bron-Includes-User-Edits": "yes" if turn.get("skipped") else ""}
    with timed_lock(vault, lock_seconds) as got:
        if not got or not changed(vault):
            if not got and turn:
                _remember_turn(vault, session_id, turn.get("prompt", ""), bool(turn.get("skipped")))
            return False
        return commit(vault, author=agent_author(agent), subject=subject, trailers=trailers)
```

Check that `slug` and `CLI_NAMES` are importable from `bron.model` (`briefing.py` imports both from `.model`). Check that `list_tickets` returns `(tickets, problems)` with `.id`, `.title` and `.status` (see `briefing.py`).

- [ ] **Step 4: Run them to see them pass**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_git.py tests/test_history_repo.py tests/test_history_save.py -q -p no:cacheprovider`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/history/save.py tests/test_history_save.py
git commit -m "History: saves credited to the user and to agents, with a timed lock and filter trailers"
```

---

### Task 4: The triggers and `bron history save`

**Files:**
- Create: `core/Engine/bron/history/cli.py` (the `save` sub-command only in this task; Tasks 5–7 add the rest)
- Modify: `core/Engine/bron/hooks.py` (user-prompt, stop, session-end branches), `core/Engine/bron/cli.py` (register and dispatch `history`)
- Test: `tests/test_history_hooks.py`

**Interfaces:**
- Consumes: `save.on_prompt`, `save.save_turn`, `repo.state`, `background.spawn_detached`
- Produces:
  - in `hooks.py`: `_history_prompt(cli, payload) -> None` and `_history_spawn(cli, payload, argv_tail: list[str]) -> None`
  - in `history/cli.py`: `add_parser(sub) -> None` and `handle(args, vault) -> int`, with the `save --turn --cli C --session S` command (hidden help)
  - the CLI dispatch: `if args.command == "history": return history_cli.handle(args, vault)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_hooks.py
"""The triggers: the user's edits are saved before routing; the agent's save and the backup start detached."""
import io
import json

from bron import hooks
from bron.history import save
from histkit import hvault, log_subjects


def fire(event, payload, cli="claude"):
    out = io.StringIO()
    hooks.main(event, cli, stdin=io.StringIO(json.dumps(payload)), stdout=out)
    return out.getvalue()


def test_user_prompt_saves_the_users_edits_first(vault, monkeypatch):
    hvault(vault)
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    (vault.knowledge_dir / "Topics" / "Mine.md").write_text("x\n")
    fire("user-prompt", {"prompt": "hello", "session_id": "s1"})
    assert log_subjects(vault)[0] == "You: edits in the vault"


def test_stop_spawns_a_detached_turn_save_and_returns(vault, monkeypatch):
    hvault(vault)
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    started = []
    monkeypatch.setattr("bron.background.spawn_detached", lambda v, argv, log, **kw: started.append((argv, log)) or True)
    fire("stop", {"session_id": "s1", "transcript_path": ""})
    assert (["history", "save", "--turn", "--cli", "claude", "--session", "s1"], "history.log") in started


def test_session_end_spawns_the_backup(vault, monkeypatch):
    hvault(vault)
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    started = []
    monkeypatch.setattr("bron.background.spawn_detached", lambda v, argv, log, **kw: started.append(argv) or True)
    fire("session-end", {"session_id": "s1", "transcript_path": ""})
    assert ["history", "backup", "--run"] in started


def test_no_history_means_nothing_is_spawned(vault, monkeypatch):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))  # no hvault: the repository doesn't exist
    started = []
    monkeypatch.setattr("bron.background.spawn_detached", lambda v, argv, log, **kw: started.append(argv) or True)
    fire("stop", {"session_id": "s1", "transcript_path": ""})
    assert not [a for a in started if a[:1] == ["history"]]


def test_a_failing_history_never_fails_the_trigger(vault, monkeypatch):
    hvault(vault)
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    monkeypatch.setattr(save, "on_prompt", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hooks.main("user-prompt", "claude", stdin=io.StringIO('{"prompt": "hi"}'), stdout=io.StringIO()) == 0
    assert "boom" in (vault.bron_dir / "logs" / "history.log").read_text()


def test_bron_history_save_turn_saves(vault, monkeypatch, capsys):
    from bron.cli import main
    hvault(vault)
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    save.on_prompt(vault, cli="codex", session_id="s9", prompt="Write the memo")
    (vault.knowledge_dir / "Topics" / "Memo.md").write_text("x\n")
    assert main(["history", "save", "--turn", "--cli", "codex", "--session", "s9"]) == 0
    assert log_subjects(vault)[0] == "Bron (Codex): Write the memo"
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_hooks.py -q -p no:cacheprovider`
Expected: FAIL (no history save in the trigger; `history` isn't a command).

- [ ] **Step 3: Write the implementation**

In `core/Engine/bron/hooks.py`, add these helpers next to `_start_summary`:

```python
def _history_log(cli: str, exc: Exception) -> None:
    try:
        from .vault import Vault

        log = Vault.find().bron_dir / "logs" / "history.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {cli}: {exc.__class__.__name__}: {exc}\n")
    except Exception:  # noqa: BLE001
        pass


def _history_prompt(cli: str, payload: dict) -> None:
    """Save the user's edits before the agent starts (spec §4.1); never fails the message."""
    try:
        from .history import save
        from .vault import Vault

        save.on_prompt(Vault.find(), cli=cli, session_id=str(payload.get("session_id") or ""),
                       prompt=str(payload.get("prompt") or ""))
    except Exception as exc:  # noqa: BLE001
        _history_log(cli, exc)


def _history_spawn(cli: str, argv_tail: list[str]) -> None:
    """Start `bron history …` detached when the vault has a history; never waits, never fails."""
    try:
        from . import background
        from .history import repo
        from .vault import Vault

        vault = Vault.find()
        if repo.state(vault) == "ready":
            background.spawn_detached(vault, ["history", *argv_tail], "history.log")
    except Exception as exc:  # noqa: BLE001
        _history_log(cli, exc)
```

In `main`, in the `QUICK` branch after `_marker(...)`:

```python
            if event == "stop":
                _history_spawn(cli, ["save", "--turn", "--cli", cli, "--session", str(payload.get("session_id") or "")])
            if event == "session-end":
                _history_spawn(cli, ["backup", "--run"])
```

In the `user-prompt` branch, as the first line after `payload = _payload(stdin)`:

```python
            _history_prompt(cli, payload)
```

Make sure `hooks.py` imports `time` (add `import time` at the top if it's missing). The test patches `bron.background.spawn_detached`, so `_history_spawn` must call it as `background.spawn_detached` (module attribute), not through a `from … import spawn_detached` name.

Create `core/Engine/bron/history/cli.py`:

```python
"""`bron history …`: list, show, restore, undo, backup, recover, status, and the trigger's save."""
from __future__ import annotations

import argparse

from ..vault import Vault


def add_parser(sub) -> None:
    parser = sub.add_parser("history", help="the vault's change history: what changed, and putting things back")
    commands = parser.add_subparsers(dest="history_command")
    saver = commands.add_parser("save", help=argparse.SUPPRESS)
    saver.add_argument("--turn", action="store_true")
    saver.add_argument("--cli", default="claude")
    saver.add_argument("--session", default="")


def handle(args, vault: Vault) -> int:
    from . import save

    if args.history_command == "save":
        save.save_turn(vault, cli=args.cli, session_id=args.session)
        return 0
    print("Say what you'd like: `bron history` lists recent saves.")
    return 0
```

In `core/Engine/bron/cli.py`, register it next to the others in `build_parser`:

```python
    from .history import cli as history_cli
    ...
    history_cli.add_parser(sub)
```

Add the dispatch next to `memory`/`kb`:

```python
    if args.command == "history":
        from .history import cli as history_cli

        return history_cli.handle(args, vault)
```

Follow how `memory` gets `vault` in `cli.py:125-128` (same pattern).

- [ ] **Step 4: Run them to see them pass, then the hook and CLI suites**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_hooks.py tests/test_hooks.py tests/test_cli.py tests/test_handoff_content.py -q -p no:cacheprovider`
Expected: all passed. `test_handoff_content.py` parses documented commands. Nothing documents `history` yet, so it stays green.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/hooks.py core/Engine/bron/cli.py core/Engine/bron/history/cli.py tests/test_history_hooks.py
git commit -m "History: the user's edits are saved when a message arrives; the agent's turn is saved in the background"
```

---

### Task 5: Looking back (`log.py`; `bron history`, `history show`)

**Files:**
- Create: `core/Engine/bron/history/log.py`
- Modify: `core/Engine/bron/history/cli.py`
- Test: `tests/test_history_log.py`

**Interfaces:**
- Consumes: `gitcmd.run`, `gitcmd.GitError`
- Produces:
  - `@dataclass(frozen=True) class Save: number: int; commit: str; when: float; author: str; email: str; subject: str; trailers: dict; files: list[str]`
  - `numbers(vault) -> dict[str, int]` (commit → #n, oldest = 1)
  - `saves(vault, *, path: str = "", since: str = "", agent: str = "", ticket: str = "", limit: int = 20) -> list[Save]` (newest first)
  - `format_line(s: Save) -> str`
  - `resolve(vault, ref: str) -> Save`, raising `HistoryError` (a `RuntimeError` with a plain message) for unknown refs
  - `show(vault, ref: str, *, max_lines: int = 200) -> str`
  - `class HistoryError(RuntimeError)`
- CLI: `bron history [path] [--since S] [--agent A] [--ticket T] [--limit N]` and `bron history show <ref>`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_log.py
"""Numbered saves, filters, and showing one save in plain words."""
import pytest

from bron.history import log, save
from histkit import hvault


def turn(vault, rel, text, prompt, *, agent="Bron", monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("BRON_AGENT", agent)
    save.on_prompt(vault, cli="claude", session_id="s", prompt=prompt)
    path = vault.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    assert save.save_turn(vault, cli="claude", session_id="s")


@pytest.fixture
def busy(vault, monkeypatch):
    hvault(vault)
    turn(vault, "Knowledge/Topics/Rent.md", "rent 100\n", "Add the rent", monkeypatch=monkeypatch)
    turn(vault, "Knowledge/Organisations/São Paulo Ágora.md", "x\n", "Add São Paulo", monkeypatch=monkeypatch)
    turn(vault, "Knowledge/Topics/Rent.md", "rent 120\n", "Raise the rent", agent="CFO", monkeypatch=monkeypatch)
    return vault


def test_saves_are_numbered_from_the_first_and_listed_newest_first(busy):
    found = log.saves(busy)
    assert [s.number for s in found] == [4, 3, 2, 1]
    assert found[0].subject == "CFO (Claude Code): Raise the rent"
    line = log.format_line(found[0])
    assert line.startswith("#4  ") and "CFO (Claude Code): Raise the rent" in line and line.endswith("1 page")


def test_filters_by_page_agent_and_since(busy):
    assert [s.number for s in log.saves(busy, path="Knowledge/Topics/Rent.md")] == [4, 2]
    assert [s.number for s in log.saves(busy, agent="CFO")] == [4]
    assert [s.number for s in log.saves(busy, path="Knowledge/Organisations/São Paulo Ágora.md")] == [3]
    assert log.saves(busy, since="2999-01-01") == []


def test_resolve_by_number_and_by_time(busy):
    assert log.resolve(busy, "#2").number == 2
    assert log.resolve(busy, "3").number == 3
    assert log.resolve(busy, "2999-01-01 10:00").number == 4  # the last save at or before then


def test_plain_errors_for_refs_that_dont_exist(busy):
    for ref in ("#0", "99", "1999-01-01", "yesterday-ish"):
        with pytest.raises(log.HistoryError):
            log.resolve(busy, ref)


def test_show_lists_pages_and_lines(busy):
    text = log.show(busy, "4")
    assert "#4" in text and "Knowledge/Topics/Rent.md" in text
    assert "- rent 100" in text and "+ rent 120" in text


def test_the_cli_lists_and_shows(busy, monkeypatch, capsys):
    from bron.cli import main
    monkeypatch.setenv("BRON_VAULT", str(busy.root))
    assert main(["history", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    assert "#4" in out and "#3" in out and "#2" not in out
    assert main(["history", "show", "99"]) == 1
    assert "There's no save #99" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_log.py -q -p no:cacheprovider`
Expected: FAIL, `ImportError: cannot import name 'log'`.

- [ ] **Step 3: Write the implementation**

```python
# core/Engine/bron/history/log.py
"""Looking back: numbered saves (#1 is the first; numbers never change because history is never rewritten)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..model import slug
from ..vault import Vault
from . import gitcmd

SEP, END = "\x1f", "\x1e"
FORMAT = SEP.join(["%H", "%at", "%an", "%ae", "%s", "%(trailers:only,unfold)"]) + END
WHEN = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")


class HistoryError(RuntimeError):
    """A plain-words problem with a history request."""


@dataclass(frozen=True)
class Save:
    number: int
    commit: str
    when: float
    author: str
    email: str
    subject: str
    trailers: dict
    files: list


def numbers(vault: Vault) -> dict[str, int]:
    out = gitcmd.run(vault, "rev-list", "--reverse", "--first-parent", "main", check=False).stdout.decode()
    return {commit: i + 1 for i, commit in enumerate(out.split())}


def _records(vault: Vault, numbered: dict[str, int], *selection: str) -> list[Save]:
    """Saves for a `git log` selection (revisions, options, `-- path`), newest first, in two passes:
    the details, then the file names, matched by commit."""
    raw = gitcmd.run(vault, "log", "--first-parent", f"--format={FORMAT}", *selection).stdout.decode("utf-8", "replace")
    names_raw = gitcmd.run(vault, "log", "--first-parent", "--format=%x1e%H", "--name-only", *selection).stdout.decode("utf-8", "replace")
    names: dict[str, list[str]] = {}
    for chunk in names_raw.split(END):
        lines = [l for l in chunk.splitlines() if l.strip()]
        if lines:
            names[lines[0]] = lines[1:]
    found = []
    for record in raw.split(END):
        parts = record.strip("\n").split(SEP)
        if len(parts) < 6:
            continue
        commit, at, author, email, subject, trailer_text = parts[:6]
        trailers = dict(l.split(": ", 1) for l in trailer_text.splitlines() if ": " in l)
        found.append(Save(numbered.get(commit, 0), commit, float(at), author, email, subject, trailers,
                          names.get(commit, [])))
    return found


def saves(vault: Vault, *, path: str = "", since: str = "", agent: str = "", ticket: str = "", limit: int = 20) -> list[Save]:
    numbered = numbers(vault)
    if not numbered:
        return []
    selection = ([f"--since={since}"] if since else []) + ["main"] + (["--", path] if path else [])
    found = _records(vault, numbered, *selection)
    if agent:
        key = slug(agent)
        found = [s for s in found if s.trailers.get("Bron-Agent") == key
                 or (key in ("you", "user") and s.email == "user@vault.local") or slug(s.author) == key]
    if ticket:
        found = [s for s in found if s.trailers.get("Bron-Ticket", "").upper() == ticket.upper()]
    return found[:limit]


def _pages(n: int) -> str:
    return f"{n} page" + ("" if n == 1 else "s")


def format_line(s: Save) -> str:
    stamp = time.strftime("%b %-d %H:%M", time.localtime(s.when))
    return f"#{s.number}  {stamp}  {s.subject}  {_pages(len(s.files))}"


def resolve(vault: Vault, ref: str) -> Save:
    ref = ref.strip()
    numbered = numbers(vault)
    by_number = {n: c for c, n in numbered.items()}
    if re.fullmatch(r"#?\d+", ref):
        n = int(ref.lstrip("#"))
        if n not in by_number:
            raise HistoryError(f"There's no save #{n}; the history has {len(by_number)}.")
        commit = by_number[n]
    elif WHEN.match(ref):
        out = gitcmd.run(vault, "rev-list", "-1", "--first-parent", f"--before={ref}", "main", check=False).stdout.decode().strip()
        if not out:
            raise HistoryError(f"There's no save at or before {ref}; the history starts later.")
        commit = out
    else:
        raise HistoryError(f"'{ref}' isn't a save number (#12) or a time (2026-10-05 or 2026-10-05 14:30).")
    return _records(vault, numbered, "-1", commit)[0]


def show(vault: Vault, ref: str, *, max_lines: int = 200) -> str:
    s = resolve(vault, ref)
    lines = [format_line(s), ""]
    parent = ["--root"] if s.number == 1 else []
    diff = gitcmd.run(vault, "show", "--first-parent", "--format=", "--no-color", "--unified=1", *parent, s.commit).stdout
    shown = 0
    for line in diff.decode("utf-8", "replace").splitlines():
        if line.startswith("+++ b/"):
            lines.append(line[6:])
        elif line.startswith(("---", "diff --git", "index ", "@@", "new file", "deleted file")):
            continue
        elif line.startswith(("+", "-")):
            if shown >= max_lines:
                continue
            lines.append(f"  {line[0]} {line[1:]}")
            shown += 1
    hidden = sum(1 for l in diff.decode("utf-8", "replace").splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))) - shown
    if hidden > 0:
        lines.append(f"…and {hidden} more changed lines.")
    return "\n".join(lines)
```

Deleted files show as `+++ /dev/null` in `show`; use the `--- a/` name in that case. `_records` reads file names in a second `git log` pass, so page filters and accented names stay reliable.

In `history/cli.py`, extend `add_parser` (the default list is the bare command):

```python
    parser.add_argument("path", nargs="?", default="")
    parser.add_argument("--since", default="")
    parser.add_argument("--agent", default="")
    parser.add_argument("--ticket", default="")
    parser.add_argument("--limit", type=int, default=20)
    shower = commands.add_parser("show", help="what one save changed")
    shower.add_argument("ref")
```

In `handle`:

```python
    from . import log
    from .gitcmd import GitError, GitUnavailable
    from .repo import state

    found = state(vault)
    if found != "ready" and args.history_command != "save":
        print({"off": "The change history is turned off (history: enabled: false in System/Settings.md).",
               "missing": "This vault has no change history yet.",
               "foreign": "This vault has its own git repository, so Bron keeps no history of its own."}[found])
        return 1
    try:
        if args.history_command == "show":
            print(log.show(vault, args.ref))
            return 0
        if args.history_command is None:
            found = log.saves(vault, path=args.path, since=args.since, agent=args.agent, ticket=args.ticket, limit=args.limit)
            print("\n".join(log.format_line(s) for s in found) if found else "No saves match.")
            return 0
    except log.HistoryError as exc:
        print(exc)
        return 1
    except (GitError, GitUnavailable) as exc:
        print(f"The history couldn't be read: {exc}")
        return 1
```

- [ ] **Step 4: Run them to see them pass**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_log.py tests/test_history_hooks.py -q -p no:cacheprovider`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/history/log.py core/Engine/bron/history/cli.py tests/test_history_log.py
git commit -m "History: numbered saves, filters by page, agent, ticket and time, and showing one save"
```

---

### Task 6: Putting back (`restore.py`; `history restore`, `history undo`)

**Files:**
- Create: `core/Engine/bron/history/restore.py`
- Modify: `core/Engine/bron/history/cli.py`
- Test: `tests/test_history_restore.py`

**Interfaces:**
- Consumes: `log.resolve`, `log.HistoryError`, `save.timed_lock`, `save.commit`, `save.agent_name`, `save.agent_author`, `save.user_author`, `gitcmd.run`
- Produces:
  - `find_path(vault, target: str, commit: str) -> str` (vault-relative; accepts a path, or a wiki page title, which looks for `Knowledge/**/<title>.md`)
  - `restore(vault, target: str, to: str, *, preview: bool) -> str`, raising `HistoryError`
  - `undo(vault, ref: str, *, preview: bool) -> str`, raising `HistoryError`
- CLI: `bron history restore '<page>' --to <ref> [--preview]` and `bron history undo <ref> [--preview]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_restore.py
"""Restore a page or folder, undo a turn; previews first; history is only ever added to."""
import pytest

from bron.history import log, restore, save
from histkit import hvault, log_subjects
from vaultkit import set_meta


def turn(vault, rel, text, prompt):
    save.on_prompt(vault, cli="claude", session_id="s", prompt=prompt)
    path = vault.root / rel
    if text is None:
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    save.save_turn(vault, cli="claude", session_id="s")


@pytest.fixture
def hist(vault):
    hvault(vault)
    set_meta(vault.settings_file, user_name="Guilherme")
    turn(vault, "Knowledge/Topics/Rent.md", "rent 100\n", "Add the rent")          # 2
    turn(vault, "Knowledge/Topics/Rent.md", "rent 120\n", "Raise the rent")        # 3
    turn(vault, "Knowledge/Topics/Fees.md", "fee 2%\n", "Add fees")                # 4
    return vault


def rent(vault):
    return (vault.root / "Knowledge/Topics/Rent.md").read_text()


def test_restore_previews_then_puts_a_page_back_as_a_new_save(hist):
    text = restore.restore(hist, "Knowledge/Topics/Rent.md", "#2", preview=True)
    assert "rent 120" in text and "rent 100" in text and rent(hist) == "rent 120\n"
    restore.restore(hist, "Knowledge/Topics/Rent.md", "#2", preview=False)
    assert rent(hist) == "rent 100\n"
    assert log_subjects(hist)[0] == 'Bron: restored "Rent" to #2, asked by Guilherme'
    assert len(log.saves(hist, limit=99)) == 5  # added, nothing removed


def test_restore_finds_a_page_by_its_title_and_brings_back_a_deleted_one(hist):
    turn(hist, "Knowledge/Topics/Fees.md", None, "Delete fees")
    restore.restore(hist, "Fees", "#4", preview=False)
    assert (hist.root / "Knowledge/Topics/Fees.md").read_text() == "fee 2%\n"


def test_restore_of_a_page_that_did_not_exist_then_says_so(hist):
    with pytest.raises(log.HistoryError, match="didn't exist at #2"):
        restore.restore(hist, "Knowledge/Topics/Fees.md", "#2", preview=True)


def test_undo_reverses_exactly_one_turn(hist):
    text = restore.undo(hist, "4", preview=True)
    assert "Knowledge/Topics/Fees.md" in text and (hist.root / "Knowledge/Topics/Fees.md").exists()
    restore.undo(hist, "4", preview=False)
    assert not (hist.root / "Knowledge/Topics/Fees.md").exists() and rent(hist) == "rent 120\n"
    assert log_subjects(hist)[0] == "Bron: undid #4, asked by Guilherme"


def test_undo_refuses_when_a_page_changed_again_later(hist):
    with pytest.raises(log.HistoryError, match="Rent.md"):
        restore.undo(hist, "2", preview=True)


def test_the_first_save_cannot_be_undone(hist):
    with pytest.raises(log.HistoryError, match="first save"):
        restore.undo(hist, "1", preview=True)


def test_restore_a_folder_removes_pages_added_since(hist):
    restore.restore(hist, "Knowledge/Topics", "#3", preview=False)
    assert not (hist.root / "Knowledge/Topics/Fees.md").exists() and rent(hist) == "rent 120\n"


def test_cli_restore_and_undo(hist, monkeypatch, capsys):
    from bron.cli import main
    monkeypatch.setenv("BRON_VAULT", str(hist.root))
    assert main(["history", "restore", "Rent", "--to", "#2", "--preview"]) == 0
    assert "rent 100" in capsys.readouterr().out and rent(hist) == "rent 120\n"
    assert main(["history", "undo", "2"]) == 1
    assert "changed again" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_restore.py -q -p no:cacheprovider`
Expected: FAIL, `ImportError: cannot import name 'restore'`.

- [ ] **Step 3: Write the implementation**

```python
# core/Engine/bron/history/restore.py
"""Putting things back. Every restore and undo is a new save; nothing is ever removed from the history (spec §5)."""
from __future__ import annotations

from pathlib import PurePosixPath

from ..vault import Vault
from . import gitcmd
from .log import HistoryError, resolve
from .save import agent_author, agent_name, commit, timed_lock, user_author

MAX_LINES = 120


def _tracked(vault: Vault, commit_id: str, rel: str) -> list[str]:
    out = gitcmd.run(vault, "ls-tree", "-r", "--name-only", "-z", commit_id, "--", rel).stdout.decode("utf-8")
    return [n for n in out.split("\0") if n]


def find_path(vault: Vault, target: str, commit_id: str) -> str:
    rel = target.strip().strip("/")
    if (vault.root / rel).exists() or _tracked(vault, commit_id, rel):
        return rel
    title = PurePosixPath(rel).name.removesuffix(".md")
    out = gitcmd.run(vault, "ls-tree", "-r", "--name-only", "-z", commit_id, "--", "Knowledge").stdout.decode("utf-8")
    hits = sorted({n for n in out.split("\0") if PurePosixPath(n).name == f"{title}.md"}
                  | {p.relative_to(vault.root).as_posix() for p in vault.knowledge_dir.rglob(f"{title}.md")})
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise HistoryError(f"More than one page is called '{title}': " + ", ".join(hits) + ". Say which one.")
    return rel


def _capped(diff: bytes) -> list[str]:
    lines, more = [], 0
    for line in diff.decode("utf-8", "replace").splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            continue
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            if len(lines) < MAX_LINES:
                lines.append(f"  {line[0]} {line[1:]}")
            else:
                more += 1
    if more:
        lines.append(f"…and {more} more changed lines.")
    return lines


def _who(vault: Vault) -> str:
    return user_author(vault).name


def restore(vault: Vault, target: str, to: str, *, preview: bool) -> str:
    s = resolve(vault, to)
    rel = find_path(vault, target, s.commit)
    if not _tracked(vault, s.commit, rel):
        raise HistoryError(f"'{rel}' didn't exist at #{s.number}.")
    diff = gitcmd.run(vault, "diff", "-R", "--no-color", "--unified=1", s.commit, "--", rel).stdout
    if not diff:
        return f"'{rel}' is already as it was at #{s.number}; nothing to put back."
    name = PurePosixPath(rel).name.removesuffix(".md")
    header = [f'Put "{name}" back as it was at #{s.number} ({s.subject}):']
    if preview:
        return "\n".join(header + _capped(diff))
    with timed_lock(vault, 5) as got:
        if not got:
            raise HistoryError("Another save is running; try again in a moment.")
        gitcmd.run(vault, "restore", f"--source={s.commit}", "--staged", "--worktree", "--", rel)
        agent = agent_name(vault)
        commit(vault, author=agent_author(agent), subject=f'{agent}: restored "{name}" to #{s.number}, asked by {_who(vault)}',
               trailers={"Bron-Agent": agent.lower(), "Bron-Restored-From": f"#{s.number}"})
    return f'Restored "{name}" to #{s.number}.'


def undo(vault: Vault, ref: str, *, preview: bool) -> str:
    s = resolve(vault, ref)
    if s.number == 1:
        raise HistoryError("The first save can't be undone; restore single pages instead.")
    files = s.files
    later = gitcmd.run(vault, "diff", "--name-only", "-z", s.commit, "--", *files).stdout.decode("utf-8")
    again = [n for n in later.split("\0") if n]
    if again:
        raise HistoryError(f"These pages changed again after #{s.number}, so undoing it could lose that work: "
                           + ", ".join(again) + ". Restore them one by one instead, or leave them.")
    diff = gitcmd.run(vault, "diff", "--no-color", "--unified=1", s.commit, f"{s.commit}^").stdout
    header = [f"Undo #{s.number} ({s.subject}) puts back {len(files)} page" + ("" if len(files) == 1 else "s") + ":",
              *[f"- {f}" for f in files]]
    if preview:
        return "\n".join(header + _capped(diff))
    with timed_lock(vault, 5) as got:
        if not got:
            raise HistoryError("Another save is running; try again in a moment.")
        done = gitcmd.run(vault, "revert", "--no-commit", "--no-edit", s.commit, check=False)
        if done.returncode != 0:
            gitcmd.run(vault, "revert", "--abort", check=False)
            raise HistoryError(f"#{s.number} couldn't be undone cleanly; nothing was changed.")
        agent = agent_name(vault)
        commit(vault, author=agent_author(agent), subject=f"{agent}: undid #{s.number}, asked by {_who(vault)}",
               trailers={"Bron-Agent": agent.lower(), "Bron-Undid": f"#{s.number}"})
    return f"Undid #{s.number}."
```

Use `slug(agent)` from `..model` instead of `agent.lower()` for `Bron-Agent` (consistency with Task 3). Also, `git revert --no-commit` leaves the revert state open, and the `commit()` call finishes it. If a sequencer state lingers (`.git/sequencer`), call `gitcmd.run(vault, "revert", "--quit", check=False)` after committing.

In `history/cli.py`, add:

```python
    restorer = commands.add_parser("restore", help="put a page or folder back as it was at a save or time")
    restorer.add_argument("target")
    restorer.add_argument("--to", required=True)
    restorer.add_argument("--preview", action="store_true")
    undoer = commands.add_parser("undo", help="reverse exactly one save")
    undoer.add_argument("ref")
    undoer.add_argument("--preview", action="store_true")
```

And in `handle`, inside the `try`:

```python
        if args.history_command == "restore":
            from .restore import restore
            print(restore(vault, args.target, args.to, preview=args.preview))
            return 0
        if args.history_command == "undo":
            from .restore import undo
            print(undo(vault, args.ref, preview=args.preview))
            return 0
```

- [ ] **Step 4: Run them to see them pass**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_restore.py tests/test_history_log.py -q -p no:cacheprovider`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/history/restore.py core/Engine/bron/history/cli.py tests/test_history_restore.py
git commit -m "History: restore a page or folder and undo one turn, previewed first, as new saves"
```

---

### Task 7: The off-Mac copy, notices and recover (`backup.py`)

**Files:**
- Create: `core/Engine/bron/history/backup.py`
- Modify: `core/Engine/bron/history/cli.py`
- Test: `tests/test_history_backup.py`

**Interfaces:**
- Consumes: `repo.read_settings`, `repo.state`, `repo.apply_config`, `gitcmd.run`, `setup.run`, `setup.Change`, `fmedit.edit_meta`
- Produces:
  - `kind(destination: str) -> str` (`"repo"` or `"folder"`)
  - `set_destination(vault, destination: str | None, *, preview: bool) -> list[str]` (via `setup.run`; `None` removes it)
  - `run_backup(vault, *, min_interval: float = 0.0, now: float | None = None) -> str` (one of `"none"`, `"up-to-date"`, `"waiting"`, `"done"`, `"failed"`)
  - `NOTICE = "history-notice.json"`, `record_notice(vault, line)`, `take_notice(vault) -> str`
  - `recover(source: str, target: Path) -> str`, raising `HistoryError`
  - `status_text(vault) -> str`
  - `INTERVAL = 1800`
- CLI: `bron history backup --to <dest> [--preview]`, `--off [--preview]` and `--run`; `bron history status`; `bron history recover --from <src> <folder>`. The `history save --turn` handler calls `run_backup(vault, min_interval=INTERVAL)` after saving.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_backup.py
"""The optional off-Mac copy: a bundle file in a folder, or a push to a repository; notices; recover."""
import subprocess

import pytest

from bron.history import backup, repo, save
from bron.history.log import HistoryError
from histkit import hvault, log_subjects


def test_kind_of_destination():
    assert backup.kind("git@github.com:me/vault.git") == "repo"
    assert backup.kind("https://github.com/me/vault.git") == "repo"
    assert backup.kind("/Users/me/Library/CloudStorage/GoogleDrive-me/My Drive/Backups") == "folder"


def test_set_destination_previews_then_writes_settings(vault, tmp_path):
    hvault(vault)
    folder = tmp_path / "Drive Backups"
    folder.mkdir()
    lines = backup.set_destination(vault, str(folder), preview=True)
    assert any(str(folder) in l for l in lines) and repo.read_settings(vault).backup == ""
    backup.set_destination(vault, str(folder), preview=False)
    assert repo.read_settings(vault).backup == str(folder)
    backup.set_destination(vault, None, preview=False)
    assert repo.read_settings(vault).backup == ""


def test_a_missing_folder_is_refused_when_setting_it(vault, tmp_path):
    hvault(vault)
    from bron.setup import SetupError
    with pytest.raises(SetupError, match="doesn't exist"):
        backup.set_destination(vault, str(tmp_path / "nope"), preview=True)


def test_backup_to_a_folder_writes_one_verified_bundle_atomically(vault, tmp_path):
    hvault(vault)
    folder = tmp_path / "Drive"
    folder.mkdir()
    backup.set_destination(vault, str(folder), preview=False)
    assert backup.run_backup(vault) == "done"
    files = sorted(p.name for p in folder.iterdir())
    assert files == [f"{vault.root.name}.history.bundle"]
    assert subprocess.run(["git", "bundle", "verify", str(folder / files[0])], capture_output=True).returncode == 0
    assert backup.run_backup(vault) == "up-to-date"


def test_backup_to_a_repository_pushes_main(vault, tmp_path):
    hvault(vault)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    backup.set_destination(vault, str(remote) + "", preview=False)  # a local path ending in .git counts as a repo
    assert backup.kind(str(remote)) == "repo"
    assert backup.run_backup(vault) == "done"
    log = subprocess.run(["git", f"--git-dir={remote}", "log", "--format=%s", "main"], capture_output=True, text=True).stdout
    assert "Bron: vault created" in log


def test_the_time_gate_waits_between_backups(vault, tmp_path):
    hvault(vault)
    folder = tmp_path / "Drive"
    folder.mkdir()
    backup.set_destination(vault, str(folder), preview=False)
    assert backup.run_backup(vault, min_interval=1800, now=1000.0) == "done"
    (vault.knowledge_dir / "Topics" / "New.md").write_text("x\n")
    save.on_prompt(vault, cli="claude", session_id="s", prompt="hi")
    assert backup.run_backup(vault, min_interval=1800, now=1100.0) == "waiting"
    assert backup.run_backup(vault, min_interval=1800, now=3000.0) == "done"


def test_a_failing_backup_is_noticed_once(vault, tmp_path):
    hvault(vault)
    folder = tmp_path / "Drive"
    folder.mkdir()
    backup.set_destination(vault, str(folder), preview=False)
    folder.rmdir()
    assert backup.run_backup(vault) == "failed"
    assert backup.run_backup(vault) == "failed"
    notice = backup.take_notice(vault)
    assert notice.count("History backup") == 1 and "wasn't found" in notice
    assert backup.take_notice(vault) == ""


def test_recover_rebuilds_a_vault_folder_from_a_bundle(vault, tmp_path):
    hvault(vault)
    folder = tmp_path / "Drive"
    folder.mkdir()
    backup.set_destination(vault, str(folder), preview=False)
    backup.run_backup(vault)
    target = tmp_path / "Recovered Vault"
    text = backup.recover(str(folder / f"{vault.root.name}.history.bundle"), target)
    assert (target / "System" / "Settings.md").is_file() and (target / ".git" / repo.MARKER).is_file()
    assert "install" in text.lower()
    with pytest.raises(HistoryError, match="isn't empty"):
        backup.recover(str(folder / f"{vault.root.name}.history.bundle"), target)
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_backup.py -q -p no:cacheprovider`
Expected: FAIL, `ImportError: cannot import name 'backup'`.

- [ ] **Step 3: Write the implementation**

```python
# core/Engine/bron/history/backup.py
"""The optional off-Mac copy of the history (spec §6): one bundle file in a folder (Drive), or a push to a repository.
Always run detached; a failure is recorded, noticed once in the briefing, and reported by the health check."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from ..fmedit import edit_meta
from ..setup import Change, SetupError, run
from ..statefile import read_json, update_json
from ..vault import Vault
from . import gitcmd, repo
from .log import HistoryError

INTERVAL = 1800
NOTICE = "history-notice.json"
SSH = "ssh -o BatchMode=yes -o ConnectTimeout=10"
REPO_FORM = re.compile(r"^(git@|ssh://|https?://)|\.git/?$")
INSTALL = 'curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash -s -- "{folder}"'


def kind(destination: str) -> str:
    return "repo" if REPO_FORM.search(destination.strip()) else "folder"


def _state_path(vault: Vault) -> Path:
    return vault.state_dir / gitcmd.STATE


def record_notice(vault: Vault, line: str) -> None:
    def add(data: dict) -> None:
        lines = data.setdefault("lines", [])
        if line not in lines:
            lines.append(line)

    update_json(vault.state_dir / NOTICE, {}, add)


def take_notice(vault: Vault) -> str:
    path = vault.state_dir / NOTICE
    if not path.is_file():
        return ""
    found: list[str] = []

    def take(data: dict) -> None:
        found.extend(data.pop("lines", []) or [])

    update_json(path, {}, take)
    path.unlink(missing_ok=True)
    return "\n".join(found)


def set_destination(vault: Vault, destination: str | None, *, preview: bool) -> list[str]:
    dest = (destination or "").strip()
    if dest and kind(dest) == "folder":
        dest = str(Path(dest).expanduser())
        if not Path(dest).is_dir():
            raise SetupError(f"The folder {dest} doesn't exist; pick one that does (Google Drive for desktop shows Drive folders in Finder).")

    def build(cfg) -> Change:
        text = cfg.vault.settings_file.read_text(encoding="utf-8")
        current = repo.read_settings(cfg.vault)
        if current.backup == dest:
            raise SetupError("Nothing to change: that's already the backup." if dest else "There's no backup to remove.")
        change = Change(done="Saved the backup setting." if dest else "Removed the backup.")
        change.writes[cfg.settings.path.relative_to(cfg.vault.root).as_posix()] = edit_meta(
            text, {"history": {"enabled": current.enabled, "backup": dest}})
        where = "a private repository" if dest and kind(dest) == "repo" else "one file in that folder"
        change.summary = ([f"Back up the vault's history to {dest}, as {where}, after each session and at most every 30 minutes."]
                          if dest else ["Stop backing up the vault's history off this Mac (the history on this Mac stays)."])
        return change

    return run(vault, build, preview_only=preview)


def _head(vault: Vault) -> str:
    return gitcmd.run(vault, "rev-parse", "main", check=False).stdout.decode().strip()


def _to_folder(vault: Vault, folder: Path) -> None:
    if not folder.is_dir():
        raise HistoryError(f"the folder {folder} wasn't found")
    final = folder / f"{vault.root.name}.history.bundle"
    temp = folder / f".{final.name}.tmp"
    gitcmd.run(vault, "bundle", "create", "-q", str(temp), "--all", timeout=600)
    gitcmd.run(vault, "bundle", "verify", "-q", str(temp), timeout=600)
    os.replace(temp, final)


def _to_repo(vault: Vault, destination: str) -> None:
    gitcmd.run(vault, "push", "--quiet", destination, "main:main", env={"GIT_SSH_COMMAND": SSH}, timeout=300)


def run_backup(vault: Vault, *, min_interval: float = 0.0, now: float | None = None) -> str:
    settings = repo.read_settings(vault)
    if not settings.backup or repo.state(vault) != "ready":
        return "none"
    now = time.time() if now is None else now
    state = read_json(_state_path(vault), {})
    head = _head(vault)
    if head and head == state.get("backup_head") and settings.backup == state.get("backup_to"):
        return "up-to-date"
    if min_interval and now - float(state.get("backup_attempt") or 0) < min_interval:
        return "waiting"
    error = ""
    try:
        if kind(settings.backup) == "repo":
            _to_repo(vault, settings.backup)
        else:
            _to_folder(vault, Path(settings.backup).expanduser())
    except (HistoryError, gitcmd.GitError, gitcmd.GitUnavailable, OSError, subprocess.TimeoutExpired) as exc:
        error = str(exc) or exc.__class__.__name__
    first_failure = bool(error) and not state.get("backup_error")

    def put(data: dict) -> None:
        data["backup_attempt"] = now
        data["backup_to"] = settings.backup
        if error:
            data["backup_error"] = error
        else:
            data.update(backup_head=head, backup_success=now, backup_error="")

    update_json(_state_path(vault), {}, put)
    if first_failure:
        where = "Google Drive" if "GoogleDrive" in settings.backup or "Google Drive" in settings.backup else settings.backup
        record_notice(vault, f"History backup to {where} failed: {error}.")
    return "failed" if error else "done"


def status_text(vault: Vault) -> str:
    settings = repo.read_settings(vault)
    found = repo.state(vault)
    if found != "ready":
        return {"off": "History: off.", "missing": "History: not started yet.",
                "foreign": "History: this vault has its own git repository, so Bron keeps none."}[found]
    count = len(gitcmd.run(vault, "rev-list", "main", check=False).stdout.split())
    state = read_json(_state_path(vault), {})
    lines = [f"History: on, {count} saves."]
    if settings.backup:
        when = state.get("backup_success")
        lines.append(f"Backup: {settings.backup}; last done "
                     + (time.strftime("%b %-d %H:%M", time.localtime(when)) if when else "never") + ".")
        if state.get("backup_error"):
            lines.append(f"Last backup problem: {state['backup_error']}.")
    else:
        lines.append("Backup: none (history stays on this Mac).")
    return "\n".join(lines)


def recover(source: str, target: Path) -> str:
    target = Path(target).expanduser()
    if target.exists() and any(target.iterdir()):
        raise HistoryError(f"{target} isn't empty; pick a new folder.")
    done = subprocess.run(["git", "clone", "-q", "--branch", "main", source, str(target)], capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": SSH}, timeout=900)
    if done.returncode != 0:
        raise HistoryError(f"The backup couldn't be read: {done.stderr.strip() or done.stdout.strip()}")
    restored = Vault(target)
    gitcmd.run(restored, "remote", "remove", "origin", check=False)
    repo.apply_config(restored)
    return (f"Rebuilt the vault's files in {target}. Now install Bron's machine part there (it keeps every file):\n"
            + INSTALL.format(folder=target))
```

Note: `recover` runs before `target` is a vault, so it uses the git found by `gitcmd.find_git()` rather than `"git"`. Replace `["git", "clone", …]` with `[gitcmd.find_git() or "git", "clone", …]`, and raise `HistoryError("git isn't available…")` if it's `None`. `Vault(target)` works on a plain folder (no marker check in the constructor). `git_path` then writes `.bron/state/history.json` inside the target, which is ignored. Check that `Vault(path)` doesn't require the marker; `conftest.py` constructs `Vault(root)` directly.

In `history/cli.py` add:

```python
    backer = commands.add_parser("backup", help="the optional off-Mac copy of the history")
    where = backer.add_mutually_exclusive_group(required=True)
    where.add_argument("--to", default=None)
    where.add_argument("--off", action="store_true")
    where.add_argument("--run", action="store_true", help=argparse.SUPPRESS)
    backer.add_argument("--preview", action="store_true")
    commands.add_parser("status", help="history on or off, saves, and the backup")
    recoverer = commands.add_parser("recover", help="rebuild a vault folder from a backup")
    recoverer.add_argument("--from", dest="source", required=True)
    recoverer.add_argument("folder")
```

In `handle`:
- `recover` is allowed even when `state != "ready"`, so handle it before the state check.
- In the `save` branch, add `backup.run_backup(vault, min_interval=backup.INTERVAL)` after `save_turn`.
- Inside the `try`:

```python
        if args.history_command == "status":
            from .backup import status_text
            print(status_text(vault))
            return 0
        if args.history_command == "backup":
            from . import backup
            if args.run:
                backup.run_backup(vault)
                return 0
            print("\n".join(backup.set_destination(vault, None if args.off else args.to, preview=args.preview)))
            return 0
```

And before the state check:

```python
    if args.history_command == "recover":
        from .backup import recover
        try:
            print(recover(args.source, Path(args.folder)))
            return 0
        except HistoryError as exc:
            print(exc)
            return 1
```

Catch `SetupError` in the backup branch and print it (return 1), the way `setup_cli.py` does.

- [ ] **Step 4: Run them to see them pass**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_backup.py tests/test_history_hooks.py -q -p no:cacheprovider`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/history/backup.py core/Engine/bron/history/cli.py tests/test_history_backup.py
git commit -m "History: optional off-Mac copy (Drive bundle or repository), noticed once on failure, and recover"
```

---

### Task 8: Settings, install, update, migration, briefing and health check

**Files:**
- Modify:
  - `core/Engine/bron/model.py` (`Settings.history_enabled: bool = True`, `history_backup: str = ""`)
  - `core/Engine/bron/loader.py` (parse the `history` block with warnings, like `knowledge`)
  - `template/System/Settings.md`
  - `core/Engine/bron/install.py` (`install_vault`)
  - `core/Engine/bron/update.py` (`_finish`)
  - `core/Engine/bron/migrations/__init__.py`
  - `core/Engine/bron/briefing.py`
  - `core/Engine/bron/check.py`
- Create: `core/Engine/bron/migrations/vault_history.py`
- Test: `tests/test_history_setup.py`

**Interfaces:**
- Consumes: `repo.ensure`, `repo.state`, `backup.take_notice`, `backup.record_notice`, `gitcmd.git_path`
- Produces:
  - migration id `"vault-history"`, version `"0.9.0"`
  - in `check.py`: `_history(cfg) -> list[Issue]` with codes `history.unavailable`, `history.foreign`, `history.failing`, `history.backup-failing` and `history.large`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_setup.py
"""History switched on by install, update and migration; the briefing note; the health check; Settings."""
from bron.briefing import build_briefing
from bron.check import run_checks
from bron.history import backup, repo
from bron.loader import load
from histkit import hvault, log_subjects


def test_settings_template_has_history_on_and_explained(vault):
    s = load(vault).settings
    assert s.history_enabled is True and s.history_backup == ""
    text = vault.settings_file.read_text()
    assert "history:" in text and "`history`" in text


def test_the_migration_adds_the_block_and_starts_the_history(vault):
    from bron.migrations import MIGRATIONS
    from bron.setup import apply as apply_change
    text = vault.settings_file.read_text()
    vault.settings_file.write_text(text.replace("history:\n  enabled: true\n  backup: \"\"\n", ""))
    [mig] = [m for m in MIGRATIONS if m.id == "vault-history"]
    assert mig.version == "0.9.0"
    apply_change(vault, mig.build(load(vault)))
    assert "history:" in vault.settings_file.read_text()


def test_finishing_an_update_starts_history_and_notes_it_once(vault, monkeypatch):
    from bron import update
    monkeypatch.setattr("bron.cli._sync", lambda v, dry_run=False: 0)
    monkeypatch.setattr("bron.cli._check", lambda v: 0)
    monkeypatch.setattr("bron.obsidian.refresh_bundle", lambda root, core: [])
    update._finish(vault, "0.8.2", None)
    assert repo.state(vault) == "ready"
    assert log_subjects(vault)[0] == f"Bron: history started ({vault.version()})"
    assert "change history" in build_briefing(vault, cli="claude")
    assert "change history" not in build_briefing(vault, cli="claude")


def test_a_later_update_is_one_labelled_save(vault, monkeypatch):
    from bron import update
    hvault(vault)
    monkeypatch.setattr("bron.cli._sync", lambda v, dry_run=False: 0)
    monkeypatch.setattr("bron.cli._check", lambda v: 0)
    monkeypatch.setattr("bron.obsidian.refresh_bundle", lambda root, core: [])
    (vault.core / "Manual" / "new.md").write_text("x\n")
    update._finish(vault, "0.9.0", None)
    assert log_subjects(vault)[0] == f"Bron: now on version {vault.version()} (was 0.9.0)"


def test_the_health_check_reports_history_problems(vault, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", str(vault.root)], check=True)
    codes = [i.code for i in run_checks(load(vault), include_environment=False)]
    assert "history.foreign" in codes


def test_the_health_check_reports_a_failing_backup(vault, tmp_path):
    hvault(vault)
    folder = tmp_path / "Drive"
    folder.mkdir()
    backup.set_destination(vault, str(folder), preview=False)
    folder.rmdir()
    backup.run_backup(vault)
    codes = [i.code for i in run_checks(load(vault), include_environment=False)]
    assert "history.backup-failing" in codes


def test_the_briefing_shows_a_backup_failure_once(vault, tmp_path):
    hvault(vault)
    backup.record_notice(vault, "History backup to Google Drive failed: the folder wasn't found.")
    assert "History backup to Google Drive failed" in build_briefing(vault, cli="claude")
    assert "History backup" not in build_briefing(vault, cli="claude")
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_setup.py -q -p no:cacheprovider`
Expected: FAIL (no `history_enabled`, no migration, nothing in `_finish`).

- [ ] **Step 3: Write the implementation**

**`template/System/Settings.md`:** add to the frontmatter after `knowledge:`:

```yaml
history:
  enabled: true
  backup: ""
```

And to the body list, after the `knowledge` line:

```markdown
- `history`: Bron keeps a change history of this vault on this Mac: who changed what, in which conversation, and a way to put things back ("what changed today?", "undo that"). Set `enabled: false` to stop it. `backup` is empty unless you ask Bron to keep a copy off this Mac (a Google Drive folder or a private GitHub repository).
```

**`model.py`:** add `history_enabled: bool = True` and `history_backup: str = ""` to `Settings`.

**`loader.py`:** after the knowledge block in the settings parser:

```python
    history = doc.meta.get("history") or {}
    if not isinstance(history, dict):
        f.problem("field.type", "'history' should hold enabled and backup", level="warning")
        history = {}
    enabled = history.get("enabled", True)
    if isinstance(enabled, bool):
        settings.history_enabled = enabled
    else:
        f.problem("field.type", "'history.enabled' should be true or false", level="warning")
    backup_to = history.get("backup") or ""
    if isinstance(backup_to, str):
        settings.history_backup = backup_to.strip()
    else:
        f.problem("field.type", "'history.backup' should be a folder or a repository address", level="warning")
```

**`migrations/vault_history.py`:**

```python
"""0.9.0: Bron keeps a change history of the vault. Adds the history block to System/Settings.md; the history itself
is started by the update's finishing step (repo.ensure), since a migration only writes files."""
from __future__ import annotations

from .. import frontmatter as fm
from ..fmedit import EditError, edit_meta
from ..loader import Config
from ..setup import Change

SUMMARY = "Bron keeps a change history of your vault on this Mac: who changed what, and a way to put things back."


def build(cfg: Config) -> Change:
    path = cfg.vault.settings_file
    change = Change(summary=[SUMMARY], done="History settings added.")
    try:
        text = path.read_text(encoding="utf-8")
        if "history" not in fm.parse(text).meta:
            change.writes["System/Settings.md"] = edit_meta(text, {"history": {"enabled": True, "backup": ""}})
    except (OSError, UnicodeDecodeError, fm.FrontmatterError, EditError):
        pass  # an unusual settings file keeps working: history defaults to on
    return change
```

Check how `knowledge_wiki.build` handles "nothing to write" (the end of that function) and mirror it, in case `setup.run` refuses an empty Change.

**`migrations/__init__.py`:**

```python
def _vault_history(cfg: Config) -> Change:
    from .vault_history import build

    return build(cfg)
```

Append to `MIGRATIONS`:

```python
    Migration(id="vault-history", version="0.9.0",
              summary="Bron keeps a change history of your vault on this Mac: who changed what, and a way to put things back.",
              build=_vault_history),
```

**`update.py` `_finish`**, after `_sync(...)` succeeds and before `_check(vault)`:

```python
    _history_after_update(vault, previous)
```

Add the helper:

```python
STARTED_NOTE = ("Bron now keeps a change history of this vault, on this Mac only. "
                "Say \"what changed today?\" or \"undo that\". Tell the user in one line.")


def _history_after_update(vault: Vault, previous: str) -> None:
    """Start the history (first time) or save the update as one labelled change; never fails the update."""
    try:
        from .history import backup, repo

        current = vault.version()
        result = repo.ensure(vault, f"Bron: history started ({current})" if repo.state(vault) == "missing"
                             else f"Bron: now on version {current} (was {previous})")
        if result == "created":
            backup.record_notice(vault, STARTED_NOTE)
    except Exception as exc:  # noqa: BLE001
        print(f"History: {exc.__class__.__name__}: {exc}")
```

Note: an update's undo runs `after_update` → `_finish` too, so going back is also one save ("now on version 0.8.2 (was 0.9.0)"). The spec's "Bron: updated to <version>" becomes "Bron: now on version <v> (was <previous>)", which covers both directions. This is a small, deliberate wording change; mention it in the CHANGELOG.

**`install.py` `install_vault`**, after `bron(["check"])` inside the `try` (where `BRON_VAULT` is set):

```python
        from .history import repo
        from .vault import Vault
        try:
            repo.ensure(Vault(vault_root), "Bron: vault created" if previous is None else f"Bron: installed {Vault(vault_root).version()}")
        except Exception as exc:  # noqa: BLE001 - history never fails an install
            print(f"History: {exc.__class__.__name__}: {exc}")
```

**`briefing.py`**, next to the approvals notice (`take_notice`), inside `if not ticket_run:`:

```python
        try:
            from .history.backup import take_notice as history_notice

            history = history_notice(vault)
        except Exception:  # noqa: BLE001
            history = ""
        if history:
            lines += ["", history]
```

**`check.py`:** add `_history(cfg)` to the list `run_checks` runs (follow how `_locks` is added):

```python
def _history(cfg: Config) -> list[Issue]:
    from .history import gitcmd, repo
    from .statefile import read_json

    vault = cfg.vault
    found = repo.state(vault)
    if found == "off":
        return []
    if found == "foreign":
        return [Issue("warning", "history.foreign", "This vault already has its own git repository, so Bron keeps no change history of its own. Remove that repository or keep using it yourself.")]
    if not gitcmd.git_path(vault, refresh=True):
        return [Issue("warning", "history.unavailable", "Bron can't keep a change history because git isn't installed. Install Apple's command line tools with `xcode-select --install`.")]
    out = []
    state = read_json(vault.state_dir / gitcmd.STATE, {})
    if state.get("backup_error") and repo.read_settings(vault).backup:
        out.append(Issue("warning", "history.backup-failing", f"The history backup isn't working: {state['backup_error']}."))
    log = vault.bron_dir / "logs" / "history.log"
    if found == "ready" and log.is_file():
        week_ago = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7 * 86400))
        recent = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l[:19] >= week_ago]
        if len(recent) >= 5:
            out.append(Issue("warning", "history.failing", f"Saving the change history failed {len(recent)} times this week; see .bron/logs/history.log."))
    git_dir = vault.root / ".git"
    if git_dir.is_dir():
        size = sum(p.stat().st_size for p in git_dir.rglob("*") if p.is_file())
        if size > 1024 ** 3:
            out.append(Issue("warning", "history.large", f"The change history is {size / 1024 ** 3:.1f} GB; large files in Knowledge/Files/ make it grow."))
        try:
            gitcmd.run(vault, "gc", "--auto", "--quiet", check=False, timeout=120)
        except Exception:  # noqa: BLE001
            pass
    return out
```

`check.py` needs `import time` if it doesn't have it. `history.log` lines start with an ISO timestamp (Task 4's `_history_log`), which is what the 7-day count compares. Detached `bron history` processes also write their stdout and stderr there, so keep `bron history save` silent on success.

Keep the health check fast: `_history` runs once a day at session start. The `rglob` size sum is fine for vault-sized repositories.

- [ ] **Step 4: Run them to see them pass, then the affected suites**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_setup.py tests/test_setup.py tests/test_check.py tests/test_migrations.py tests/test_update.py tests/test_install.py tests/test_loader.py tests/test_prompts.py -q -p no:cacheprovider`
Expected: all passed.
- If a migration test counts the registered migrations, update its expected list.
- If an install or update test asserts the exact printed output, add the history line expectation, or keep it silent on success (the code above prints only on errors).

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/model.py core/Engine/bron/loader.py template/System/Settings.md core/Engine/bron/install.py core/Engine/bron/update.py core/Engine/bron/migrations/ core/Engine/bron/briefing.py core/Engine/bron/check.py tests/test_history_setup.py
git commit -m "History: on in Settings, started by install and update, noted in the briefing, checked daily"
```

---

### Task 9: Instructions: the skill, the manual, AGENTS.md and the changelog

**Files:**
- Create: `core/Skills/history/SKILL.md`, `core/Manual/history.md`
- Modify: `core/Manual/index.md`, `core/Templates/AGENTS.md.tmpl`, `CHANGELOG.md`
- Test: `tests/test_history_content.py`

**Interfaces:**
- Consumes: the CLI from Tasks 4–7 (every documented command must parse; `tests/test_handoff_content.py::test_quoted_commands_parse` checks core skills)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_history_content.py
"""The history skill, manual page, AGENTS.md line and changelog."""
from bron import frontmatter as fm
from bron.agents_md import render_agents_md
from bron.loader import load


def test_the_history_skill_is_published_with_previews(vault):
    assert "history" in load(vault).skills
    path = vault.core_skills / "history" / "SKILL.md"
    meta = fm.read(path).meta
    assert "undo" in meta["description"] and "what changed" in meta["description"]
    text = path.read_text()
    for must in ("bron history", "history show", "history restore", "--preview", "wait for a yes",
                 "history undo", "changed again", "history backup --to", "history recover"):
        assert must in text, must


def test_agents_md_points_to_the_skill_and_stays_small(vault):
    text = render_agents_md(load(vault))
    assert "Change history and undo: the history skill." in text
    assert len(text.encode()) < 8 * 1024


def test_the_manual_has_a_history_page(vault):
    assert "](history.md)" in (vault.core_manual / "index.md").read_text()
    page = (vault.core_manual / "history.md").read_text()
    for must in ("history:", "enabled: false", "backup", "Knowledge/Files", "never rewritten"):
        assert must in page, must


def test_the_changelog_describes_0_9_0():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text()
    assert "## 0.9.0" in text and "history" in text.split("## 0.9.0", 1)[1].split("## 0.8.2", 1)[0].lower()
```

- [ ] **Step 2: Run them to see them fail**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_content.py -q -p no:cacheprovider`
Expected: FAIL (no skill, no line, no page).

- [ ] **Step 3: Write the content**

`core/Skills/history/SKILL.md`:

```markdown
---
name: history
description: The vault's change history. Use when the user asks what changed (today, this week, on a page, by an agent or ticket), wants to see a change, wants a page put back as it was, says "undo that", or wants a backup of the history off this Mac or to recover a vault from one.
---

# Change history

Bron saves the vault at each turn: the user's own edits when a message arrives, and each agent's changes when it finishes, saying who made them and why. Saves are numbered (#1 is the first). Nothing is ever removed from the history: putting something back is a new save.

## Looking back

- What changed: `.bron/bin/bron history [<page or folder>] [--since '<YYYY-MM-DD or YYYY-MM-DD HH:MM>'] [--agent '<name or you>'] [--ticket <id>] [--limit N]`. Turn "today", "this week" or "this morning" into a date or time yourself.
- What one save changed: `.bron/bin/bron history show <n>`.
- Answer in plain words: who, when, which pages, what changed. Don't paste long diffs.

## Putting back

Always preview first, show the user, and wait for a yes before applying.

- One page or folder: `.bron/bin/bron history restore '<page title or path>' --to <n or time> --preview`, then the same command without `--preview` after a yes.
- A whole turn: `.bron/bin/bron history undo <n> --preview`, then without `--preview` after a yes.
- If undo says pages changed again after that save, don't force anything: offer to restore those pages one by one (preview each), or to leave them.
- Restoring a file in `System/` is a setup change: show the change and get a yes, as for any change there.

## Backup off this Mac

Off unless the user asks. Ask where: a folder (Google Drive for desktop shows Drive folders in Finder) or a private repository address (for example `git@github.com:<user>/<repo>.git`, which needs their GitHub key set up).

- Set: `.bron/bin/bron history backup --to '<folder or repository>' --preview`, show it, wait for a yes, then run it without `--preview`. This is the user's one approval for sending the history there.
- Remove: `.bron/bin/bron history backup --off --preview`, show it, wait for a yes, then apply.
- Check: `.bron/bin/bron history status`.
- On a new Mac: `.bron/bin/bron history recover --from '<bundle file or repository>' '<new vault folder>'`, then run the install command it prints.
```

`core/Manual/history.md`:

```markdown
# Change history

Bron keeps a private history of the vault on this Mac: every save says who made the change (you, or a named agent), in which conversation or ticket, and why. It's how you see what changed and put things back.

## What is saved, and when

- When you send a message, anything changed since the last save is saved as yours (edits you made in Obsidian).
- When an agent finishes its reply, its changes are saved under its name, with the start of your request.
- Background ticket runs save under the agent's name and the ticket.
- Kept: Knowledge (including Knowledge/Files, copies of Mac files that exist nowhere else), Projects, Routines, Tickets, System and Obsidian settings.
- Left out: `.bron/` (machine data), the files Bron rebuilds (`.claude/`, `.codex/`, `.agents/`, `AGENTS.md`, `CLAUDE.md`), Obsidian's window layout and `.trash/`. Bron keeps its part of `.gitignore` between two marker lines; your own lines outside them are kept.

## Looking back and putting back

Ask in plain words: "what changed today?", "show me #142", "put the Fund II page back as it was this morning", "undo that". Bron previews every restore or undo and applies it after your yes. The history is never rewritten: a restore or undo is a new save, so the record stays complete.

## Settings

In `System/Settings.md`:

    history:
      enabled: true
      backup: ""

- `enabled: false` stops new saves (the history so far stays).
- `backup`: empty keeps the history on this Mac only. Ask Bron to back it up to a Google Drive folder (one file, refreshed after each session and at most every 30 minutes) or a private GitHub repository.

## Good to know

- The history lives in the vault's `.git` folder. Bron sets it up with its own settings and never changes your Mac's git setup.
- A vault that already has its own git repository is left alone; Bron keeps no history there.
- The health check warns when git is missing, saves keep failing, the backup isn't working, or the history passes 1 GB.
```

`core/Manual/index.md`: add a row after `knowledge.md`:

```markdown
| [history.md](history.md) | The change history: what is saved and when, looking back, putting things back, and the optional backup |
```

`core/Templates/AGENTS.md.tmpl`: in `## How Bron works`, before the line about the manual, add:

```markdown
Change history and undo: the history skill.
```

`CHANGELOG.md`: add at the top:

```markdown
## 0.9.0
- Bron keeps a change history of your vault, on this Mac only: each save says who made the change (you, or a named agent), in which conversation or ticket, and why. It adds about 15 ms to a message, and nothing to an agent's reply.
- Ask "what changed today?", "show me #142", "put the Fund II page back as it was this morning" or "undo that". Every restore and undo is previewed first and saved as a new change; the history is never rewritten.
- Optional backup off this Mac: one file in a Google Drive folder, or a private GitHub repository. A vault can be rebuilt from it on a new Mac.
- An update or going back to an earlier version is one labelled save ("Bron: now on version 0.9.0 (was 0.8.2)").
- Turn it off with `history: enabled: false` in System/Settings.md. A vault that already has its own git repository is left alone.
```

- [ ] **Step 4: Run them to see them pass, then the content suites**

Run: `core/Engine/.venv/bin/python -m pytest tests/test_history_content.py tests/test_handoff_content.py tests/test_setup_content.py tests/test_work_setup.py tests/test_prompts.py -q -p no:cacheprovider`
Expected: all passed. `test_quoted_commands_parse` parses every `.bron/bin/bron …` in the skill, so add placeholders it doesn't know to its `placeholders` map: `<n>` → `3`, `<page title or path>` → `Rent`, `<n or time>` → `#2`, `<folder or repository>` → `/tmp/x`, `<bundle file or repository>` → `/tmp/x.bundle`, `<new vault folder>` → `/tmp/v`, `<name or you>` → `you`, `<YYYY-MM-DD or YYYY-MM-DD HH:MM>` → `2026-10-05`.

- [ ] **Step 5: Commit**

```bash
git add core/Skills/history core/Manual/history.md core/Manual/index.md core/Templates/AGENTS.md.tmpl CHANGELOG.md tests/test_history_content.py tests/test_handoff_content.py
git commit -m "History: the history skill, manual page, AGENTS.md line and 0.9.0 notes"
```

---

### Task 10: Speed test, live test, full suite

**Files:**
- Create: `tests/test_history_speed.py`, `tests/live/test_history.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the speed test**

```python
# tests/test_history_speed.py
"""Speed budgets (spec §9) on a 300-file vault. Run with: BRON_SLOW=1 uv run --project core/Engine pytest tests/test_history_speed.py -q -s"""
import io
import json
import time

import pytest

from bron import hooks
from bron.history import save
from histkit import hvault

pytestmark = pytest.mark.slow


def grow(vault, n=300):
    for i in range(n):
        path = vault.knowledge_dir / "Documents" / f"Doc {i:03d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: document\n---\n# Doc {i}\n" + "line\n" * 40)


def best_of(fn, n=5):
    times = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return min(times)


def test_the_message_step_stays_inside_its_budget(vault, monkeypatch):
    grow(vault)
    hvault(vault)
    clean = best_of(lambda: save.on_prompt(vault, cli="claude", session_id="s", prompt="hi"))
    print(f"\nnothing changed: {clean * 1000:.0f} ms")
    assert clean < 0.050

    def edit_and_save():
        for i in range(3):
            (vault.knowledge_dir / "Documents" / f"Doc {i:03d}.md").write_text(f"changed {time.time()}\n")
        save.on_prompt(vault, cli="claude", session_id="s", prompt="hi")

    dirty = best_of(edit_and_save)
    print(f"3 pages changed: {dirty * 1000:.0f} ms")
    assert dirty < 0.100


def test_the_stop_trigger_does_not_wait_for_git(vault, monkeypatch):
    grow(vault)
    hvault(vault)
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    monkeypatch.setattr("bron.background.spawn_detached", lambda *a, **k: True)
    took = best_of(lambda: hooks.main("stop", "claude", stdin=io.StringIO(json.dumps({"session_id": "s"})), stdout=io.StringIO()))
    print(f"stop trigger: {took * 1000:.0f} ms")
    assert took < 0.050
```

- [ ] **Step 2: Run it**

Run: `BRON_SLOW=1 core/Engine/.venv/bin/python -m pytest tests/test_history_speed.py -q -s -p no:cacheprovider`
Expected: 2 passed, with printed times near the spec's measurements (about 15 ms nothing changed, about 35 ms changed). If the "nothing changed" step is over budget, profile `repo.state` and `read_settings` first; `frontmatter.read` of Settings should be about 1 ms.

- [ ] **Step 3: Write the live test** (it follows `tests/live/test_memory.py`'s helpers and style; skipped unless `BRON_LIVE=1`)

```python
# tests/live/test_history.py
"""Live history: one real turn that edits a page makes one save credited to the right agent and app.
Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_history.py -q -s"""
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]
ASK = "Create the file Projects/History check/README.md containing one line: History check. Then stop."


def make_vault(tmp: Path) -> Path:
    vault = tmp / "History Live"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(vault)], check=True, capture_output=True, timeout=900)
    return vault


def subjects(vault: Path) -> list[str]:
    return subprocess.run(["git", f"--git-dir={vault / '.git'}", "log", "--format=%s"], capture_output=True, text=True).stdout.splitlines()


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_one_turn_one_credited_save(cli, tmp_path):
    vault = make_vault(tmp_path)
    assert subjects(vault)[-1] == "Bron: vault created"
    if cli == "claude":
        cmd = ["claude", "-p", ASK, "--permission-mode", "acceptEdits"]
    else:
        cmd = ["codex", "exec", "-s", "workspace-write", ASK]
    subprocess.run(cmd, cwd=vault, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL, check=True)
    deadline = time.time() + 30  # the turn save is detached
    app = "Claude Code" if cli == "claude" else "Codex"
    while time.time() < deadline and not any(s.startswith(f"Bron ({app}): Create the file") for s in subjects(vault)):
        time.sleep(1)
    assert any(s.startswith(f"Bron ({app}): Create the file") for s in subjects(vault)), subjects(vault)
```

- [ ] **Step 4: Run the full suite**

Run: `core/Engine/.venv/bin/python -m pytest tests -q -p no:cacheprovider`
Expected: all passed (1,437 before this plan, plus the new history tests). Report any failure by name.

Run the live test once per CLI if Claude Code and Codex are signed in: `BRON_LIVE=1 core/Engine/.venv/bin/python -m pytest tests/live/test_history.py -q -s -p no:cacheprovider`. Report the result. The user also tests by hand in the Bron Test Vault before release.

- [ ] **Step 5: Commit**

```bash
git add tests/test_history_speed.py tests/live/test_history.py
git commit -m "History: speed budgets and a live test in both apps"
```

---

## Release (after the user's own test; not part of the tasks)

Follow the release memory: separate commands from the repo folder.
1. `git checkout main`
2. `git merge --ff-only <branch>`
3. `scripts/release.sh 0.9.0`
4. Ask the user before `git push origin main` and `git push origin v0.9.0`.
