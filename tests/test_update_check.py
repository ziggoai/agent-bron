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
