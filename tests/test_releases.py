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
