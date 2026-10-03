"""Standalone terminal release and repeat-install acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('install_terminal', ROOT / 'core/Plugins/install_terminal.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
SOURCE = ROOT / 'core/Plugins/bron-terminal'


def test_clean_install_is_complete_without_termy(tmp_path):
    target = installer.install(tmp_path, SOURCE)
    assert json.loads((target / 'manifest.json').read_text())['id'] == 'bron-terminal'
    assert json.loads((tmp_path / '.obsidian/community-plugins.json').read_text()) == ['bron-terminal']
    assert not (target.parent / 'termy').exists()
    for name, checksum in json.loads((target / 'checksums.json').read_text()).items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == checksum
    assert (target / 'bin/pty-host-darwin').stat().st_mode & 0o111 == 0o111
    assert not (target / 'data.json').exists()


def test_upgrade_preserves_settings_other_plugins_and_backup(tmp_path):
    target = installer.install(tmp_path, SOURCE)
    settings = '{"shellPath":"/bin/bash","provider":"claude"}'
    (target / 'data.json').write_text(settings)
    (target / 'main.js').write_text('old build')
    enabled = tmp_path / '.obsidian/community-plugins.json'
    enabled.write_text('["existing-plugin", "bron-terminal"]')
    installer.install(tmp_path, SOURCE)
    assert (target / 'data.json').read_text() == settings
    assert json.loads(enabled.read_text()) == ['existing-plugin', 'bron-terminal']
    backups = list((tmp_path / '.bron/backups').iterdir())
    assert len(backups) == 1
    assert (backups[0] / 'main.js').read_text() == 'old build'
    assert (backups[0] / 'data.json').read_text() == settings


def test_corrupt_release_rejected_before_modifying_vault(tmp_path):
    import shutil
    source = tmp_path / 'release'
    shutil.copytree(SOURCE, source)
    (source / 'main.js').write_text('corrupt')
    vault = tmp_path / 'vault'
    with pytest.raises(ValueError, match='checksum'):
        installer.install(vault, source)
    assert not vault.exists()


def test_invalid_plugin_list_is_not_overwritten(tmp_path):
    config = tmp_path / '.obsidian'
    config.mkdir()
    (config / 'community-plugins.json').write_text('{}')
    with pytest.raises(ValueError, match='Invalid community'):
        installer.install(tmp_path, SOURCE)
    assert not (config / 'plugins').exists()
    assert (config / 'community-plugins.json').read_text() == '{}'


def test_install_does_not_follow_payload_symlinks(tmp_path):
    target = installer.install(tmp_path, SOURCE)
    outside = tmp_path / 'outside'
    outside.write_text('keep')
    (target / 'main.js').unlink()
    (target / 'main.js').symlink_to(outside)
    installer.install(tmp_path, SOURCE)
    assert outside.read_text() == 'keep'
    assert not (target / 'main.js').is_symlink()


def test_no_enable_preserves_disabled_state(tmp_path):
    installer.install(tmp_path, SOURCE, enable=False)
    assert not (tmp_path / '.obsidian/community-plugins.json').exists()


def test_reinstall_of_identical_plugin_is_skipped(tmp_path):
    target = installer.install(tmp_path, SOURCE)
    before = (target / 'main.js').stat().st_ino
    again = installer.install(tmp_path, SOURCE)
    assert again == target
    assert (target / 'main.js').stat().st_ino == before
    assert not (tmp_path / '.bron/backups').exists()


def test_skipped_install_still_enables_plugin(tmp_path):
    installer.install(tmp_path, SOURCE, enable=False)
    installer.install(tmp_path, SOURCE)
    assert json.loads((tmp_path / '.obsidian/community-plugins.json').read_text()) == ['bron-terminal']
    assert not (tmp_path / '.bron/backups').exists()


def test_only_three_newest_backups_are_kept(tmp_path):
    target = installer.install(tmp_path, SOURCE)
    for i in range(5):
        (target / 'main.js').write_text(f'build {i}')
        installer.install(tmp_path, SOURCE)
    backups = sorted((tmp_path / '.bron/backups').iterdir(), key=lambda p: int(p.name.split('-')[1]))
    assert len(backups) == 3
    assert [(b / 'main.js').read_text() for b in backups] == ['build 2', 'build 3', 'build 4']


def test_prune_ignores_unrelated_backup_entries(tmp_path):
    backups = tmp_path / '.bron/backups'
    backups.mkdir(parents=True)
    (backups / 'other-1').mkdir()
    installer.install(tmp_path, SOURCE)
    assert (backups / 'other-1').exists()
