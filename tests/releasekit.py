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
