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
