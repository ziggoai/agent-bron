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
