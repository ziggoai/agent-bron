# Bron Core Plan 4: install, Obsidian bundle, updates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone on a Mac installs Bron with one pasted line into the folder they choose; every vault gets the Bron Obsidian look without personal state; "Bron, update yourself" pulls the newest GitHub release with a preview, a backup, automatic rollback and undo.

**Architecture:** A small bash `install.sh` does only what needs a shell (Mac check, choosing the folder, downloading, getting `uv`, creating the engine's venv) and hands over to the engine's own `python -m bron.install`, which sets up the vault (template, `System/Core`, shim, Obsidian bundle, global `bron` launcher, PATH line, Codex trust, first sync and check). `scripts/dev-vault.sh` uses the same Python step. `bron update` finds releases through `bron/releases.py` (GitHub via `curl`, a folder of fake releases for tests, or a Bron project folder for development), backs up `System/Core`, swaps it, reinstalls the engine, and lets the *new* engine finish in a fresh process (`bron _after-update`: template files, migrations, Obsidian refresh, sync, check); any failure restores the backup. A daily, cached, 2-second check adds one line to the session briefing when a newer version exists.

**Tech Stack:** Python 3.12 engine (`core/Engine/bron`, run with uv), stdlib-only Python 3.9-safe maintainer scripts, bash (macOS `/bin/bash` 3.2-compatible), `curl`, `tar`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-bron-core-4-install-design.md`

## Global Constraints

- macOS only (12+). `install.sh` must run under macOS's `/bin/bash` 3.2: no associative arrays, no `${var,,}`, no `mapfile`.
- Public repository `ziggoai/agent-bron`. Tags look like `v0.5.0`. Tags API `https://api.github.com/repos/ziggoai/agent-bron/tags?per_page=100`; tarball `https://codeload.github.com/ziggoai/agent-bron/tar.gz/refs/tags/v<version>`; changelog `https://raw.githubusercontent.com/ziggoai/agent-bron/v<version>/CHANGELOG.md`; installer `https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh`.
- All network access from the engine goes through the `curl` command (`subprocess`), never `urllib`: uv-managed Pythons can lack CA certificates.
- Unit tests never touch the network: `tests/conftest.py` sets `BRON_RELEASE_SOURCE` to an empty folder for every non-live test (Task 1).
- Never overwrite the user's own files. In `.obsidian/`, only code files (`main.js`, `manifest.json`, `styles.css`, `theme.css`) are ever replaced; settings files (`data.json`, `app.json`, `appearance.json`, `core-plugins.json`, `community-plugins.json`) are only created when `.obsidian/` didn't exist, except that a first install or repair adds `bron-terminal` and `bron-workspace` to `community-plugins.json`.
- Every message a user sees is plain English for a non-technical person; no stack traces.
- No personal data in tracked files: no `/Users/` paths, no email addresses, no real person's name; Bron-owned manifests say `"author": "Ziggo AI"`.
- Default install folder when asking: `~/Documents/Bron`. Finish message: "Your Bron vault is ready at <folder>." then "Open this folder in Claude Code or Codex (desktop app or terminal), or in Obsidian, and say hi to Bron."
- Daily update line: "Bron <version> is available. Say 'update yourself' to see what's new." Checked at most once per 24 hours, 2-second limit, silent when offline, cached in `.bron/state/update-check.json`; `update_check: false` in `System/Settings.md` turns it off.
- Core backups: `.bron/backups/core-<version>-<YYYYmmdd-HHMMSS>/`, at most 3 kept.
- Tests: `uv run --project core/Engine pytest tests -q`. Run git as plain, separate commands. Never push. Never stage the untracked `Bron Framework/` folder or the repo-root `.obsidian/`.
- Every commit message ends with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Folders with spaces and accents** (e.g. `~/Documents/Meu Cofre Ágora`): install, launcher, Codex trust entry and update all work. Pinned by Task 4 (`test_trust_codex_with_an_accented_path_parses`), Task 5 (`test_installs_into_an_empty_folder_given_on_the_command_line` uses such a name).
2. **A user who already customised Obsidian** (other theme, own plugins, a Bron plugin switched off): install keeps their settings; update never re-enables or recreates anything. Pinned by Task 3 (`test_existing_obsidian_settings_are_kept`, `test_refresh_leaves_removed_and_disabled_plugins_alone`).
3. **An update that fails half-way** (engine reinstall fails, or the new engine's finishing step fails): Bron is back on the old version with its old engine, and says so plainly. Pinned by Task 6 (`test_failed_engine_install_rolls_back`, `test_failed_finishing_step_rolls_back`).
4. **No internet or slow GitHub at session start:** the briefing isn't delayed past ~2 seconds, says nothing, and doesn't retry within the day. Pinned by Task 7 (`test_offline_is_silent_and_cached`, `test_github_check_uses_a_two_second_limit`).
5. **`curl … | bash` with no way to ask** (stdin is the script; no terminal): when a question is needed, the installer stops with the exact command to pass a folder, and changes nothing. Pinned by Task 5 (`test_no_terminal_to_ask_explains_how_to_pass_a_folder`).

---

### Task 1: Release sources (`bron/releases.py`)

**Files:**
- Create: `core/Engine/bron/releases.py`
- Create: `tests/releasekit.py`
- Create: `tests/test_releases.py`
- Modify: `tests/conftest.py` (autouse fixture)

**Interfaces:**
- Produces:
  - `class ReleaseError(RuntimeError)` — message is user-facing.
  - `parse_version(text: str) -> tuple[int, int, int] | None` (accepts `0.5.0` and `v0.5.0`).
  - `newest(tags: list[str]) -> str | None` — newest `vX.Y.Z` tag, returned without the `v`.
  - `is_newer(candidate: str, current: str) -> bool`.
  - `changes_between(changelog: str, current: str, latest: str) -> str` — `## X.Y.Z` sections with current < X.Y.Z <= latest, newest first, joined by a blank line.
  - `unpack(tarball: Path, dest: Path) -> Path` — returns the single top folder.
  - `check_tree(tree: Path, version: str) -> None` — raises if `tree/core/VERSION` != version.
  - Sources, each with `latest() -> str | None`, `changelog(version: str) -> str`, `fetch(version: str, dest: Path) -> Path` (returns the unpacked release tree containing `core/`, `template/`, `CHANGELOG.md`): `GitHubReleases(timeout: int = 60)`, `LocalReleases(folder: Path)`, `ProjectFolder(folder: Path)`.
  - `SOURCE_FILE = "source"` (in `.bron/`), `GITHUB = "github"`, `ENV_SOURCE = "BRON_RELEASE_SOURCE"`.
  - `select_source(vault: Vault, from_folder: Path | None = None, *, timeout: int = 60)` — env → `LocalReleases`; `from_folder` → `ProjectFolder`; `.bron/source` missing/empty/`github` → `GitHubReleases(timeout)`; otherwise `ProjectFolder(Path(text))`.
  - `tests/releasekit.py`: `make_release(folder: Path, version: str, *, core_version: str | None = None, changelog: str = "", extra: dict[str, str] | None = None) -> Path` and `write_tags(folder: Path, versions: list[str]) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/releasekit.py`:

```python
"""Fake Bron releases for tests: tarballs shaped like GitHub's, plus a tags.json like GitHub's tags API."""
import json
import shutil
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", ".pytest_cache", ".DS_Store")


def write_tags(folder: Path, versions: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tags.json").write_text(json.dumps([{"name": f"v{v}"} for v in versions]), encoding="utf-8")


def make_release(folder: Path, version: str, *, core_version: str | None = None, changelog: str = "", extra: dict[str, str] | None = None) -> Path:
    """Build folder/agent-bron-<version>.tar.gz from this repo's core/ and template/, with VERSION set."""
    folder.mkdir(parents=True, exist_ok=True)
    stage = folder / f"stage-{version}"
    top = stage / f"agent-bron-{version}"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(REPO / "core", top / "core", ignore=IGNORE)
    shutil.copytree(REPO / "template", top / "template", ignore=IGNORE)
    (top / "core" / "VERSION").write_text((core_version or version) + "\n", encoding="utf-8")
    (top / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    for rel, text in (extra or {}).items():
        path = top / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    tarball = folder / f"agent-bron-{version}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(top, arcname=top.name)
    shutil.rmtree(stage)
    return tarball
```

`tests/test_releases.py`:

```python
import pytest

from bron import releases
from bron.releases import (
    GitHubReleases, LocalReleases, ProjectFolder, ReleaseError,
    changes_between, is_newer, newest, parse_version, select_source,
)
from releasekit import REPO, make_release, write_tags

CHANGELOG = """# Changelog

## 0.6.0
- Six.

## 0.5.0
- Five.

## 0.4.1
- Four one.
"""


def test_parse_version():
    assert parse_version("v0.5.0") == (0, 5, 0)
    assert parse_version("0.10.2") == (0, 10, 2)
    assert parse_version("latest") is None
    assert parse_version("v1.0") is None


def test_newest_compares_numbers_not_text():
    assert newest(["v0.9.1", "v0.10.0", "latest", "v0.2.0"]) == "0.10.0"
    assert newest(["nightly"]) is None
    assert newest([]) is None


def test_is_newer():
    assert is_newer("0.5.0", "0.4.1")
    assert not is_newer("0.4.1", "0.4.1")
    assert not is_newer("0.4.0", "0.4.1")


def test_changes_between_keeps_only_the_new_sections():
    text = changes_between(CHANGELOG, "0.4.1", "0.6.0")
    assert text.startswith("## 0.6.0")
    assert "Five." in text
    assert "Four one." not in text


def test_local_releases_fetch(tmp_path):
    source = tmp_path / "releases"
    make_release(source, "0.6.0", changelog=CHANGELOG)
    write_tags(source, ["0.5.0", "0.6.0"])
    local = LocalReleases(source)
    assert local.latest() == "0.6.0"
    assert "Six." in local.changelog("0.6.0")
    tree = local.fetch("0.6.0", tmp_path / "work")
    assert (tree / "core" / "VERSION").read_text().strip() == "0.6.0"
    assert (tree / "template" / "System" / "Settings.md").is_file()


def test_a_download_with_the_wrong_version_is_refused(tmp_path):
    source = tmp_path / "releases"
    make_release(source, "0.6.0", core_version="0.5.9")
    with pytest.raises(ReleaseError, match="doesn't contain that version"):
        LocalReleases(source).fetch("0.6.0", tmp_path / "work")


def test_missing_tags_reads_like_github_not_answering(tmp_path):
    with pytest.raises(ReleaseError, match="GitHub didn't answer"):
        LocalReleases(tmp_path / "nothing").latest()


def test_missing_tarball(tmp_path):
    write_tags(tmp_path, ["0.6.0"])
    with pytest.raises(ReleaseError, match="couldn't be downloaded"):
        LocalReleases(tmp_path).fetch("0.6.0", tmp_path / "work")


def test_project_folder_is_its_own_release(tmp_path):
    project = ProjectFolder(REPO)
    version = (REPO / "core" / "VERSION").read_text().strip()
    assert project.latest() == version
    tree = project.fetch(version, tmp_path / "work")
    assert (tree / "core" / "Engine" / "bron" / "cli.py").is_file()
    assert not list(tree.rglob("__pycache__"))


def test_project_folder_that_moved(tmp_path):
    with pytest.raises(ReleaseError, match="can't find the Bron project"):
        ProjectFolder(tmp_path / "gone").latest()


def test_select_source(vault, tmp_path, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    assert isinstance(select_source(vault), GitHubReleases)
    vault.bron_dir.mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "source").write_text("github\n")
    assert isinstance(select_source(vault), GitHubReleases)
    (vault.bron_dir / "source").write_text(f"{tmp_path}\n")
    assert select_source(vault) == ProjectFolder(tmp_path)
    assert select_source(vault, from_folder=REPO) == ProjectFolder(REPO)
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(tmp_path))
    assert select_source(vault) == LocalReleases(tmp_path)


def test_github_source_reads_tags_through_curl(monkeypatch):
    calls = []

    def fake_curl(url, *, timeout, out=None):
        calls.append((url, timeout))
        return b'[{"name": "v0.5.0"}, {"name": "v0.10.0"}]'

    monkeypatch.setattr(releases, "_curl", fake_curl)
    assert GitHubReleases(timeout=2).latest() == "0.10.0"
    assert calls == [("https://api.github.com/repos/ziggoai/agent-bron/tags?per_page=100", 2)]


def test_github_garbage_answer(monkeypatch):
    monkeypatch.setattr(releases, "_curl", lambda url, *, timeout, out=None: b"<html>rate limited</html>")
    with pytest.raises(ReleaseError, match="GitHub didn't answer"):
        GitHubReleases().latest()


def test_unit_tests_never_reach_github(vault):
    assert isinstance(select_source(vault), LocalReleases)
```

Add to `tests/conftest.py`, inside the existing `_private_codex_home` autouse fixture, after the `CODEX_HOME` line:

```python
    # Unit tests never reach GitHub: releases come from an empty folder unless a test makes some.
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(tmp_path_factory.mktemp("no-releases")))
```

`tests/` must be importable as a module path for `releasekit`: it already is for `vaultkit` (check how `tests/test_*.py` import `vaultkit` and do the same).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_releases.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bron.releases'`.

- [ ] **Step 3: Write the implementation**

`core/Engine/bron/releases.py`:

```python
"""Where Bron releases come from: GitHub, a folder of fake releases (tests), or a Bron project folder (development)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .vault import Vault

REPO = "ziggoai/agent-bron"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
TARBALL_URL = f"https://codeload.github.com/{REPO}/tar.gz/refs/tags/v{{version}}"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/v{{version}}/CHANGELOG.md"
SOURCE_FILE = "source"  # in .bron/: "github", or the Bron project folder this vault follows
GITHUB = "github"
ENV_SOURCE = "BRON_RELEASE_SOURCE"
NO_ANSWER = "GitHub didn't answer; try again later."
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_HEADING = re.compile(r"^## +v?(\d+\.\d+\.\d+)\b.*$", re.M)
_IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", ".pytest_cache", ".DS_Store")


class ReleaseError(RuntimeError):
    """A release problem, in plain words."""


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def _key(text: str) -> tuple[int, int, int]:
    return parse_version(text) or (0, 0, 0)


def newest(tags: list[str]) -> str | None:
    found = [tag[1:] for tag in tags if tag.startswith("v") and parse_version(tag)]
    return max(found, key=_key) if found else None


def is_newer(candidate: str, current: str) -> bool:
    return _key(candidate) > _key(current)


def changes_between(changelog: str, current: str, latest: str) -> str:
    """The changelog's `## X.Y.Z` sections newer than `current`, up to `latest`, newest first."""
    heads = list(_HEADING.finditer(changelog))
    sections = []
    for i, head in enumerate(heads):
        if _key(current) < _key(head.group(1)) <= _key(latest):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(changelog)
            sections.append((_key(head.group(1)), changelog[head.start():end].strip()))
    return "\n\n".join(text for _, text in sorted(sections, reverse=True))


def _curl(url: str, *, timeout: int, out: Path | None = None) -> bytes:
    command = ["curl", "-fsSL", "--connect-timeout", str(timeout), "--max-time", str(timeout), url]
    if out is not None:
        command += ["-o", str(out)]
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError(NO_ANSWER) from exc
    if done.returncode != 0:
        raise ReleaseError(NO_ANSWER)
    return done.stdout


def _tag_names(data: bytes | str) -> list[str]:
    try:
        return [str(item["name"]) for item in json.loads(data)]
    except (ValueError, TypeError, KeyError) as exc:
        raise ReleaseError(NO_ANSWER) from exc


def unpack(tarball: Path, dest: Path) -> Path:
    """Unpack a release tarball into dest and return its single top folder."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tarball) as tar:
            tar.extractall(dest, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseError("The download was damaged; nothing was changed.") from exc
    tops = [path for path in dest.iterdir() if path.is_dir()]
    if len(tops) != 1:
        raise ReleaseError("The download didn't look like a Bron release; nothing was changed.")
    return tops[0]


def check_tree(tree: Path, version: str) -> None:
    try:
        found = (tree / "core" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        found = ""
    if found != version:
        raise ReleaseError(f"The download for version {version} doesn't contain that version; nothing was changed.")


@dataclass(frozen=True)
class GitHubReleases:
    timeout: int = 60

    def latest(self) -> str | None:
        return newest(_tag_names(_curl(TAGS_URL, timeout=self.timeout)))

    def changelog(self, version: str) -> str:
        return _curl(CHANGELOG_URL.format(version=version), timeout=self.timeout).decode("utf-8", "replace")

    def fetch(self, version: str, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        tarball = dest / "release.tar.gz"
        _curl(TARBALL_URL.format(version=version), timeout=600, out=tarball)
        tree = unpack(tarball, dest / "tree")
        check_tree(tree, version)
        return tree


@dataclass(frozen=True)
class LocalReleases:
    """A folder standing in for GitHub: tags.json (the tags API's shape) and agent-bron-<version>.tar.gz files."""

    folder: Path

    def latest(self) -> str | None:
        try:
            data = (self.folder / "tags.json").read_text(encoding="utf-8")
        except OSError as exc:
            raise ReleaseError(NO_ANSWER) from exc
        return newest(_tag_names(data))

    def _tarball(self, version: str) -> Path:
        path = self.folder / f"agent-bron-{version}.tar.gz"
        if not path.is_file():
            raise ReleaseError(f"Version {version} couldn't be downloaded; nothing was changed.")
        return path

    def changelog(self, version: str) -> str:
        with tarfile.open(self._tarball(version)) as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.count("/") == 1 and member.name.endswith("/CHANGELOG.md"):
                    handle = tar.extractfile(member)
                    return handle.read().decode("utf-8", "replace") if handle else ""
        return ""

    def fetch(self, version: str, dest: Path) -> Path:
        tree = unpack(self._tarball(version), dest / "tree")
        check_tree(tree, version)
        return tree


@dataclass(frozen=True)
class ProjectFolder:
    """A Bron project folder on this Mac (development): its current files are the release."""

    folder: Path

    def latest(self) -> str | None:
        try:
            return (self.folder / "core" / "VERSION").read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ReleaseError(
                f"Bron can't find the Bron project at {self.folder} any more. "
                "If it moved, run `bron update --from <its new folder>`."
            ) from exc

    def changelog(self, version: str) -> str:
        try:
            return (self.folder / "CHANGELOG.md").read_text(encoding="utf-8")
        except OSError:
            return ""

    def fetch(self, version: str, dest: Path) -> Path:
        tree = dest / "tree"
        tree.mkdir(parents=True, exist_ok=True)
        for name in ("core", "template"):
            shutil.copytree(self.folder / name, tree / name, ignore=_IGNORE)
        if (self.folder / "CHANGELOG.md").is_file():
            shutil.copy2(self.folder / "CHANGELOG.md", tree / "CHANGELOG.md")
        check_tree(tree, version)
        return tree


def select_source(vault: Vault, from_folder: Path | None = None, *, timeout: int = 60):
    env = os.environ.get(ENV_SOURCE)
    if env:
        return LocalReleases(Path(env))
    if from_folder is not None:
        return ProjectFolder(Path(from_folder).expanduser().resolve())
    try:
        text = (vault.bron_dir / SOURCE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text in ("", GITHUB):
        return GitHubReleases(timeout=timeout)
    return ProjectFolder(Path(text))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_releases.py -q` → PASS. Then the full suite: `uv run --project core/Engine pytest tests -q` → all pass (the old `tests/test_update.py` still passes; it is replaced in Task 6).

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/releases.py tests/releasekit.py tests/test_releases.py tests/conftest.py
git commit -m "Release sources: GitHub through curl, local fake releases, Bron project folders"
```

---

### Task 2: The Obsidian bundle (`scripts/export-obsidian.py`, `core/Obsidian/`, `template/.obsidian/`)

**Files:**
- Create: `scripts/export-obsidian.py`
- Create (generated by the script, then committed): `core/Obsidian/themes/Bron/{theme.css,manifest.json}`, `core/Obsidian/plugins/<id>/{main.js,manifest.json,styles.css}` for the seven bundled plugins, `template/.obsidian/{app.json,appearance.json,core-plugins.json,community-plugins.json}`, `template/.obsidian/plugins/{colored-tags,obsidian-style-settings,obsidian-icon-folder}/data.json`, `template/.obsidian/icons/<pack>/*.svg` (the icons the vault uses)
- Create (by hand): `core/Obsidian/THIRD-PARTY-NOTICES.md`, `core/Obsidian/licenses/*.txt`
- Modify: `.gitignore`
- Test: `tests/test_obsidian_bundle.py`

**Interfaces:**
- Produces: the bundle layout above. `core/Obsidian/` never contains `data.json`. Later tasks read `core/Obsidian/themes/*/` and `core/Obsidian/plugins/*/` (code files) and `template/.obsidian/` (first-install settings).
- Script CLI: `scripts/export-obsidian.py <source vault> [--repo <folder>]` (default repo: the script's own repository). Exit 0 on success; exit 1 with a plain message when a bundled plugin or the theme is missing from the source, or when a scrub check fails.

The maintainer's source vault is this repository folder itself (its git-ignored `.obsidian/`). Note: its `appearance.json` currently selects "Bron v2"; the bundle always selects the v1 theme "Bron".

Bundled plugins (ids): `bron-workspace`, `colored-tags`, `data-files-editor`, `file-explorer-note-count`, `obsidian-icon-folder` (Iconize, shipped switched off), `obsidian-style-settings`, `xlsx-viewer`. Theme: `Bron`. Left out: `obsidian-file-color`, `termy`, `bron-v2-*`, `Bron v2`, `bron-terminal` (comes from `core/Plugins`, Task 3), and Iconize's downloadable icon-pack archives (`.obsidian/icons/*.zip`, ~80 MB). The user's requirement: **the vault must look exactly like the maintainer's**. The Bron theme's own file and folder icons are embedded in `theme.css` (about 30 SVGs as `data:` URLs), so `theme.css` ships byte for byte; the icons already extracted into `.obsidian/icons/<pack>/*.svg` (today: `tabler-icons/FileTextAi.svg`, used for AGENTS.md) ship too, with Iconize's matching assignment.

- [ ] **Step 1: Write the failing tests**

`tests/test_obsidian_bundle.py`:

```python
"""The shipped Obsidian bundle: complete, and free of personal state."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "core" / "Obsidian"
TEMPLATE = REPO / "template" / ".obsidian"
SCRIPT = REPO / "scripts" / "export-obsidian.py"
PLUGINS = ["bron-workspace", "colored-tags", "data-files-editor", "file-explorer-note-count", "obsidian-icon-folder", "obsidian-style-settings", "xlsx-viewer"]
THIRD_PARTY = [p for p in PLUGINS if p != "bron-workspace"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")


def all_files():
    return [p for root in (BUNDLE, TEMPLATE) for p in root.rglob("*") if p.is_file()]


def test_bundle_has_the_theme_and_every_plugin():
    assert (BUNDLE / "themes" / "Bron" / "theme.css").is_file()
    for plugin in PLUGINS:
        assert (BUNDLE / "plugins" / plugin / "main.js").is_file(), plugin
        assert json.loads((BUNDLE / "plugins" / plugin / "manifest.json").read_text())["id"] == plugin


def test_left_out_items_are_not_shipped():
    shipped = {p.name for p in (BUNDLE / "plugins").iterdir()}
    assert not shipped & {"obsidian-file-color", "termy", "bron-v2-terminal", "bron-v2-ai-usage", "bron-terminal"}
    assert {p.name for p in (BUNDLE / "themes").iterdir()} == {"Bron"}
    assert not list((TEMPLATE / "icons").rglob("*.zip"))


def test_the_theme_keeps_its_embedded_icons_exactly():
    css = (BUNDLE / "themes" / "Bron" / "theme.css").read_text()
    assert css.count("data:image/svg+xml") >= 30
    source = REPO / ".obsidian" / "themes" / "Bron" / "theme.css"
    if source.is_file():  # the maintainer's own vault (not in git)
        assert (BUNDLE / "themes" / "Bron" / "theme.css").read_bytes() == source.read_bytes()


def test_the_icons_the_vault_uses_ship_too():
    icons = [p for p in (TEMPLATE / "icons").rglob("*") if p.is_file()]
    assert icons and all(p.suffix == ".svg" for p in icons)
    assert sum(p.stat().st_size for p in icons) < 1_000_000
    assert (TEMPLATE / "icons" / "tabler-icons" / "FileTextAi.svg").is_file()


def test_no_settings_in_the_code_bundle():
    assert not list(BUNDLE.rglob("data.json"))


def test_no_personal_state_in_template():
    for name in ("workspace.json", "workspace-mobile.json", "graph.json", "devin-backups"):
        assert not (TEMPLATE / name).exists(), name


def test_no_personal_paths_or_emails_anywhere():
    for path in all_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "/Users/" not in text, path
        assert not EMAIL.search(text), (path, EMAIL.search(text).group(0))


def test_bron_owned_items_are_credited_to_ziggo_ai():
    for manifest in (BUNDLE / "themes" / "Bron" / "manifest.json", BUNDLE / "plugins" / "bron-workspace" / "manifest.json"):
        data = json.loads(manifest.read_text())
        assert data["author"] == "Ziggo AI"
        assert "authorUrl" not in data and "fundingUrl" not in data


def test_first_install_settings():
    appearance = json.loads((TEMPLATE / "appearance.json").read_text())
    assert appearance["cssTheme"] == "Bron"
    enabled = json.loads((TEMPLATE / "community-plugins.json").read_text())
    assert "bron-terminal" in enabled and "bron-workspace" in enabled
    assert "obsidian-icon-folder" not in enabled
    iconize = json.loads((TEMPLATE / "plugins" / "obsidian-icon-folder" / "data.json").read_text())
    assert iconize["settings"]["recentlyUsedIcons"] == []
    assert iconize["AGENTS.md"] == "TiFileTextAi"  # the icon the maintainer's vault shows for AGENTS.md


def test_template_obsidian_is_tracked_by_git():
    done = subprocess.run(["git", "check-ignore", "-q", str(TEMPLATE / "appearance.json")], cwd=REPO)
    assert done.returncode == 1  # 1 = not ignored


def test_third_party_notices_cover_every_plugin():
    notices = (BUNDLE / "THIRD-PARTY-NOTICES.md").read_text()
    for plugin in THIRD_PARTY:
        assert plugin in notices, plugin
    assert "GPL-3.0" in notices  # Style Settings


def make_source(root: Path, *, leak: str = "") -> Path:
    """A fake maintainer vault built from the shipped bundle, with personal state added."""
    config = root / ".obsidian"
    for plugin in PLUGINS:
        shutil.copytree(BUNDLE / "plugins" / plugin, config / "plugins" / plugin)
        (config / "plugins" / plugin / "data.json").write_text('{"secret": "personal"}')
    manifest = config / "plugins" / "bron-workspace" / "manifest.json"
    data = json.loads(manifest.read_text())
    data.update(author="Somebody Personal", authorUrl="https://example.org/me")
    manifest.write_text(json.dumps(data))
    shutil.copytree(BUNDLE / "themes" / "Bron", config / "themes" / "Bron")
    (config / "themes" / "Bron" / "README.md").write_text("theme notes")
    (config / "icons" / "tabler-icons").mkdir(parents=True)
    (config / "icons" / "tabler-icons" / "FileTextAi.svg").write_text("<svg/>")
    (config / "icons" / "tabler-icons.zip").write_bytes(b"big archive")
    (config / "workspace.json").write_text('{"open": "Somebody notes"}')
    (config / "core-plugins.json").write_text(json.dumps({"file-explorer": True, "graph": False}))
    (config / "appearance.json").write_text(json.dumps({"cssTheme": "Bron v2"}))
    if leak:
        with open(config / "plugins" / "xlsx-viewer" / "main.js", "a") as fh:
            fh.write(leak)
    return root


def run_export(source: Path, repo: Path):
    return subprocess.run([sys.executable, str(SCRIPT), str(source), "--repo", str(repo)], capture_output=True, text=True)


def test_export_scrubs_a_source_vault(tmp_path):
    source = make_source(tmp_path / "Source Vault")
    repo = tmp_path / "repo"
    done = run_export(source, repo)
    assert done.returncode == 0, done.stdout + done.stderr
    out = repo / "core" / "Obsidian"
    tpl = repo / "template" / ".obsidian"
    assert not list(out.rglob("data.json"))
    assert not (out / "themes" / "Bron" / "README.md").exists()
    assert json.loads((out / "plugins" / "bron-workspace" / "manifest.json").read_text())["author"] == "Ziggo AI"
    assert not (tpl / "workspace.json").exists()
    assert json.loads((tpl / "appearance.json").read_text())["cssTheme"] == "Bron"
    assert json.loads((tpl / "core-plugins.json").read_text()) == {"file-explorer": True, "graph": False}
    assert "secret" not in (tpl / "plugins" / "colored-tags" / "data.json").read_text()
    assert (tpl / "icons" / "tabler-icons" / "FileTextAi.svg").read_text() == "<svg/>"
    assert not list((tpl / "icons").rglob("*.zip"))


def test_export_refuses_a_personal_path(tmp_path):
    source = make_source(tmp_path / "Source Vault", leak='var p="/Users/someone/vault";')
    done = run_export(source, tmp_path / "repo")
    assert done.returncode == 1
    assert "xlsx-viewer" in done.stdout + done.stderr


def test_export_needs_every_plugin(tmp_path):
    source = make_source(tmp_path / "Source Vault")
    shutil.rmtree(source / ".obsidian" / "plugins" / "xlsx-viewer")
    done = run_export(source, tmp_path / "repo")
    assert done.returncode == 1
    assert "xlsx-viewer" in done.stdout + done.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_obsidian_bundle.py -q`
Expected: FAIL — bundle files and script don't exist.

- [ ] **Step 3: Write the export script**

`scripts/export-obsidian.py` (stdlib only, must run on Python 3.9):

```python
#!/usr/bin/env python3
"""Refresh Bron's Obsidian bundle from a source vault, leaving personal state behind.

Usage: scripts/export-obsidian.py <source vault> [--repo <folder>]

Writes core/Obsidian/themes + core/Obsidian/plugins (code files only) and template/.obsidian
(first-install settings). THIRD-PARTY-NOTICES.md and licenses/ in core/Obsidian are kept as they are.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

OWNER = "Ziggo AI"
THEME = "Bron"
PLUGINS = ["bron-workspace", "colored-tags", "data-files-editor", "file-explorer-note-count", "obsidian-icon-folder", "obsidian-style-settings", "xlsx-viewer"]
OWN_PLUGINS = {"bron-workspace"}  # made by the Bron project
DISABLED = {"obsidian-icon-folder"}  # shipped, but switched off
CODE_FILES = ["main.js", "manifest.json", "styles.css"]
THEME_FILES = ["theme.css", "manifest.json"]
APPEARANCE = {"cssTheme": THEME, "theme": "moonstone", "accentColor": "#386bc2", "baseFontSize": 14}
# Reviewed first-install settings. Every other plugin starts from its own defaults.
SETTINGS = {
    "colored-tags": {
        "palette": {"seed": 0, "selected": "adaptive-soft", "custom": "e12729-f37324-f8cc1b-72b043-007f4e"},
        "mixColors": True,
        "transition": True,
        "accessibility": {"highTextContrast": False},
        "knownTags": {},
        "tagColors": {},
        "_version": 4,
    },
    "obsidian-style-settings": {"bron-terminal@@bron-terminal-font-size": 13},
    "obsidian-icon-folder": {
        "settings": {
            "migrated": 6,
            "iconPacksPath": ".obsidian/icons",
            "fontSize": 16,
            "emojiStyle": "native",
            "iconColor": None,
            "recentlyUsedIcons": [],
            "recentlyUsedIconsSize": 5,
            "rules": [],
            "extraMargin": {"top": 0, "right": 4, "bottom": 0, "left": 0},
            "iconInTabsEnabled": False,
            "iconInTitleEnabled": False,
            "iconInTitlePosition": "above",
            "iconInFrontmatterEnabled": False,
            "iconInFrontmatterFieldName": "icon",
            "iconColorInFrontmatterFieldName": "iconColor",
            "iconsBackgroundCheckEnabled": False,
            "iconsInNotesEnabled": True,
            "iconsInLinksEnabled": True,
            "iconIdentifier": ":",
            "lucideIconPackType": "native",
            "debugMode": False,
            "useInternalPlugins": False,
        },
        "AGENTS.md": "TiFileTextAi",  # icon assignments are kept; personal history (recently used) is not
    },
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")


class ExportError(Exception):
    pass


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def own_manifest(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["author"] = OWNER
    data.pop("authorUrl", None)
    data.pop("fundingUrl", None)
    write_json(path, data)


def copy_files(src: Path, dest: Path, names: list[str], *, required: list[str]) -> None:
    for name in required:
        if not (src / name).is_file():
            raise ExportError(f"{src.name} is missing {name} in the source vault")
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        if (src / name).is_file():
            shutil.copy2(src / name, dest / name)


def export(source: Path, repo: Path) -> None:
    config = source / ".obsidian"
    if not config.is_dir():
        raise ExportError(f"{source} has no .obsidian folder")
    bundle = repo / "core" / "Obsidian"
    template = repo / "template" / ".obsidian"
    for plugin in PLUGINS:
        if not (config / "plugins" / plugin).is_dir():
            raise ExportError(f"the source vault doesn't have the plugin {plugin}")
    if not (config / "themes" / THEME).is_dir():
        raise ExportError(f"the source vault doesn't have the {THEME} theme")
    shutil.rmtree(bundle / "plugins", ignore_errors=True)
    shutil.rmtree(bundle / "themes", ignore_errors=True)
    shutil.rmtree(template, ignore_errors=True)
    for plugin in PLUGINS:
        dest = bundle / "plugins" / plugin
        copy_files(config / "plugins" / plugin, dest, CODE_FILES, required=["main.js", "manifest.json"])
        if plugin in OWN_PLUGINS:
            own_manifest(dest / "manifest.json")
    theme = bundle / "themes" / THEME
    copy_files(config / "themes" / THEME, theme, THEME_FILES, required=THEME_FILES)
    own_manifest(theme / "manifest.json")
    write_json(template / "app.json", {})
    write_json(template / "appearance.json", APPEARANCE)
    core_plugins = json.loads((config / "core-plugins.json").read_text(encoding="utf-8")) if (config / "core-plugins.json").is_file() else {}
    if not isinstance(core_plugins, dict) or not all(isinstance(v, bool) for v in core_plugins.values()):
        raise ExportError("core-plugins.json in the source vault isn't a list of on/off switches")
    write_json(template / "core-plugins.json", core_plugins)
    write_json(template / "community-plugins.json", ["bron-terminal", *[p for p in PLUGINS if p not in DISABLED]])
    for plugin, data in SETTINGS.items():
        write_json(template / "plugins" / plugin / "data.json", data)
    copy_icons(config / "icons", template / "icons")
    scrub([bundle / "plugins", bundle / "themes", template], source.name)


def copy_icons(src: Path, dest: Path) -> None:
    """The icons already extracted into the vault (small SVGs), without the downloadable pack archives."""
    if not src.is_dir():
        return
    for svg in sorted(src.rglob("*.svg")):
        target = dest / svg.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg, target)


def scrub(roots: list[Path], vault_name: str) -> None:
    problems = []
    distinctive = vault_name if len(vault_name) > 4 and vault_name.lower() not in {"bron", "vault", "notes"} else ""
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "/Users/" in text:
                problems.append(f"{path.relative_to(root.parent)}: contains a /Users/ path")
            match = EMAIL.search(text)
            if match:
                problems.append(f"{path.relative_to(root.parent)}: contains an email address ({match.group(0)})")
            if distinctive and distinctive in text:
                problems.append(f"{path.relative_to(root.parent)}: mentions the source vault's name")
    if problems:
        raise ExportError("personal details found:\n" + "\n".join(f"- {p}" for p in problems))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        export(args.source.expanduser().resolve(), args.repo.resolve())
    except (ExportError, OSError, ValueError) as exc:
        print(f"Export stopped: {exc}", file=sys.stderr)
        return 1
    print(f"Obsidian bundle refreshed from {args.source}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Un-ignore the template's Obsidian folder**

Append to `.gitignore` (after the `.obsidian/` line's block, at the end of the file):

```
# The starting vault's Obsidian settings ship with the framework
!/template/.obsidian/
```

- [ ] **Step 5: Run the export against the maintainer's vault**

Run: `python3 scripts/export-obsidian.py .`
Expected: `Obsidian bundle refreshed from .` — if it stops with "personal details found", report the lines (don't edit third-party code to hide them) and stop as BLOCKED.

- [ ] **Step 6: Write the notices and licences by hand**

Download the licence texts (network allowed for this step):

```bash
mkdir -p core/Obsidian/licenses
curl -fsSL https://raw.githubusercontent.com/pfrankov/obsidian-colored-tags/HEAD/LICENSE -o core/Obsidian/licenses/colored-tags.txt
curl -fsSL https://raw.githubusercontent.com/ZukTol/obsidian-data-files-editor/HEAD/LICENSE -o core/Obsidian/licenses/data-files-editor.txt
curl -fsSL https://raw.githubusercontent.com/FlorianWoelki/obsidian-iconize/HEAD/LICENSE -o core/Obsidian/licenses/obsidian-icon-folder.txt
curl -fsSL https://raw.githubusercontent.com/obsidian-community/obsidian-style-settings/HEAD/LICENSE -o core/Obsidian/licenses/obsidian-style-settings.txt
curl -fsSL https://raw.githubusercontent.com/viggomeesters/obsidian-xlsx-viewer/HEAD/LICENSE -o core/Obsidian/licenses/xlsx-viewer.txt
cp .obsidian/themes/Bron/assets/IBM-Plex-LICENSE.txt core/Obsidian/licenses/font-ibm-plex.txt
cp .obsidian/themes/Bron/assets/Inter-LICENSE.txt core/Obsidian/licenses/font-inter.txt
```

If a URL fails, try `LICENSE.md` / `LICENSE.txt` / `license` at the same place; if none exists, leave that file out and say so in the notices row. File Explorer Note Count has no licence file (its `package.json` says MIT).

Check that every downloaded/copied licence file passes the scrub rules (no `/Users/`; an email address in a licence's copyright line must be removed from the file rather than shipped — replace the address with the author's name only and note it in the report).

`core/Obsidian/THIRD-PARTY-NOTICES.md`:

```markdown
# Third-party software in Bron's Obsidian bundle

Bron ships unmodified builds of these Obsidian plugins so every vault looks the same. Each keeps its own licence; the licence texts are in `licenses/`.

| Plugin (id) | Version | Author | Licence | Source |
|---|---|---|---|---|
| Colored Tags (`colored-tags`) | 7.0.0 | Pavel Frankov | MIT | https://github.com/pfrankov/obsidian-colored-tags |
| Data Files Editor (`data-files-editor`) | 1.3.0 | ZukTol | MIT | https://github.com/ZukTol/obsidian-data-files-editor |
| File Explorer Note Count (`file-explorer-note-count`) | 1.2.4 | Ozan Tellioglu | MIT (declared in its package.json) | https://github.com/ozntel/file-explorer-note-count |
| Iconize (`obsidian-icon-folder`) | 2.14.7 | Florian Woelki | MIT | https://github.com/FlorianWoelki/obsidian-iconize |
| Style Settings (`obsidian-style-settings`) | 1.0.9 | mgmeyers | GPL-3.0 | https://github.com/obsidian-community/obsidian-style-settings |
| XLSX Viewer (`xlsx-viewer`) | 0.1.0 | Viggo Meesters | MIT | https://github.com/viggomeesters/obsidian-xlsx-viewer |

The Bron theme embeds the IBM Plex and Inter fonts (SIL Open Font License 1.1; see `licenses/font-*.txt`).

The Bron theme, Bron Workspace and Bron Terminal are part of Bron (MIT, Ziggo AI).
```

Take the version numbers from the exported manifests (`core/Obsidian/plugins/<id>/manifest.json`); if one differs from the table above, use the manifest's.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_obsidian_bundle.py -q` → PASS. Then the full suite → all pass (the test vault fixture now also contains `.obsidian/`; if an existing test breaks because of it, report which and why before changing it).

- [ ] **Step 8: Commit**

```bash
git add .gitignore scripts/export-obsidian.py core/Obsidian template/.obsidian tests/test_obsidian_bundle.py
git status --short   # must not list Bron Framework/ or the root .obsidian/
git commit -m "Ship the Obsidian bundle: Bron theme and plugins, first-install settings, no personal state"
```

---

### Task 3: Installing the bundle into a vault (`bron/obsidian.py`, terminal installer in `core/`)

**Files:**
- Move: `scripts/install-terminal.py` → `core/Plugins/install_terminal.py` (`git mv`), then create a new thin `scripts/install-terminal.py`
- Modify: `tests/test_terminal_install.py:10` (load the moved file)
- Create: `core/Engine/bron/obsidian.py`
- Test: `tests/test_obsidian.py`

**Interfaces:**
- Consumes: bundle layout from Task 2 (`<core>/Obsidian/themes/<name>/`, `<core>/Obsidian/plugins/<id>/`), `<core>/Plugins/bron-terminal/` payload, `<core>/Plugins/install_terminal.py` with `install(vault: Path, source: Path, enable: bool = True) -> Path`.
- Produces:
  - `class BundleError(RuntimeError)` — plain message.
  - `install_bundle(vault_root: Path, core: Path, template_config: Path | None) -> list[str]` — first install or repair; returns notes for the user.
  - `refresh_bundle(vault_root: Path, core: Path) -> list[str]` — after an update; returns notes (normally empty).
  - `THEME_TIP = "Your Obsidian settings were kept. To use Bron's look, pick the Bron theme in Obsidian: Settings → Appearance → Themes."`

- [ ] **Step 1: Move the terminal installer into core**

```bash
git mv scripts/install-terminal.py core/Plugins/install_terminal.py
```

In `core/Plugins/install_terminal.py`, change the `--source` default in the `__main__` block from `Path(__file__).resolve().parents[1] / 'core/Plugins/bron-terminal'` to `Path(__file__).resolve().parent / 'bron-terminal'`. Nothing else changes (it stays Python 3.9-safe).

Create `scripts/install-terminal.py`:

```python
#!/usr/bin/env python3
"""Install the bundled Bron Terminal into a vault. The installer itself ships in core/Plugins/install_terminal.py."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "core" / "Plugins" / "install_terminal.py"), run_name="__main__")
```

In `tests/test_terminal_install.py` line 10, load `ROOT / 'core/Plugins/install_terminal.py'` instead of `ROOT / 'scripts/install-terminal.py'`. Run `uv run --project core/Engine pytest tests/test_terminal_install.py tests/test_terminal_payload.py -q` → PASS (if `test_terminal_payload.py` lists the files of `core/Plugins/`, adjust only that listing to allow `install_terminal.py` beside `bron-terminal/`, and say so in the report).

- [ ] **Step 2: Write the failing tests**

`tests/test_obsidian.py`:

```python
import json
import shutil
from pathlib import Path

import pytest

from bron.obsidian import THEME_TIP, BundleError, install_bundle, refresh_bundle

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_CONFIG = REPO / "template" / ".obsidian"


def config(vault) -> Path:
    return vault.root / ".obsidian"


def enabled(vault) -> list:
    return json.loads((config(vault) / "community-plugins.json").read_text())


def test_fresh_vault_gets_the_full_bron_setup(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    notes = install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert notes == []
    assert json.loads((config(vault) / "appearance.json").read_text())["cssTheme"] == "Bron"
    assert (config(vault) / "themes" / "Bron" / "theme.css").is_file()
    assert (config(vault) / "plugins" / "colored-tags" / "main.js").is_file()
    assert (config(vault) / "plugins" / "bron-terminal" / "main.js").is_file()
    assert {"bron-terminal", "bron-workspace"} <= set(enabled(vault))
    assert "obsidian-icon-folder" not in enabled(vault)


def test_existing_obsidian_settings_are_kept(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    (config(vault) / "plugins" / "colored-tags").mkdir(parents=True)
    (config(vault) / "appearance.json").write_text('{"cssTheme": "Minimal"}')
    (config(vault) / "community-plugins.json").write_text('["dataview"]')
    (config(vault) / "plugins" / "colored-tags" / "data.json").write_text('{"mine": true}')
    (config(vault) / "plugins" / "colored-tags" / "main.js").write_text("old code")
    notes = install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert notes == [THEME_TIP]
    assert (config(vault) / "appearance.json").read_text() == '{"cssTheme": "Minimal"}'
    assert enabled(vault) == ["dataview", "bron-terminal", "bron-workspace"]
    assert (config(vault) / "plugins" / "colored-tags" / "data.json").read_text() == '{"mine": true}'
    assert (config(vault) / "plugins" / "colored-tags" / "main.js").read_text() != "old code"
    assert not (config(vault) / "app.json").exists()


def test_no_theme_tip_when_bron_is_already_the_theme(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    config(vault).mkdir()
    (config(vault) / "appearance.json").write_text('{"cssTheme": "Bron"}')
    assert install_bundle(vault.root, vault.core, TEMPLATE_CONFIG) == []


def test_unreadable_plugin_list_is_left_alone(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    config(vault).mkdir()
    (config(vault) / "community-plugins.json").write_text('{"not": "a list"}')
    with pytest.raises(BundleError, match="community-plugins.json"):
        install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert (config(vault) / "community-plugins.json").read_text() == '{"not": "a list"}'


def test_a_linked_plugin_folder_is_left_alone(vault, tmp_path):
    shutil.rmtree(config(vault), ignore_errors=True)
    elsewhere = tmp_path / "my-dev-copy"
    elsewhere.mkdir()
    (elsewhere / "main.js").write_text("my dev build")
    (config(vault) / "plugins").mkdir(parents=True)
    (config(vault) / "plugins" / "xlsx-viewer").symlink_to(elsewhere)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert (elsewhere / "main.js").read_text() == "my dev build"


def test_refresh_without_obsidian_does_nothing(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    assert refresh_bundle(vault.root, vault.core) == []
    assert not config(vault).exists()


def test_refresh_leaves_removed_and_disabled_plugins_alone(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    shutil.rmtree(config(vault) / "plugins" / "xlsx-viewer")
    (config(vault) / "community-plugins.json").write_text('["colored-tags"]')
    (config(vault) / "plugins" / "colored-tags" / "main.js").write_text("old code")
    (config(vault) / "plugins" / "colored-tags" / "data.json").write_text('{"mine": true}')
    refresh_bundle(vault.root, vault.core)
    assert not (config(vault) / "plugins" / "xlsx-viewer").exists()
    assert enabled(vault) == ["colored-tags"]
    assert (config(vault) / "plugins" / "colored-tags" / "main.js").read_text() != "old code"
    assert (config(vault) / "plugins" / "colored-tags" / "data.json").read_text() == '{"mine": true}'
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_obsidian.py -q`
Expected: FAIL — `No module named 'bron.obsidian'`.

- [ ] **Step 4: Write the implementation**

`core/Engine/bron/obsidian.py`:

```python
"""Bron's Obsidian bundle in a vault: theme and plugins added without touching the user's own settings."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path

ENABLE_ON_INSTALL = ("bron-terminal", "bron-workspace")
SETTINGS_FILES = {"data.json"}
THEME = "Bron"
THEME_TIP = "Your Obsidian settings were kept. To use Bron's look, pick the Bron theme in Obsidian: Settings → Appearance → Themes."


class BundleError(RuntimeError):
    """The Obsidian bundle couldn't be set up, in plain words."""


def _replace_file(src: Path, dest: Path) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}-", dir=dest.parent)
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _copy_code(core: Path, config: Path, *, only_present: bool) -> None:
    """Copy the bundled theme and plugin code (never settings) into .obsidian."""
    for kind in ("themes", "plugins"):
        folder = core / "Obsidian" / kind
        if not folder.is_dir():
            continue
        for item in sorted(p for p in folder.iterdir() if p.is_dir()):
            target = config / kind / item.name
            if target.is_symlink() or (only_present and not target.is_dir()):
                continue
            target.mkdir(parents=True, exist_ok=True)
            for src in sorted(item.iterdir()):
                if src.is_file() and src.name not in SETTINGS_FILES:
                    _replace_file(src, target / src.name)


def _read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BundleError("Obsidian's community-plugins.json isn't a plugin list, so it was left as it is; Bron's plugins weren't switched on.")
    return value


def _enable(config: Path, ids: tuple[str, ...]) -> None:
    path = config / "community-plugins.json"
    current = _read_list(path)
    missing = [item for item in ids if item not in current]
    if not missing:
        return
    fd, tmp = tempfile.mkstemp(prefix=".community-plugins-", dir=config)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(current + missing, stream, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _terminal(core: Path, vault_root: Path, *, enable: bool) -> None:
    script = core / "Plugins" / "install_terminal.py"
    spec = importlib.util.spec_from_file_location("bron_install_terminal", script)
    if spec is None or spec.loader is None:
        raise BundleError("Bron Terminal's installer is missing from System/Core/Plugins.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.install(vault_root, core / "Plugins" / "bron-terminal", enable)
    except (OSError, ValueError, KeyError) as exc:
        raise BundleError(f"Bron Terminal couldn't be installed ({exc}).") from exc


def _theme(config: Path) -> str:
    try:
        data = json.loads((config / "appearance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("cssTheme", "")) if isinstance(data, dict) else ""


def install_bundle(vault_root: Path, core: Path, template_config: Path | None) -> list[str]:
    """First install or repair: a vault without .obsidian gets Bron's whole Obsidian setup; one with it keeps its settings."""
    config = vault_root / ".obsidian"
    fresh = not config.exists()
    if fresh and template_config is not None and template_config.is_dir():
        shutil.copytree(template_config, config)
    config.mkdir(exist_ok=True)
    _read_list(config / "community-plugins.json")  # refuse before changing anything
    _copy_code(core, config, only_present=False)
    _terminal(core, vault_root, enable=True)
    _enable(config, ENABLE_ON_INSTALL)
    return [] if fresh or _theme(config) == THEME else [THEME_TIP]


def refresh_bundle(vault_root: Path, core: Path) -> list[str]:
    """After an update: refresh the code of Bron's theme and plugins that are there; settings and the plugin list stay as they are."""
    config = vault_root / ".obsidian"
    if not config.is_dir():
        return []
    _copy_code(core, config, only_present=True)
    if (config / "plugins" / "bron-terminal").is_dir():
        _terminal(core, vault_root, enable=False)
    return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_obsidian.py tests/test_terminal_install.py tests/test_terminal_payload.py -q` → PASS; full suite → all pass.

- [ ] **Step 6: Commit**

```bash
git add core/Plugins/install_terminal.py scripts/install-terminal.py tests/test_terminal_install.py core/Engine/bron/obsidian.py tests/test_obsidian.py
git commit -m "Install and refresh the Obsidian bundle without touching the user's settings; terminal installer ships in core"
```

---

### Task 4: Setting up a vault (`bron/install.py`) and `scripts/dev-vault.sh`

**Files:**
- Create: `core/Engine/bron/install.py`
- Modify: `scripts/dev-vault.sh` (rewrite)
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: `bron.obsidian.install_bundle`, `BundleError` (Task 3); `bron.releases.SOURCE_FILE` (Task 1); `bron.cli.main(argv) -> int`.
- Produces:
  - `copy_template(vault_root: Path, template: Path) -> None` — copies files that don't exist yet; skips `.obsidian` and `.DS_Store`.
  - `replace_core(vault_root: Path, core_src: Path) -> None` — `System/Core` becomes an exact copy of `core_src` (ignoring `.venv`, `__pycache__`, `*.egg-info`, `.pytest_cache`, `.DS_Store`), swapped in via a staging folder.
  - `write_shim(vault_root: Path) -> None`, `write_source(vault_root: Path, label: str) -> None`.
  - `install_launcher(home: Path) -> str | None`, `ensure_path(home: Path, path_env: str) -> str | None`, `trust_codex(home: Path, vault_root: Path, *, codex_installed: bool) -> str | None`.
  - `install_vault(vault_root: Path, tree: Path, *, source: str, home: Path | None) -> int` — prints its notes and the sync/check output; returns 0, or 1 when sync fails.
  - CLI: `python -m bron.install <vault> --tree <release tree> --source <github|folder> [--no-home]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_install.py`:

```python
import os
import subprocess
import tomllib
from pathlib import Path

from bron import install
from bron.install import (
    LAUNCHER, PATH_LINE, copy_template, ensure_path, install_launcher, install_vault,
    replace_core, trust_codex, write_shim,
)

REPO = Path(__file__).resolve().parents[1]


def test_copy_template_never_overwrites_and_skips_obsidian(tmp_path):
    vault = tmp_path / "v"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "Settings.md").write_text("mine")
    copy_template(vault, REPO / "template")
    assert (vault / "System" / "Settings.md").read_text() == "mine"
    assert (vault / "Tickets" / "Board.base").is_file()
    assert not (vault / ".obsidian").exists()


def test_replace_core_is_exact_and_keeps_user_files(vault):
    (vault.core / "stale.md").write_text("old")
    (vault.system / "Agents" / "note.md").write_text("mine")
    replace_core(vault.root, REPO / "core")
    assert not (vault.core / "stale.md").exists()
    assert (vault.core / "VERSION").is_file()
    assert not list(vault.core.rglob("__pycache__"))
    assert (vault.system / "Agents" / "note.md").read_text() == "mine"
    assert not [p for p in vault.system.iterdir() if p.name.startswith(".Core")]


def test_shim_runs_the_vault_engine(tmp_path):
    write_shim(tmp_path)
    shim = tmp_path / ".bron" / "bin" / "bron"
    assert os.access(shim, os.X_OK)
    assert '.bron/venv/bin/python" -m bron' in shim.read_text()


def make_fake_vault(root: Path) -> Path:
    (root / "System" / "Core").mkdir(parents=True)
    (root / "System" / "Core" / "VERSION").write_text("0.5.0\n")
    shim = root / ".bron" / "bin" / "bron"
    shim.parent.mkdir(parents=True)
    shim.write_text('#!/bin/sh\necho "vault bron: $*"\n')
    shim.chmod(0o755)
    return root


def test_launcher_finds_the_vault_from_a_subfolder(tmp_path):
    home = tmp_path / "home"
    assert install_launcher(home) is None
    launcher = home / ".local" / "bin" / "bron"
    vault = make_fake_vault(tmp_path / "Meu Cofre Ágora")
    inside = vault / "Projects" / "Deep"
    inside.mkdir(parents=True)
    done = subprocess.run([str(launcher), "check"], cwd=inside, capture_output=True, text=True)
    assert done.stdout.strip() == "vault bron: check"


def test_launcher_outside_a_vault(tmp_path):
    home = tmp_path / "home"
    install_launcher(home)
    done = subprocess.run([str(home / ".local" / "bin" / "bron"), "check"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 2
    assert "isn't inside a Bron vault" in done.stderr


def test_someone_elses_bron_command_is_kept(tmp_path):
    home = tmp_path / "home"
    other = home / ".local" / "bin" / "bron"
    other.parent.mkdir(parents=True)
    other.write_text("#!/bin/sh\necho other\n")
    note = install_launcher(home)
    assert "already a different `bron` command" in note
    assert other.read_text() == "#!/bin/sh\necho other\n"


def test_our_launcher_is_updated_in_place(tmp_path):
    home = tmp_path / "home"
    install_launcher(home)
    (home / ".local" / "bin" / "bron").write_text("# installed by Bron's installer\nold")
    assert install_launcher(home) is None
    assert (home / ".local" / "bin" / "bron").read_text() == LAUNCHER


def test_path_line_added_once_on_its_own_line(tmp_path):
    (tmp_path / ".zprofile").write_text("export FOO=1")  # no trailing newline
    assert "~/.zprofile" in ensure_path(tmp_path, "/usr/bin:/bin")
    assert ensure_path(tmp_path, "/usr/bin:/bin") is None
    text = (tmp_path / ".zprofile").read_text()
    assert text == "export FOO=1\n" + PATH_LINE + "\n"


def test_no_path_line_when_already_on_path(tmp_path):
    assert ensure_path(tmp_path, f"/usr/bin:{tmp_path}/.local/bin") is None
    assert not (tmp_path / ".zprofile").exists()


def test_trust_codex_adds_the_vault_once_with_a_backup(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "gpt-5"')  # no trailing newline
    vault = tmp_path / "Bron"
    assert "trusts this vault" in trust_codex(home, vault, codex_installed=True)
    assert trust_codex(home, vault, codex_installed=True) is None
    data = tomllib.loads(config.read_text())
    assert data["model"] == "gpt-5"
    assert data["projects"][str(vault)]["trust_level"] == "trusted"
    assert len(list(config.parent.glob("config.toml.bron-backup-*"))) == 1


def test_trust_codex_with_an_accented_path_parses(tmp_path):
    home = tmp_path / "home"
    vault = tmp_path / 'Meu Cofre Ágora "x"'
    trust_codex(home, vault, codex_installed=True)
    data = tomllib.loads((home / ".codex" / "config.toml").read_text())
    assert data["projects"][str(vault)]["trust_level"] == "trusted"


def test_trust_codex_respects_an_existing_entry(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    vault = tmp_path / "Bron"
    original = f'[projects."{vault}"]\ntrust_level = "untrusted"\n'
    config.write_text(original)
    assert trust_codex(home, vault, codex_installed=True) is None
    assert config.read_text() == original


def test_trust_codex_leaves_a_file_it_cant_extend(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    original = 'projects = { other = { trust_level = "trusted" } }\n'
    config.write_text(original)
    note = trust_codex(home, tmp_path / "Bron", codex_installed=True)
    assert "Codex will ask" in note
    assert config.read_text() == original


def test_trust_codex_skips_when_codex_isnt_there(tmp_path):
    assert trust_codex(tmp_path, tmp_path / "Bron", codex_installed=False) is None
    assert not (tmp_path / ".codex").exists()


def test_install_vault_end_to_end(tmp_path, monkeypatch, capsys):
    root = tmp_path / "Meu Cofre Ágora"
    home = tmp_path / "home"
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    code = install_vault(root, REPO, source="github", home=home)
    out = capsys.readouterr().out
    assert code == 0, out
    assert (root / "System" / "Core" / "VERSION").is_file()
    assert (root / ".bron" / "source").read_text().strip() == "github"
    assert (root / ".bron" / "bin" / "bron").is_file()
    assert (root / ".obsidian" / "themes" / "Bron" / "theme.css").is_file()
    assert (root / "AGENTS.md").is_file()  # first sync ran
    assert (home / ".local" / "bin" / "bron").is_file()
    assert "Bron health check" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_install.py -q`
Expected: FAIL — `No module named 'bron.install'`.

- [ ] **Step 3: Write the implementation**

`core/Engine/bron/install.py`:

```python
"""Setting up a vault from a Bron release folder. Used by install.sh, scripts/dev-vault.sh and `bron update`.

Run as: python -m bron.install <vault> --tree <release folder> --source <github|project folder> [--no-home]
(the engine's venv in <vault>/.bron/venv must already exist; install.sh and dev-vault.sh create it).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import tomllib
from pathlib import Path

from .releases import SOURCE_FILE

CORE_IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", ".pytest_cache", ".DS_Store")
SHIM = """#!/bin/sh
VAULT="$(cd "$(dirname "$0")/../.." && pwd)"
export BRON_VAULT="$VAULT"
exec "$VAULT/.bron/venv/bin/python" -m bron "$@"
"""
LAUNCHER_MARK = "installed by Bron's installer"
LAUNCHER = f"""#!/bin/sh
# Bron: runs the bron command of the vault you're in ({LAUNCHER_MARK}).
dir="$PWD"
while :; do
  if [ -f "$dir/System/Core/VERSION" ] && [ -x "$dir/.bron/bin/bron" ]; then
    exec "$dir/.bron/bin/bron" "$@"
  fi
  [ "$dir" = "/" ] && break
  dir="$(dirname "$dir")"
done
echo "bron: this folder isn't inside a Bron vault. Go to your vault folder first (cd \\"<your vault>\\")." >&2
exit 2
"""
PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH"  # added by the Bron installer'


def copy_template(vault_root: Path, template: Path) -> None:
    """Copy the starting vault where files are missing; nothing that exists is overwritten. Obsidian is obsidian.py's job."""
    for src in sorted(template.rglob("*")):
        rel = src.relative_to(template)
        if rel.parts[0] == ".obsidian" or src.name == ".DS_Store" or "__pycache__" in rel.parts:
            continue
        dest = vault_root / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists() and not dest.is_symlink():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def replace_core(vault_root: Path, core_src: Path) -> None:
    """System/Core becomes an exact copy of the release's core/ (it is framework-owned)."""
    system = vault_root / "System"
    system.mkdir(parents=True, exist_ok=True)
    target = system / "Core"
    stage = system / f".Core-new-{os.getpid()}"
    old = system / f".Core-old-{os.getpid()}"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    shutil.copytree(core_src, stage, ignore=CORE_IGNORE)
    if target.exists():
        target.rename(old)
    try:
        stage.rename(target)
    except OSError:
        if old.exists():
            old.rename(target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def write_shim(vault_root: Path) -> None:
    shim = vault_root / ".bron" / "bin" / "bron"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(SHIM, encoding="utf-8")
    shim.chmod(0o755)


def write_source(vault_root: Path, label: str) -> None:
    path = vault_root / ".bron" / SOURCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(label + "\n", encoding="utf-8")


def install_launcher(home: Path) -> str | None:
    launcher = home / ".local" / "bin" / "bron"
    if launcher.exists() or launcher.is_symlink():
        try:
            ours = LAUNCHER_MARK in launcher.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ours = False
        if not ours:
            return f"There's already a different `bron` command at {launcher}, so Bron's own wasn't added. Inside your vault, use .bron/bin/bron."
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)
    return None


def ensure_path(home: Path, path_env: str) -> str | None:
    if str(home / ".local" / "bin") in path_env.split(":"):
        return None
    profile = home / ".zprofile"
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if PATH_LINE in text:
        return None
    separator = "" if not text or text.endswith("\n") else "\n"
    profile.write_text(text + separator + PATH_LINE + "\n", encoding="utf-8")
    return "Added ~/.local/bin to your PATH in ~/.zprofile, so the `bron` command works in new Terminal windows."


def trust_codex(home: Path, vault_root: Path, *, codex_installed: bool) -> str | None:
    config = home / ".codex" / "config.toml"
    if not config.exists() and not codex_installed:
        return None
    cannot = "Codex's settings file couldn't be extended, so this vault wasn't marked as trusted there; Codex will ask the first time you open it."
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return cannot
    projects = data.get("projects")
    key = str(vault_root)
    if isinstance(projects, dict) and key in projects:
        return None
    separator = "" if not text or text.endswith("\n") else "\n"
    new_text = text + separator + f"\n[projects.{json.dumps(key)}]\ntrust_level = \"trusted\"\n"
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        return cannot
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        shutil.copy2(config, config.with_name(f"config.toml.bron-backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    config.write_text(new_text, encoding="utf-8")
    return "Codex now trusts this vault (its settings were backed up next to them first)."


def install_vault(vault_root: Path, tree: Path, *, source: str, home: Path | None) -> int:
    from .obsidian import BundleError, install_bundle

    notes: list[str] = []
    copy_template(vault_root, tree / "template")
    replace_core(vault_root, tree / "core")
    write_shim(vault_root)
    write_source(vault_root, source)
    try:
        notes += install_bundle(vault_root, vault_root / "System" / "Core", tree / "template" / ".obsidian")
    except BundleError as exc:
        notes.append(f"Obsidian: {exc}")
    if home is not None:
        notes += [note for note in (
            install_launcher(home),
            ensure_path(home, os.environ.get("PATH", "")),
            trust_codex(home, vault_root, codex_installed=shutil.which("codex") is not None),
        ) if note]
    for note in notes:
        print(note)
    from .cli import main as bron

    previous = os.environ.get("BRON_VAULT")
    os.environ["BRON_VAULT"] = str(vault_root)
    try:
        code = bron(["sync"])
        bron(["check"])
    finally:
        if previous is None:
            os.environ.pop("BRON_VAULT", None)
        else:
            os.environ["BRON_VAULT"] = previous
    return 0 if code == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bron.install")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--tree", type=Path, required=True, help="the unpacked release (with core/ and template/)")
    parser.add_argument("--source", required=True, help="'github' or the Bron project folder updates come from")
    parser.add_argument("--no-home", action="store_true", help="don't add the global bron command, PATH line or Codex trust")
    args = parser.parse_args(argv)
    if not (args.tree / "core" / "VERSION").is_file():
        print(f"{args.tree} isn't a Bron release (no core/VERSION).", file=sys.stderr)
        return 1
    return install_vault(args.vault.resolve(), args.tree.resolve(), source=args.source, home=None if args.no_home else Path.home())


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Rewrite `scripts/dev-vault.sh`**

```bash
#!/usr/bin/env bash
# Create or refresh a development Bron vault from this repository (the same steps as install.sh, from this folder).
# Usage: scripts/dev-vault.sh <vault-path>
# - Your files are only copied where missing; nothing of yours is overwritten.
# - System/Core is always replaced with the repository's core/.
# - `bron update` in that vault keeps following this folder.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?usage: scripts/dev-vault.sh <vault-path>}"
mkdir -p "$TARGET"
VAULT="$(cd "$TARGET" && pwd)"

uv venv --quiet --allow-existing --python 3.12 "$VAULT/.bron/venv"
uv pip install --quiet --python "$VAULT/.bron/venv/bin/python" --reinstall-package bron-engine "$REPO/core/Engine"
"$VAULT/.bron/venv/bin/python" -m bron.install "$VAULT" --tree "$REPO" --source "$REPO" --no-home
echo "Dev vault ready: $VAULT"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_install.py -q` → PASS; full suite → all pass.
Then a real dev vault: `scripts/dev-vault.sh "$TMPDIR/bron dev vault"` → ends with `Dev vault ready:`; `"$TMPDIR/bron dev vault/.bron/bin/bron" version` prints the version; `cat "$TMPDIR/bron dev vault/.bron/source"` prints the repo path. Delete that folder afterwards.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/install.py scripts/dev-vault.sh tests/test_install.py
git commit -m "Vault setup step shared by the installer and dev vaults: template, core, shim, Obsidian, launcher, PATH, Codex trust"
```

---

### Task 5: The one-line installer (`install.sh`)

**Files:**
- Create: `install.sh` (repo root, executable)
- Test: `tests/test_install_sh.py`

**Interfaces:**
- Consumes: `python -m bron.install <vault> --tree <tree> --source <label>` (Task 4).
- Environment (for tests and development): `BRON_INSTALL_SOURCE` (a release tarball or a project folder; skips GitHub), `BRON_TTY` (file answers are read from; default `/dev/tty`), `BRON_YES=1` (answer yes to confirmations).
- Folder argument: `bash install.sh <folder>` or `curl … | bash -s -- <folder>`.

- [ ] **Step 1: Write the failing tests**

`tests/test_install_sh.py`:

```python
"""install.sh end to end, against a local release tarball, a temporary HOME and scripted answers."""
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.sh"
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", ".pytest_cache", ".DS_Store")

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")


@pytest.fixture(scope="module")
def tarball(tmp_path_factory):
    stage = tmp_path_factory.mktemp("release") / "agent-bron-test"
    shutil.copytree(REPO / "core", stage / "core", ignore=IGNORE)
    shutil.copytree(REPO / "template", stage / "template", ignore=IGNORE)
    path = stage.parent / "release.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        tar.add(stage, arcname=stage.name)
    return path


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text('model = "gpt-5"\n')
    return home


def run(home, tarball, *args, cwd=None, answers=None, yes=False, tty=None):
    env = {
        "HOME": str(home),
        "PATH": f"{Path(shutil.which('uv')).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "BRON_INSTALL_SOURCE": str(tarball),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv")),
        "UV_PYTHON_INSTALL_DIR": os.environ.get("UV_PYTHON_INSTALL_DIR", str(Path.home() / ".local" / "share" / "uv" / "python")),
    }
    if answers is not None:
        answer_file = home.parent / "answers.txt"
        answer_file.write_text(answers)
        env["BRON_TTY"] = str(answer_file)
    elif tty is not None:
        env["BRON_TTY"] = tty
    else:
        env["BRON_TTY"] = str(home.parent / "no-terminal")
    if yes:
        env["BRON_YES"] = "1"
    done = subprocess.run(["bash", str(INSTALLER), *args], cwd=cwd or home, env=env, capture_output=True, text=True, timeout=600)
    return done.returncode, done.stdout + done.stderr


def test_installs_into_an_empty_folder_given_on_the_command_line(home, tarball, tmp_path):
    target = tmp_path / "Meu Cofre Ágora"
    code, out = run(home, tarball, str(target))
    assert code == 0, out
    assert (target / "System" / "Core" / "VERSION").is_file()
    assert (target / ".bron" / "source").read_text().strip() == "github"
    assert (target / ".obsidian" / "themes" / "Bron" / "theme.css").is_file()
    assert (home / ".local" / "bin" / "bron").is_file()
    assert (home / ".zprofile").read_text().count("added by the Bron installer") == 1
    trusted = tomllib.loads((home / ".codex" / "config.toml").read_text())["projects"]
    assert trusted[str(target)]["trust_level"] == "trusted"
    assert f"Your Bron vault is ready at {target}." in out
    assert "say hi to Bron" in out
    assert "Obsidian" in out


def test_rerun_repairs_and_changes_nothing_of_yours(home, tarball, tmp_path):
    target = tmp_path / "Bron"
    assert run(home, tarball, str(target))[0] == 0
    (target / "Projects" / "My note.md").write_text("mine")
    (target / "Tickets" / "Board.base").unlink()
    code, out = run(home, tarball, str(target))
    assert code == 0, out
    assert "repairing" in out
    assert (target / "Projects" / "My note.md").read_text() == "mine"
    assert (target / "Tickets" / "Board.base").is_file()
    assert (home / ".zprofile").read_text().count("added by the Bron installer") == 1
    assert (home / ".codex" / "config.toml").read_text().count(str(target)) == 1


def test_a_folder_with_other_files_needs_a_yes(home, tarball, tmp_path):
    target = tmp_path / "Notes"
    target.mkdir()
    (target / "old.md").write_text("mine")
    code, out = run(home, tarball, str(target), answers="n\n")
    assert code == 1
    assert "Nothing was changed" in out
    assert sorted(p.name for p in target.iterdir()) == ["old.md"]
    code, out = run(home, tarball, str(target), answers="y\n")
    assert code == 0, out
    assert (target / "old.md").read_text() == "mine"
    assert (target / "System" / "Core" / "VERSION").is_file()


def test_home_folder_asks_and_defaults_to_documents_bron(home, tarball):
    code, out = run(home, tarball, cwd=home, answers="\n")
    assert code == 0, out
    assert "~/Documents/Bron" in out
    assert (home / "Documents" / "Bron" / "System" / "Core" / "VERSION").is_file()
    assert not (home / "System").exists()


def test_no_terminal_to_ask_explains_how_to_pass_a_folder(home, tarball):
    code, out = run(home, tarball, cwd=home)
    assert code == 1
    assert "bash -s --" in out
    assert not (home / "Documents" / "Bron").exists()


def test_system_folders_are_not_used(home, tarball):
    code, out = run(home, tarball, "/Library")
    assert code == 1
    assert "bash -s --" in out


def test_icloud_folder_warns_and_can_be_declined(home, tarball):
    target = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Bron"
    code, out = run(home, tarball, str(target), answers="n\n")
    assert code == 1
    assert "iCloud" in out
    assert not target.exists()


def test_existing_obsidian_settings_are_kept(home, tarball, tmp_path):
    target = tmp_path / "Vault"
    (target / ".obsidian").mkdir(parents=True)
    (target / ".obsidian" / "appearance.json").write_text('{"cssTheme": "Minimal"}')
    (target / ".obsidian" / "community-plugins.json").write_text('["dataview"]')
    code, out = run(home, tarball, str(target), yes=True)
    assert code == 0, out
    assert (target / ".obsidian" / "appearance.json").read_text() == '{"cssTheme": "Minimal"}'
    assert json.loads((target / ".obsidian" / "community-plugins.json").read_text()) == ["dataview", "bron-terminal", "bron-workspace"]
    assert "Bron theme" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_install_sh.py -q`
Expected: FAIL — `install.sh` doesn't exist (bash exits 127).

- [ ] **Step 3: Write `install.sh`**

```bash
#!/usr/bin/env bash
# Install Bron on a Mac:
#   curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash
# Into a chosen folder:
#   curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash -s -- "<folder>"
# Safe to run again: it repairs an existing Bron vault and never overwrites your files.
set -euo pipefail

REPO="ziggoai/agent-bron"
DEFAULT_FOLDER="$HOME/Documents/Bron"
TTY="${BRON_TTY:-/dev/tty}"
TTY_STATE=0   # 0 not opened yet, 1 open on fd 3, 2 can't ask
ANSWER=""
STEP="starting"

say() { printf '%s\n' "$*"; }
fail() { printf '\nBron install stopped (%s): %s\n' "$STEP" "$*" >&2; exit 1; }
cant_ask() {
  fail "Bron needs an answer but can't ask in this window. Run it again with the folder to use, for example:
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | bash -s -- \"$DEFAULT_FOLDER\""
}

# ask "<question>" "<default>": sets ANSWER; returns 1 when nobody can be asked.
ask() {
  if [ "$TTY_STATE" = 0 ]; then
    if { exec 3<"$TTY"; } 2>/dev/null; then TTY_STATE=1; else TTY_STATE=2; fi
  fi
  [ "$TTY_STATE" = 1 ] || return 1
  printf '%s ' "$1"
  ANSWER=""
  IFS= read -r ANSWER <&3 || true
  [ -n "$ANSWER" ] || ANSWER="$2"
  printf '\n'
  return 0
}

confirm() {
  [ "${BRON_YES:-}" = "1" ] && return 0
  ask "$1 [y/N]" "n" || cant_ask
  case "$ANSWER" in y|Y|yes|Yes|YES) return 0 ;; esac
  say "Nothing was changed."
  exit 1
}

expand() {  # expand a leading ~ and make the path absolute
  local p="$1"
  case "$p" in "~") p="$HOME" ;; "~/"*) p="$HOME/${p#\~/}" ;; esac
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  while [ "${#p}" -gt 1 ] && [ "${p%/}" != "$p" ]; do p="${p%/}"; done
  printf '%s' "$p"
}

is_icloud() { case "$1" in "$HOME/Library/Mobile Documents"|"$HOME/Library/Mobile Documents/"*) return 0 ;; esac; return 1; }

is_system_folder() {
  case "$1" in
    /|"$HOME"|/Users|/Volumes|/System|/System/*|/Library|/Library/*|/Applications|/Applications/*|/usr|/usr/*|/bin|/bin/*|/sbin|/sbin/*|/etc|/etc/*|/private/etc|/private/etc/*|/opt|/opt/*|"$HOME/Library"|"$HOME/Library/"*) return 0 ;;
  esac
  return 1
}

# 1. This Mac
STEP="checking this Mac"
[ "$(uname -s)" = "Darwin" ] || fail "Bron installs on macOS only for now."
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 12 ] 2>/dev/null || fail "Bron needs macOS 12 or newer."
command -v curl >/dev/null 2>&1 || fail "the curl command is missing."
command -v tar >/dev/null 2>&1 || fail "the tar command is missing."
if ! command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
  say "Note: install Claude Code or Codex before talking to Bron."
fi

# 2. The folder
STEP="choosing the folder"
TARGET="$(expand "${1:-$PWD}")"
if is_icloud "$TARGET"; then
  say "$TARGET is in iCloud Drive. Bron's engine doesn't work well there (iCloud can move its files away)."
  confirm "Install there anyway?"
elif is_system_folder "$TARGET"; then
  say "Bron shouldn't be installed straight into $TARGET."
  ask "Where should Bron live? Press Enter for ~/Documents/Bron, or type a folder:" "$DEFAULT_FOLDER" || cant_ask
  TARGET="$(expand "$ANSWER")"
  if is_system_folder "$TARGET" && ! is_icloud "$TARGET"; then fail "$TARGET can't be used either; choose a folder of your own."; fi
  if is_icloud "$TARGET"; then
    say "$TARGET is in iCloud Drive. Bron's engine doesn't work well there (iCloud can move its files away)."
    confirm "Install there anyway?"
  fi
  case "$TARGET" in "$HOME"/*) say "Installing into ~/${TARGET#$HOME/}" ;; *) say "Installing into $TARGET" ;; esac
fi
if [ -f "$TARGET/System/Core/VERSION" ]; then
  say "Found a Bron vault in $TARGET; repairing it. Your files are kept."
elif [ -d "$TARGET" ]; then
  count="$(ls -A "$TARGET" | grep -vc '^\.DS_Store$' || true)"
  if [ "$count" != "0" ]; then
    say "$TARGET already has $count item(s). Bron adds its own folders next to them and never changes your files."
    confirm "Install Bron here?"
  fi
fi

# 3. Download
STEP="downloading Bron"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
LABEL="github"
if [ -n "${BRON_INSTALL_SOURCE:-}" ]; then
  if [ -d "$BRON_INSTALL_SOURCE" ]; then
    SRC="$(cd "$BRON_INSTALL_SOURCE" && pwd)"
    LABEL="$SRC"
  else
    tar -xzf "$BRON_INSTALL_SOURCE" -C "$WORK" || fail "the release file couldn't be unpacked."
    SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  fi
else
  tags="$(curl -fsSL --max-time 30 "https://api.github.com/repos/$REPO/tags?per_page=100")" || fail "GitHub didn't answer; check your internet connection and try again."
  VERSION="$(printf '%s\n' "$tags" | grep -oE '"name": *"v[0-9]+\.[0-9]+\.[0-9]+"' | sed -E 's/.*"v([0-9.]+)"/\1/' | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1 || true)"
  [ -n "$VERSION" ] || fail "Bron hasn't published a release yet."
  say "Downloading Bron $VERSION…"
  curl -fsSL --max-time 600 "https://codeload.github.com/$REPO/tar.gz/refs/tags/v$VERSION" -o "$WORK/bron.tar.gz" || fail "the download didn't finish; nothing was changed."
  tar -xzf "$WORK/bron.tar.gz" -C "$WORK" || fail "the download was damaged; nothing was changed."
  SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [ "$(cat "$SRC/core/VERSION" 2>/dev/null)" = "$VERSION" ] || fail "the download doesn't match version $VERSION; nothing was changed."
fi
[ -f "$SRC/core/VERSION" ] || fail "that isn't a Bron release (no core/VERSION)."

# 4. uv
STEP="getting uv"
UV="$(command -v uv || true)"
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then UV="$HOME/.local/bin/uv"; fi
if [ -z "$UV" ]; then
  say "Installing uv (the tool Bron uses to run its engine)…"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null 2>&1 || fail "uv couldn't be installed; check your internet connection and try again."
  UV="$HOME/.local/bin/uv"
  [ -x "$UV" ] || fail "uv was installed but can't be found in ~/.local/bin."
fi

# 5–9. The vault
STEP="setting up the vault"
mkdir -p "$TARGET" || fail "the folder $TARGET couldn't be created."
VAULT="$(cd "$TARGET" && pwd)"
say "Setting up Bron's engine (this can take a minute the first time)…"
"$UV" venv --quiet --allow-existing --python 3.12 "$VAULT/.bron/venv" || fail "Python 3.12 couldn't be set up for Bron."
"$UV" pip install --quiet --python "$VAULT/.bron/venv/bin/python" --reinstall-package bron-engine "$SRC/core/Engine" || fail "Bron's engine couldn't be installed."
"$VAULT/.bron/venv/bin/python" -m bron.install "$VAULT" --tree "$SRC" --source "$LABEL" || fail "the vault couldn't be finished; run the same command again to repair it."

# 10. Done
say ""
say "Your Bron vault is ready at $VAULT."
say "Open this folder in Claude Code or Codex (desktop app or terminal), or in Obsidian, and say hi to Bron."
```

Then `chmod +x install.sh`.

Notes for the implementer:
- The `ask` prompt and answers go to stdout so the tests (which merge stdout and stderr) see them; with `curl | bash` stdout is the user's terminal.
- The "Installing into ~/…" line prints `~/Documents/Bron` for the default answer (the test checks this).
- With `set -o pipefail`, a `grep` that matches nothing fails the whole pipeline and `set -e` would end the script silently; every pipeline inside `$( … )` that may legitimately match nothing ends in `|| true` (as written above). Keep it that way for any pipeline you add.
- Run `bash -n install.sh` and, if available, `shellcheck install.sh`; fix real findings.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_install_sh.py -q` → PASS (slow: about a minute). Full suite → all pass.

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install_sh.py
git commit -m "One-line installer: choose the folder, download the latest release, set up uv and the vault"
```

---

### Task 6: Migrations, and `bron update` from releases with backup, rollback and undo

**Files:**
- Create: `core/Engine/bron/migrations/__init__.py`
- Modify: `core/Engine/bron/update.py` (rewrite)
- Modify: `core/Engine/bron/cli.py` (`update` arguments; hidden `_after-update` command)
- Modify: `core/Skills/update/SKILL.md` (rewrite)
- Modify: `tests/test_update.py` (rewrite)
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `releases.select_source`, `ReleaseError`, `changes_between`, `is_newer`, `GitHubReleases`, `ProjectFolder` (Task 1); `install.replace_core`, `install.copy_template`, `install.write_source` (Task 4); `obsidian.refresh_bundle`, `BundleError` (Task 3); `setup.run(vault, build, *, preview_only)`, `setup.Change`, `setup.SetupError`; `statefile.locked`, `statefile.read_json`, `statefile.write_json`.
- Produces:
  - `migrations.Migration(id: str, version: str, summary: str, build: Callable[[Config], Change])`, `migrations.MIGRATIONS: list[Migration]` (empty), `migrations.pending(vault, previous: str, current: str, registry: list[Migration] | None = None) -> list[Migration]`, `migrations.apply_pending(vault, previous, current, registry=None) -> list[str]`.
  - `update.preview(vault, source) -> tuple[int, str]`, `update.apply(vault, source) -> tuple[int, str]`, `update.undo(vault) -> tuple[int, str]`, `update.finish(vault, previous: str, tree: Path | None) -> int` (prints; run by the new engine), `update.install_engine(vault) -> None` (raises `RuntimeError`), `update.after_update(vault, previous: str, tree: Path | None) -> tuple[int, str]`, `update.backups(vault) -> list[Path]`.
  - CLI: `bron update [--preview | --undo] [--from FOLDER]`; hidden `bron _after-update --previous X.Y.Z [--tree PATH]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_migrations.py`:

```python
from bron import migrations
from bron.migrations import Migration, apply_pending, pending
from bron.setup import Change


def note(text):
    return lambda cfg: Change(summary=[text], writes={"Projects/Migrated.md": text + "\n"}, done=f"Applied: {text}")


REGISTRY = [
    Migration("old", "0.4.0", "Old change", note("old")),
    Migration("five", "0.5.0", "Five change", note("five")),
    Migration("six", "0.6.0", "Six change", note("six")),
]


def test_pending_is_between_versions_and_in_order(vault):
    assert [m.id for m in pending(vault, "0.4.1", "0.6.0", REGISTRY)] == ["five", "six"]
    assert pending(vault, "0.6.0", "0.4.1", REGISTRY) == []


def test_each_migration_applies_once(vault):
    apply_pending(vault, "0.4.1", "0.5.0", REGISTRY)
    assert (vault.root / "Projects" / "Migrated.md").read_text() == "five\n"
    (vault.root / "Projects" / "Migrated.md").unlink()
    apply_pending(vault, "0.4.1", "0.5.0", REGISTRY)
    assert not (vault.root / "Projects" / "Migrated.md").exists()


def test_the_registry_starts_empty():
    assert migrations.MIGRATIONS == []
```

`tests/test_update.py` (replace the whole file):

```python
import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from bron import update
from bron.cli import main
from bron.releases import LocalReleases, ProjectFolder
from releasekit import REPO, make_release, write_tags

CURRENT = (REPO / "core" / "VERSION").read_text().strip()
CHANGELOG = f"""# Changelog

## 9.1.0
- Newest thing.

## 9.0.0
- Big thing.

## {CURRENT}
- What you have.
"""


@pytest.fixture
def releases(tmp_path, monkeypatch):
    folder = tmp_path / "releases"
    make_release(folder, "9.0.0", changelog=CHANGELOG, extra={"core/Manual/new-page.md": "new\n"})
    write_tags(folder, [CURRENT, "9.0.0"])
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    return folder


@pytest.fixture
def run(vault, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))

    def _run(*args):
        code = main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def engine(monkeypatch):
    """No real uv: record engine installs; run the 'new engine' finishing step in this process."""
    calls = []
    monkeypatch.setattr(update, "install_engine", lambda vault: calls.append(vault.version()))

    def in_process(vault, previous, tree):
        out = io.StringIO()
        with redirect_stdout(out):
            code = update.finish(vault, previous, tree)
        return code, out.getvalue()

    monkeypatch.setattr(update, "after_update", in_process)
    return calls


def test_preview_lists_whats_new(run, releases):
    code, out, _ = run("update", "--preview")
    assert code == 0
    assert f"Bron 9.0.0 is available (you have {CURRENT})" in out
    assert "Big thing." in out
    assert "Newest thing." not in out
    assert "What you have." not in out


def test_preview_when_up_to_date(run, tmp_path, monkeypatch):
    folder = tmp_path / "r"
    write_tags(folder, [CURRENT])
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    code, out, _ = run("update", "--preview")
    assert code == 0
    assert f"Bron is up to date (version {CURRENT})." in out


def test_preview_offline(run):
    code, out, _ = run("update", "--preview")
    assert code == 1
    assert "GitHub didn't answer" in out


def test_apply_updates_backs_up_and_keeps_your_files(run, vault, releases, engine):
    mine = vault.system / "Agents" / "Bron" / "Agent.md"
    before = mine.read_text()
    code, out, _ = run("update")
    assert code == 0, out
    assert f"Updated Bron from version {CURRENT} to 9.0.0." in out
    assert "Start a new session" in out
    assert vault.version() == "9.0.0"
    assert (vault.core / "Manual" / "new-page.md").is_file()
    assert mine.read_text() == before
    assert [b.name.startswith(f"core-{CURRENT}-") for b in update.backups(vault)] == [True]
    assert engine == ["9.0.0"]


def test_a_download_with_the_wrong_version_changes_nothing(run, vault, tmp_path, monkeypatch, engine):
    folder = tmp_path / "bad"
    make_release(folder, "9.0.0", core_version="8.9.9")
    write_tags(folder, ["9.0.0"])
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    code, out, _ = run("update")
    assert code == 1
    assert "doesn't contain that version" in out
    assert vault.version() == CURRENT
    assert update.backups(vault) == []


def test_failed_engine_install_rolls_back(run, vault, releases, monkeypatch):
    attempts = []

    def flaky(v):
        attempts.append(v.version())
        if v.version() == "9.0.0":
            raise RuntimeError("the engine couldn't be installed: no network")

    monkeypatch.setattr(update, "install_engine", flaky)
    code, out, _ = run("update")
    assert code == 1
    assert "didn't finish" in out and "no network" in out
    assert f"went back to version {CURRENT}" in out
    assert vault.version() == CURRENT
    assert not (vault.core / "Manual" / "new-page.md").exists()
    assert attempts == ["9.0.0", CURRENT]


def test_failed_finishing_step_rolls_back(run, vault, releases, monkeypatch):
    monkeypatch.setattr(update, "install_engine", lambda v: None)
    monkeypatch.setattr(update, "after_update", lambda v, previous, tree: (1, "Sync stopped. Fix these first"))
    code, out, _ = run("update")
    assert code == 1
    assert "Sync stopped" in out
    assert vault.version() == CURRENT


def test_undo_goes_back_and_uses_up_the_backup(run, vault, releases, engine):
    run("update")
    code, out, _ = run("update", "--undo")
    assert code == 0, out
    assert f"Went back from version 9.0.0 to {CURRENT}." in out
    assert vault.version() == CURRENT
    assert update.backups(vault) == []


def test_undo_without_a_backup(run):
    code, out, _ = run("update", "--undo")
    assert code == 1
    assert "no earlier version" in out


def test_only_three_backups_are_kept(vault):
    for i in range(5):
        update.backup_core(vault, stamp=f"2026010{i}-000000")
    assert [b.name for b in update.backups(vault)] == [f"core-{CURRENT}-2026010{i}-000000" for i in (2, 3, 4)]


def test_update_from_a_project_folder_refreshes_and_remembers_it(run, vault, engine, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    code, out, _ = run("update", "--from", str(REPO))
    assert code == 0, out
    assert f"already on the latest version ({CURRENT})" in out
    assert (vault.bron_dir / "source").read_text().strip() == str(REPO)


def test_finish_restores_missing_starting_files(vault, tmp_path, capsys):
    (vault.root / "Tickets" / "Board.base").unlink()
    tree = ProjectFolder(REPO).fetch(CURRENT, tmp_path / "work")
    assert update.finish(vault, CURRENT, tree) == 0
    assert (vault.root / "Tickets" / "Board.base").is_file()
    assert "Bron health check" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_update.py tests/test_migrations.py -q`
Expected: FAIL — `No module named 'bron.migrations'`, unknown `--preview`, missing `update.backups`.

- [ ] **Step 3: Write the migrations registry**

`core/Engine/bron/migrations/__init__.py`:

```python
"""Changes to the user's own files that a new framework version needs, applied once after an update.

Each migration is built and applied through the setup change runner (setup.run), so it is checked
first and rolled back as a whole if it fails. Its summary also goes in the release's CHANGELOG entry,
so the update preview mentions it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..loader import Config
from ..releases import parse_version
from ..setup import Change, run
from ..statefile import read_json, write_json
from ..vault import Vault

STATE = "migrations.json"


@dataclass(frozen=True)
class Migration:
    id: str  # stable name, recorded once applied
    version: str  # the framework version that introduced it
    summary: str  # one plain line
    build: Callable[[Config], Change]


MIGRATIONS: list[Migration] = []  # oldest first; none yet


def _applied(vault: Vault) -> set[str]:
    data = read_json(vault.state_dir / STATE, {})
    return set(data.get("applied", [])) if isinstance(data, dict) else set()


def _key(version: str) -> tuple[int, int, int]:
    return parse_version(version) or (0, 0, 0)


def pending(vault: Vault, previous: str, current: str, registry: list[Migration] | None = None) -> list[Migration]:
    done = _applied(vault)
    found = registry if registry is not None else MIGRATIONS
    return [m for m in found if _key(previous) < _key(m.version) <= _key(current) and m.id not in done]


def apply_pending(vault: Vault, previous: str, current: str, registry: list[Migration] | None = None) -> list[str]:
    lines: list[str] = []
    for migration in pending(vault, previous, current, registry):
        lines += run(vault, migration.build, preview_only=False)
        write_json(vault.state_dir / STATE, {"applied": sorted(_applied(vault) | {migration.id})})
    return lines
```

Check `statefile.read_json(path, default)` / `write_json(path, data)` signatures in `core/Engine/bron/statefile.py` before relying on them (they exist at lines 23 and 31); `write_json` must create `.bron/state/` if missing — if it doesn't, create the folder first.

- [ ] **Step 4: Rewrite `core/Engine/bron/update.py`**

```python
"""`bron update`: the newest release from GitHub (or a Bron project folder), previewed, backed up and undoable.

The running (old) engine downloads and checks the release, backs up System/Core, swaps it in and
reinstalls the engine; then the new engine finishes in a fresh process (`bron _after-update`):
starting files, migrations, Obsidian, sync, health check. Any failure puts the backup back.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .install import copy_template, replace_core, write_source
from .releases import ProjectFolder, ReleaseError, changes_between, is_newer
from .statefile import locked
from .vault import Vault

KEEP_BACKUPS = 3
TAIL_LINES = 15
_BACKUP = re.compile(r"^core-(\d+\.\d+\.\d+)-(\d{8}-\d{6})(?:-(\d+))?$")
NEW_SESSION = "Start a new session so every change applies."


def find_uv() -> str | None:
    home = Path.home()
    for candidate in (shutil.which("uv"), home / ".local/bin/uv", home / ".cargo/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        if candidate and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def install_engine(vault: Vault) -> None:
    """Reinstall the engine in .bron/venv from System/Core/Engine. Raises RuntimeError with a plain reason."""
    uv = find_uv()
    if uv is None:
        raise RuntimeError("uv (the tool Bron uses to install its engine) wasn't found")
    venv = vault.bron_dir / "venv"
    for command in (
        [uv, "venv", "--quiet", "--allow-existing", "--python", "3.12", str(venv)],
        [uv, "pip", "install", "--quiet", "--python", str(venv / "bin" / "python"), "--reinstall-package", "bron-engine", str(vault.core / "Engine")],
    ):
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"the engine couldn't be installed ({exc.__class__.__name__})") from exc
        if done.returncode != 0:
            raise RuntimeError("the engine couldn't be installed: " + (done.stderr or done.stdout).strip()[-400:])


def after_update(vault: Vault, previous: str, tree: Path | None) -> tuple[int, str]:
    """Let the newly installed engine finish, in a fresh process."""
    command = [str(vault.bron_command), "_after-update", "--previous", previous]
    if tree is not None:
        command += ["--tree", str(tree)]
    try:
        done = subprocess.run(command, cwd=vault.root, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"The new version couldn't finish setting up ({exc.__class__.__name__})."
    return done.returncode, (done.stdout + done.stderr).strip()


def finish(vault: Vault, previous: str, tree: Path | None) -> int:
    """Run by the new engine: starting files, migrations, Obsidian, sync, health check. Prints what happened."""
    from .cli import _check, _sync
    from .migrations import apply_pending
    from .obsidian import BundleError, refresh_bundle
    from .setup import SetupError

    if tree is not None:
        copy_template(vault.root, tree / "template")
    try:
        for line in apply_pending(vault, previous, vault.version()):
            print(line)
    except SetupError as exc:
        print(f"A change to your setup that this version needs couldn't be made: {exc}")
        return 1
    try:
        for line in refresh_bundle(vault.root, vault.core):
            print(line)
    except BundleError as exc:
        print(f"Obsidian: {exc}")
    if _sync(vault, dry_run=False) != 0:
        return 1
    _check(vault)
    return 0


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backups(vault: Vault) -> list[Path]:
    """Core backups, oldest first."""
    if not vault.backups_dir.is_dir():
        return []
    found = []
    for path in vault.backups_dir.iterdir():
        match = _BACKUP.match(path.name)
        if match and path.is_dir():
            found.append(((match.group(2), int(match.group(3) or 0)), path))
    return [path for _, path in sorted(found)]


def backup_core(vault: Vault, *, stamp: str | None = None) -> Path:
    base = f"core-{vault.version()}-{stamp or _stamp()}"
    dest = vault.backups_dir / base
    n = 1
    while dest.exists():
        n += 1
        dest = vault.backups_dir / f"{base}-{n}"
    vault.backups_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(vault.core, dest, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    for old in backups(vault)[:-KEEP_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def _version_of(backup: Path) -> str:
    match = _BACKUP.match(backup.name)
    return match.group(1) if match else "?"


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-TAIL_LINES:])


def _restore(vault: Vault, backup: Path) -> str:
    """Put a backed-up System/Core back with its engine. Returns an extra note when the engine couldn't be reinstalled."""
    replace_core(vault.root, backup)
    try:
        install_engine(vault)
    except RuntimeError as exc:
        return f" Its engine couldn't be reinstalled ({exc}); run the install command again to repair it."
    try:
        subprocess.run([str(vault.bron_command), "sync"], cwd=vault.root, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def preview(vault: Vault, source) -> tuple[int, str]:
    current = vault.version()
    try:
        latest = source.latest()
        if latest is None:
            return 1, "Bron hasn't published a release yet."
        if not is_newer(latest, current):
            return 0, f"Bron is up to date (version {current})."
        notes = changes_between(source.changelog(latest), current, latest) or "(No release notes were found.)"
    except ReleaseError as exc:
        return 1, str(exc)
    return 0, (
        f"Bron {latest} is available (you have {current}). What's new:\n\n{notes}\n\n"
        "Updating keeps all your own files, and the current version is backed up first so it can be undone."
    )


def apply(vault: Vault, source) -> tuple[int, str]:
    current = vault.version()
    with locked(vault.state_dir / "update.json"):
        try:
            latest = source.latest()
        except ReleaseError as exc:
            return 1, str(exc)
        if latest is None:
            return 1, "Bron hasn't published a release yet."
        refresh = isinstance(source, ProjectFolder) and latest == current
        if not refresh and not is_newer(latest, current):
            return 0, f"Bron is up to date (version {current})."
        with tempfile.TemporaryDirectory(prefix="bron-update-") as work:
            try:
                tree = source.fetch(latest, Path(work))
            except ReleaseError as exc:
                return 1, str(exc)
            backup = backup_core(vault)
            try:
                replace_core(vault.root, tree / "core")
                install_engine(vault)
                code, output = after_update(vault, current, tree)
                if code != 0:
                    raise RuntimeError("the new version couldn't finish setting up:\n" + _tail(output))
            except Exception as exc:  # noqa: BLE001 - every failure puts the old version back
                note = _restore(vault, backup)
                return 1, f"The update to {latest} didn't finish ({exc}). Bron went back to version {current}.{note} Your own files were kept."
    if isinstance(source, ProjectFolder):
        write_source(vault.root, str(source.folder))
    if refresh:
        headline = f"Bron is already on the latest version ({current}); its setup was refreshed."
    else:
        headline = f"Updated Bron from version {current} to {latest}."
    return 0, f"{headline} Your own files were kept.\n{_tail(output)}\n{NEW_SESSION}"


def undo(vault: Vault) -> tuple[int, str]:
    with locked(vault.state_dir / "update.json"):
        found = backups(vault)
        if not found:
            return 1, "There's no earlier version of Bron to go back to."
        target = found[-1]
        current = vault.version()
        with tempfile.TemporaryDirectory(prefix="bron-undo-") as work:
            safety = Path(work) / "Core"
            shutil.copytree(vault.core, safety, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
            try:
                replace_core(vault.root, target)
                install_engine(vault)
                code, output = after_update(vault, current, None)
                if code != 0:
                    raise RuntimeError("the earlier version couldn't finish setting up:\n" + _tail(output))
            except Exception as exc:  # noqa: BLE001
                note = _restore(vault, safety)
                return 1, f"Going back didn't work ({exc}). Bron stayed on version {current}.{note}"
        shutil.rmtree(target, ignore_errors=True)
    return 0, f"Went back from version {current} to {_version_of(target)}. Your own files were kept.\n{_tail(output)}\n{NEW_SESSION}"
```

Note: `after_update` and `install_engine` are looked up as module attributes at call time (tests replace them), so call them by bare name inside this module as written — do not bind them to local names elsewhere.

- [ ] **Step 5: Wire the CLI**

In `core/Engine/bron/cli.py` `build_parser`, replace `sub.add_parser("update", ...)` with:

```python
    p_update = sub.add_parser("update", help="update Bron to the newest release (shows what's new first with --preview)")
    update_mode = p_update.add_mutually_exclusive_group()
    update_mode.add_argument("--preview", action="store_true", help="show what's new without changing anything")
    update_mode.add_argument("--undo", action="store_true", help="go back to the version before the last update")
    p_update.add_argument("--from", dest="from_folder", type=Path, help="update from a Bron project folder instead of GitHub (development)")
    p_after = sub.add_parser("_after-update", help=argparse.SUPPRESS)
    p_after.add_argument("--previous", required=True)
    p_after.add_argument("--tree", type=Path)
```

(add `from pathlib import Path` at the top). In `main`, replace the `update` branch with:

```python
    if args.command == "update":
        from . import update
        from .releases import select_source

        if args.undo:
            code, message = update.undo(vault)
        else:
            source = select_source(vault, args.from_folder)
            code, message = (update.preview if args.preview else update.apply)(vault, source)
        print(message)
        return code
    if args.command == "_after-update":
        from .update import finish

        return finish(vault, args.previous, args.tree)
```

- [ ] **Step 6: Rewrite the update skill**

`core/Skills/update/SKILL.md`:

```markdown
---
name: update
description: Update the Bron framework when the user asks Bron to update itself ("Bron, update yourself", "update Bron", "get the latest Bron"), or undo the last update ("undo the update", "go back to the previous Bron"). Shows what's new first and keeps all the user's own files.
---

# Update Bron

## Update
1. Run `.bron/bin/bron update --preview`.
   - "up to date": tell the user in one line; stop.
   - A problem (for example "GitHub didn't answer"): say it in plain words; stop.
2. Otherwise summarise what's new in a few short bullets, in plain words, and ask: "Update now?" Wait for a yes.
3. After a yes, run `.bron/bin/bron update`. It can take a few minutes.
4. Report the result in plain words:
   - the first line says which version Bron moved to;
   - mention any problem the health check lists at the end, and offer to fix it;
   - say their own files were kept, that "undo the update" goes back, and that a new session is needed for every change to apply.
5. If it says the update didn't finish, explain the reason it gives in simple terms. Bron has already gone back to the previous version by itself. Don't retry more than once.

## Undo the update
Run `.bron/bin/bron update --undo` and report its first line in plain words, plus that a new session is needed.

Never edit `System/Core/` or the generated folders yourself to "finish" an update.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_update.py tests/test_migrations.py -q` → PASS; full suite → all pass (also re-check `tests/test_setup_content.py` / skill-content tests that read `core/Skills/update/SKILL.md`, if any).

Then one real end-to-end check (needs uv; leaves nothing behind):

```bash
V="$TMPDIR/bron update check"
scripts/dev-vault.sh "$V"
"$V/.bron/bin/bron" update --from "$PWD"
"$V/.bron/bin/bron" version
rm -rf "$V"
```

Expected: "Bron is already on the latest version (…); its setup was refreshed." and the version printed. Quote the output in the report.

- [ ] **Step 8: Commit**

```bash
git add core/Engine/bron/migrations core/Engine/bron/update.py core/Engine/bron/cli.py core/Skills/update/SKILL.md tests/test_update.py tests/test_migrations.py
git commit -m "bron update: GitHub releases with a preview, a backup, automatic rollback and undo; migrations registry"
```

---

### Task 7: The daily "new version" line (`bron/update_check.py`, settings, briefing)

**Files:**
- Create: `core/Engine/bron/update_check.py`
- Modify: `core/Engine/bron/model.py` (`Settings.update_check: bool = True`)
- Modify: `core/Engine/bron/loader.py` (`_settings`: read `update_check`)
- Modify: `core/Engine/bron/briefing.py` (add the line, not for ticket runs)
- Modify: `template/System/Settings.md` (add `update_check: true` and its explanation)
- Test: `tests/test_update_check.py`

**Interfaces:**
- Consumes: `releases.select_source(vault, timeout=2)`, `GitHubReleases`, `LocalReleases`, `ProjectFolder`, `ReleaseError`, `is_newer` (Task 1); `statefile.read_json`, `write_json`.
- Produces: `update_check.update_notice(vault: Vault, settings: Settings, *, now: float | None = None) -> str` — the user-facing line or `""`. Constants `CACHE = "update-check.json"`, `DAY = 86400`, `TIMEOUT = 2`.

- [ ] **Step 1: Write the failing tests**

`tests/test_update_check.py`:

```python
import json

from bron import releases
from bron.briefing import build_briefing
from bron.loader import load
from bron.update_check import DAY, update_notice
from releasekit import write_tags
from vaultkit import set_meta

NOW = 1_800_000_000.0


def settings(vault):
    return load(vault).settings


def offer(tmp_path, monkeypatch, versions):
    folder = tmp_path / "releases"
    write_tags(folder, versions)
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    return folder


def test_newer_version_is_announced(vault, tmp_path, monkeypatch):
    offer(tmp_path, monkeypatch, ["9.0.0"])
    assert update_notice(vault, settings(vault), now=NOW) == "Bron 9.0.0 is available. Say 'update yourself' to see what's new."


def test_nothing_when_up_to_date(vault, tmp_path, monkeypatch):
    offer(tmp_path, monkeypatch, [vault.version()])
    assert update_notice(vault, settings(vault), now=NOW) == ""


def test_checked_at_most_once_a_day(vault, tmp_path, monkeypatch):
    folder = offer(tmp_path, monkeypatch, ["9.0.0"])
    update_notice(vault, settings(vault), now=NOW)
    (folder / "tags.json").unlink()
    assert "9.0.0" in update_notice(vault, settings(vault), now=NOW + DAY - 60)
    write_tags(folder, ["9.1.0"])
    assert "9.1.0" in update_notice(vault, settings(vault), now=NOW + DAY + 1)


def test_offline_is_silent_and_cached(vault):
    assert update_notice(vault, settings(vault), now=NOW) == ""  # conftest's empty release folder = offline
    cache = json.loads((vault.state_dir / "update-check.json").read_text())
    assert cache["checked_at"] == NOW


def test_turned_off_in_settings(vault, tmp_path, monkeypatch):
    offer(tmp_path, monkeypatch, ["9.0.0"])
    set_meta(vault.settings_file, update_check=False)
    assert update_notice(vault, settings(vault), now=NOW) == ""
    assert not (vault.state_dir / "update-check.json").exists()


def test_not_a_true_or_false_setting_is_a_warning(vault):
    set_meta(vault.settings_file, update_check="sometimes")
    cfg = load(vault)
    assert cfg.settings.update_check is True
    assert any(i.level == "warning" and "update_check" in i.message for i in cfg.issues)


def test_dev_vaults_following_a_project_folder_are_not_checked(vault, tmp_path, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    vault.bron_dir.mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "source").write_text(f"{tmp_path}\n")
    assert update_notice(vault, settings(vault), now=NOW) == ""


def test_github_check_uses_a_two_second_limit(vault, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    seen = []

    def fake_curl(url, *, timeout, out=None):
        seen.append(timeout)
        raise releases.ReleaseError("GitHub didn't answer; try again later.")

    monkeypatch.setattr(releases, "_curl", fake_curl)
    assert update_notice(vault, settings(vault), now=NOW) == ""
    assert seen == [2]


def test_briefing_mentions_it(vault, tmp_path, monkeypatch):
    offer(tmp_path, monkeypatch, ["9.0.0"])
    assert "Bron 9.0.0 is available." in build_briefing(vault, cli="claude")


def test_ticket_runs_dont_mention_it(vault, tmp_path, monkeypatch):
    offer(tmp_path, monkeypatch, ["9.0.0"])
    monkeypatch.setenv("BRON_TICKET", "T-1")
    assert "is available" not in build_briefing(vault, cli="claude")
```

(If `vaultkit.set_meta` can't write a bool or the briefing needs a user name to avoid the first-run text, keep the assertions and adapt only the setup lines.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_update_check.py -q`
Expected: FAIL — `No module named 'bron.update_check'`.

- [ ] **Step 3: Write the implementation**

`core/Engine/bron/update_check.py`:

```python
"""The once-a-day "a new Bron is available" line in the session briefing. Never slow, never noisy."""
from __future__ import annotations

import time

from .model import Settings
from .releases import ProjectFolder, ReleaseError, is_newer, select_source
from .statefile import read_json, write_json
from .vault import Vault

CACHE = "update-check.json"
DAY = 24 * 3600
TIMEOUT = 2


def update_notice(vault: Vault, settings: Settings, *, now: float | None = None) -> str:
    if not settings.update_check:
        return ""
    source = select_source(vault, timeout=TIMEOUT)
    if isinstance(source, ProjectFolder):
        return ""  # a development vault follows a project folder; `bron update` handles it
    now = time.time() if now is None else now
    path = vault.state_dir / CACHE
    cache = read_json(path, {})
    if not isinstance(cache, dict):
        cache = {}
    latest = cache.get("latest")
    checked = cache.get("checked_at", 0)
    if not isinstance(checked, (int, float)) or now - checked >= DAY:
        try:
            latest = source.latest()
        except ReleaseError:
            pass  # offline or GitHub busy: stay quiet, try again tomorrow
        write_json(path, {"checked_at": now, "latest": latest})
    if isinstance(latest, str) and is_newer(latest, vault.version()):
        return f"Bron {latest} is available. Say 'update yourself' to see what's new."
    return ""
```

`core/Engine/bron/model.py` — in `Settings`, after `max_minutes: int = 30` add `update_check: bool = True`.

`core/Engine/bron/loader.py` — in `_settings`, after the `runner` block (before `groups = ...`):

```python
    check = doc.meta.get("update_check", True)
    if isinstance(check, bool):
        settings.update_check = check
    else:
        f.problem("field.type", "'update_check' should be true or false", level="warning")
```

`core/Engine/bron/briefing.py` — inside `if not ticket_run:`, after the approvals notice block and before the routines block:

```python
        try:
            from .update_check import update_notice

            available = update_notice(vault, settings)
        except Exception:  # noqa: BLE001 - never fails the briefing
            available = ""
        if available:
            lines += ["", available + " Mention it to the user in one line."]
```

`template/System/Settings.md` — add `update_check: true` after the `runner:` block in the frontmatter, and in the list below add:
`- \`update_check\`: Bron checks once a day whether a new version is out and tells you; set it to false to stop that.`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_update_check.py -q` → PASS; full suite → all pass (briefing tests run with the conftest's empty release folder, so they see no line and stay unchanged).

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/update_check.py core/Engine/bron/model.py core/Engine/bron/loader.py core/Engine/bron/briefing.py template/System/Settings.md tests/test_update_check.py
git commit -m "Tell the user once a day when a new Bron is out; update_check: false turns it off"
```

---

### Task 8: Releases, changelog and docs

**Files:**
- Create: `CHANGELOG.md`, `scripts/release.sh` (executable), `core/Manual/updates.md`
- Modify: `core/Manual/index.md` (add the page; update the "Updating Bron" line), `README.md` (install, update, release, bundle sections)
- Modify: `tests/test_vault.py:39`, `tests/test_prompts.py:20`, `tests/test_cli.py:57` (read the version from `core/VERSION`)
- Test: `tests/test_release_script.py`

**Interfaces:**
- Consumes: everything above (docs only describe it).
- Produces: `scripts/release.sh <version>` — refuses unless the version looks like `X.Y.Z`, tracked files are clean, the version is newer than the newest `v*` tag, and `CHANGELOG.md` has `## <version>`; bumps `core/VERSION`, `core/Engine/pyproject.toml`, `core/Engine/bron/__init__.py`, runs `uv lock` when `core/Engine/uv.lock` exists, runs the tests (`BRON_RELEASE_TEST_CMD`, default `uv run --project core/Engine pytest tests -q`), commits "Release <version>" (plus the line in `BRON_COMMIT_TRAILER` when set) and tags `v<version>`. Never pushes.

- [ ] **Step 1: Write the failing tests**

`tests/test_release_script.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env={**os.environ, **GIT_ENV}, check=True).stdout


def fake_repo(tmp_path, changelog="# Changelog\n\n## 0.5.0\n- New.\n"):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "core" / "Engine" / "bron").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "release.sh", repo / "scripts" / "release.sh")
    (repo / "core" / "VERSION").write_text("0.4.1\n")
    (repo / "core" / "Engine" / "pyproject.toml").write_text('[project]\nname = "bron-engine"\nversion = "0.4.1"\ndependencies = ["pyyaml>=6.0"]\n')
    (repo / "core" / "Engine" / "bron" / "__init__.py").write_text('"""Bron."""\n\n__version__ = "0.4.1"\n')
    (repo / "CHANGELOG.md").write_text(changelog)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "start")
    git(repo, "tag", "v0.4.1")
    return repo


def release(repo, version, test_cmd="true"):
    env = {**os.environ, **GIT_ENV, "BRON_RELEASE_TEST_CMD": test_cmd, "BRON_COMMIT_TRAILER": "Co-Authored-By: Someone <someone@example.invalid>"}
    done = subprocess.run(["bash", "scripts/release.sh", version], cwd=repo, capture_output=True, text=True, env=env)
    return done.returncode, done.stdout + done.stderr


def test_release_bumps_commits_and_tags(tmp_path):
    repo = fake_repo(tmp_path)
    code, out = release(repo, "0.5.0")
    assert code == 0, out
    assert (repo / "core" / "VERSION").read_text() == "0.5.0\n"
    assert 'version = "0.5.0"' in (repo / "core" / "Engine" / "pyproject.toml").read_text()
    assert 'pyyaml>=6.0' in (repo / "core" / "Engine" / "pyproject.toml").read_text()
    assert '__version__ = "0.5.0"' in (repo / "core" / "Engine" / "bron" / "__init__.py").read_text()
    assert "v0.5.0" in git(repo, "tag").split()
    message = git(repo, "log", "-1", "--format=%B")
    assert message.startswith("Release 0.5.0") and "Co-Authored-By: Someone" in message
    assert "git push origin main" in out


def test_refuses_a_version_that_isnt_newer(tmp_path):
    repo = fake_repo(tmp_path, "# Changelog\n\n## 0.4.0\n- Old.\n")
    code, out = release(repo, "0.4.0")
    assert code == 1
    assert "isn't newer" in out


def test_refuses_without_a_changelog_section(tmp_path):
    repo = fake_repo(tmp_path)
    code, out = release(repo, "0.6.0")
    assert code == 1
    assert "CHANGELOG.md" in out


def test_refuses_uncommitted_changes(tmp_path):
    repo = fake_repo(tmp_path)
    (repo / "core" / "VERSION").write_text("0.4.9\n")
    code, out = release(repo, "0.5.0")
    assert code == 1
    assert "Commit" in out


def test_refuses_a_badly_written_version(tmp_path):
    code, out = release(fake_repo(tmp_path), "v0.5")
    assert code == 1
    assert "0.5.0" in out


def test_failing_tests_release_nothing(tmp_path):
    repo = fake_repo(tmp_path)
    code, out = release(repo, "0.5.0", test_cmd="false")
    assert code == 1
    assert "nothing was released" in out.lower()
    assert (repo / "core" / "VERSION").read_text() == "0.4.1\n"
    assert "v0.5.0" not in git(repo, "tag").split()


def test_the_real_changelog_has_the_current_version():
    version = (REPO / "core" / "VERSION").read_text().strip()
    text = (REPO / "CHANGELOG.md").read_text()
    assert f"## {version}" in text
    assert "## 0.5.0" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project core/Engine pytest tests/test_release_script.py -q`
Expected: FAIL — `scripts/release.sh` and `CHANGELOG.md` don't exist.

- [ ] **Step 3: Write `scripts/release.sh`**

```bash
#!/usr/bin/env bash
# Maintainer: make a Bron release.  Usage: scripts/release.sh <version>   (for example 0.5.0)
# Checks, bumps the version everywhere, runs the tests, commits "Release <version>" and tags v<version>.
# It never pushes. Afterwards: git push origin main && git push origin v<version>
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
VERSION="${1:-}"
FILES="core/VERSION core/Engine/pyproject.toml core/Engine/bron/__init__.py"

stop() { printf '%s\n' "$*" >&2; exit 1; }
order() { sort -t. -k1,1n -k2,2n -k3,3n; }

printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || stop "The version must look like 0.5.0."
[ -z "$(git status --porcelain --untracked-files=no)" ] || stop "Commit or stash your changes first."
latest="$(git tag -l 'v*' | sed 's/^v//' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | order | tail -n 1 || true)"
if [ -n "$latest" ]; then
  top="$(printf '%s\n%s\n' "$latest" "$VERSION" | order | tail -n 1)"
  if [ "$top" != "$VERSION" ] || [ "$latest" = "$VERSION" ]; then
    stop "Version $VERSION isn't newer than the latest release ($latest)."
  fi
fi
grep -Eq "^## $VERSION( |$)" CHANGELOG.md || stop "CHANGELOG.md has no section '## $VERSION'. Add one first."

printf '%s\n' "$VERSION" > core/VERSION
sed -i '' -E "s/^version = \"[0-9]+\.[0-9]+\.[0-9]+\"/version = \"$VERSION\"/" core/Engine/pyproject.toml
sed -i '' -E "s/^__version__ = \"[0-9]+\.[0-9]+\.[0-9]+\"/__version__ = \"$VERSION\"/" core/Engine/bron/__init__.py
if [ -f core/Engine/uv.lock ]; then
  uv lock --quiet --project core/Engine
  FILES="$FILES core/Engine/uv.lock"
fi

if ! bash -c "${BRON_RELEASE_TEST_CMD:-uv run --project core/Engine pytest tests -q}"; then
  # shellcheck disable=SC2086
  git checkout -q -- $FILES
  stop "The tests failed, so nothing was released."
fi

MESSAGE="Release $VERSION"
if [ -n "${BRON_COMMIT_TRAILER:-}" ]; then
  MESSAGE="$(printf '%s\n\n%s' "$MESSAGE" "$BRON_COMMIT_TRAILER")"
fi
# shellcheck disable=SC2086
git add $FILES
git commit -q -m "$MESSAGE"
git tag -a "v$VERSION" -m "Bron $VERSION"
echo "Released $VERSION (tag v$VERSION). Publish it with: git push origin main && git push origin v$VERSION"
```

`chmod +x scripts/release.sh`.

- [ ] **Step 4: Write `CHANGELOG.md`**

```markdown
# Changelog

What changed in each version of Bron, newest first. Bron shows the new sections when you ask it to update itself.

## 0.5.0
- Install Bron with one line pasted into Terminal, into the folder you choose (or `~/Documents/Bron`). Running it again repairs a vault and never changes your files.
- New vaults come with Bron's Obsidian look: the Bron theme, Bron Terminal, Bron Workspace and a few helpful plugins. Your own Obsidian settings are always kept.
- "Bron, update yourself" now gets the newest release from GitHub: Bron shows what's new and waits for your yes, backs up the current version, goes back by itself if anything fails, and "undo the update" returns to the previous version.
- Once a day Bron tells you when a new version is out. Set `update_check: false` in System/Settings.md to stop that.
- A `bron` command that works from any folder inside your vault.
- Bron Terminal 0.6.0 ships with Bron: a standalone terminal for Claude Code and Codex inside Obsidian (no other terminal plugin needed).
- Bron is open source under the MIT licence.

## 0.4.1
- Safer connector setup: more kinds of passwords and keys are refused, harmless options are allowed, and programs whose path has spaces work.
- Setup changes stay correct when you click "don't ask again" while Bron is making a change.
- Bringing back a retired agent works even when one of its helpers was removed.

## 0.4.0
- Setup by conversation: first-run onboarding, and creating, editing and retiring agents, projects, routines, skills and connectors. Every change is previewed in plain words before it's made.
- Bron uses Opus 5.5 by default.

## 0.3.1
- Picking an agent from the @ list (for example `@"cfo (agent)"`) now reaches that agent.
- Codex agents can use their connectors in background work without being stopped by approval prompts.

## 0.3.0
- @-mention an agent to bring it into the conversation.
- Routines: repeating work per period, with checklists and due dates.
- "Don't ask again" approvals are saved and apply in both Claude Code and Codex.

## 0.2.3
- Versions 0.2.0 to 0.2.3: much faster handoffs between agents, quick questions answered straight in the chat, and results always delivered back to you.

## 0.1.0
- The first version: agents defined once in plain markdown, kept in sync across Claude Code and Codex, tickets for handing work between agents, and a health check.
```

- [ ] **Step 5: Write `core/Manual/updates.md` and update the index**

`core/Manual/updates.md`:

```markdown
# Installing and updating Bron

## Installing
Paste into Terminal (macOS):

    curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash

It installs into the folder you're in, or into a folder you name: `… | bash -s -- "<folder>"`. In your home folder or a system folder it asks where to go instead (default `~/Documents/Bron`). Running it again on a Bron vault repairs it; your files are never overwritten.

It also adds a `bron` command that works from any folder inside a vault (`~/.local/bin/bron`), and, if you use Codex, marks the vault as trusted there.

## Updating
Say "Bron, update yourself". Bron shows what's new and waits for your yes. Or run:

- `.bron/bin/bron update --preview`: what's new, without changing anything.
- `.bron/bin/bron update`: update now.
- `.bron/bin/bron update --undo`: go back to the version before the last update.

Before updating, Bron backs up `System/Core` to `.bron/backups/core-<version>-<date>/` (the last 3 are kept). If anything fails, it goes back by itself. Your own files (everything in `System/` except `System/Core/`, and all your notes) are never touched; Obsidian keeps your settings, and only Bron's theme and plugin code are refreshed.

Once a day, at the start of a session, Bron checks whether a new version is out and tells you. To stop that, set `update_check: false` in `System/Settings.md`.

A development vault made with `scripts/dev-vault.sh` follows its Bron project folder instead of GitHub (`bron update --from <folder>` switches folders).
```

In `core/Manual/index.md`: add the table row `| [updates.md](updates.md) | Installing Bron, updating it, undoing an update, and the daily new-version check |` after the `setup.md` row, and change the "Updating Bron" bullet to: `- **Updating Bron:** say "Bron, update yourself". Bron shows what's new first, keeps your files, and can undo the update (see updates.md).`

- [ ] **Step 6: Update `README.md`**

Replace the opening sections so the README has, in order: the existing one-paragraph intro; an **Install** section (the curl line, the folder variant, one sentence on what it sets up, "Then open the folder in Claude Code or Codex (desktop app or terminal), or in Obsidian, and say hi to Bron."); an **Updating** section (one line: say "Bron, update yourself"; link `core/Manual/updates.md`); the existing **Development** section plus two bullets — `Release: scripts/release.sh <version> (needs a CHANGELOG.md section first; push the commit and tag afterwards)` and `Obsidian bundle: python3 scripts/export-obsidian.py <your vault> refreshes core/Obsidian and template/.obsidian from your own vault, without personal state`; the existing **Bron Terminal** section (replace "`scripts/dev-vault.sh` installs it without Termy" with "Bron installs it into every vault; `scripts/install-terminal.py <vault>` installs it on its own"); a **Licence** line: MIT (Ziggo AI); bundled third-party Obsidian plugins keep their own licences (`core/Obsidian/THIRD-PARTY-NOTICES.md`).

- [ ] **Step 7: Make version tests follow `core/VERSION`**

In `tests/test_vault.py:39`, `tests/test_prompts.py:20` and `tests/test_cli.py:57`, replace the literal `0.4.1` with the version read from the repo: add near the imports `VERSION = (Path(__file__).resolve().parents[1] / "core" / "VERSION").read_text().strip()` (import `Path` if needed) and use `VERSION` / `f"Framework version {VERSION}."` / `f"{VERSION}\n"`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run --project core/Engine pytest tests/test_release_script.py -q` → PASS; full suite → all pass. Also `bash -n scripts/release.sh`, and `shellcheck scripts/release.sh install.sh` if available.

- [ ] **Step 9: Commit**

```bash
git add CHANGELOG.md scripts/release.sh core/Manual/updates.md core/Manual/index.md README.md tests/test_release_script.py tests/test_vault.py tests/test_prompts.py tests/test_cli.py
git commit -m "Releases: changelog, release script, install and update manual page, README"
```

---

## After the build (controller, not a task)

1. Final whole-branch review, fix wave, merge to `main` (with the user's yes).
2. On `main`: `BRON_COMMIT_TRAILER="Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" scripts/release.sh 0.5.0` → commit "Release 0.5.0" and tag `v0.5.0`.
3. Ask the user to push `main` and the tag (or push with their yes).
4. Live check once public: `curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash -s -- "$TMPDIR/bron-live-install"` → "Your Bron vault is ready at …"; then `"$TMPDIR/bron-live-install/.bron/bin/bron" update --preview` → "Bron is up to date (version 0.5.0)."; delete the folder.
5. The maintainer's test vault (made by `dev-vault.sh`, still on 0.4.1) updates with "Bron, update yourself" as before — its 0.4.1 engine runs the new `scripts/dev-vault.sh`.
