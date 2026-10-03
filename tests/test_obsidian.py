import json
import shutil
from pathlib import Path

import pytest

from bron.obsidian import RESTART_NOTE, THEME_TIP, BundleError, install_bundle, refresh_bundle

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
    assert notes == [THEME_TIP, RESTART_NOTE]
    assert (config(vault) / "appearance.json").read_text() == '{"cssTheme": "Minimal"}'
    assert enabled(vault) == ["dataview", "bron-terminal", "bron-workspace"]
    assert (config(vault) / "plugins" / "colored-tags" / "data.json").read_text() == '{"mine": true}'
    assert (config(vault) / "plugins" / "colored-tags" / "main.js").read_text() != "old code"
    assert not (config(vault) / "app.json").exists()


def test_no_theme_tip_when_bron_is_already_the_theme(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    config(vault).mkdir()
    (config(vault) / "appearance.json").write_text('{"cssTheme": "Bron"}')
    assert install_bundle(vault.root, vault.core, TEMPLATE_CONFIG) == [RESTART_NOTE]


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


def plant(vault, plugin: str, version: str | None, code: str = "my own build") -> Path:
    folder = config(vault) / "plugins" / plugin
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"id": plugin} if version is None else {"id": plugin, "version": version}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "main.js").write_text(code)
    return folder


def test_a_newer_installed_plugin_is_never_replaced(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    folder = plant(vault, "colored-tags", "99.0.0")
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert (folder / "main.js").read_text() == "my own build"
    assert json.loads((folder / "manifest.json").read_text())["version"] == "99.0.0"
    refresh_bundle(vault.root, vault.core)
    assert (folder / "main.js").read_text() == "my own build"


def test_a_newer_installed_theme_is_never_replaced(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    theme = config(vault) / "themes" / "Bron"
    theme.mkdir(parents=True)
    (theme / "manifest.json").write_text('{"name": "Bron", "version": "99.1.0"}')
    (theme / "theme.css").write_text("/* mine */")
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    refresh_bundle(vault.root, vault.core)
    assert (theme / "theme.css").read_text() == "/* mine */"


@pytest.mark.parametrize("version", ["0.0.1", None, "not a version"])
def test_an_older_or_unknown_plugin_version_is_replaced(vault, version):
    shutil.rmtree(config(vault), ignore_errors=True)
    folder = plant(vault, "colored-tags", version)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    bundled = vault.core / "Obsidian" / "plugins" / "colored-tags"
    assert (folder / "main.js").read_bytes() == (bundled / "main.js").read_bytes()
    plant(vault, "colored-tags", version)
    refresh_bundle(vault.root, vault.core)
    assert (folder / "main.js").read_bytes() == (bundled / "main.js").read_bytes()


def test_versions_compare_as_numbers():
    from bron.obsidian import _newer

    assert _newer("1.10.0", "1.9.9")
    assert not _newer("1.9.9", "1.10.0")
    assert not _newer("1.2", "1.2.0")
    assert _newer("1.2.0.1", "1.2")
    assert not _newer(None, "1.0.0") and not _newer("x", "1.0.0")


def test_obsidian_sync_starts_off():
    assert json.loads((TEMPLATE_CONFIG / "core-plugins.json").read_text())["sync"] is False


def test_fresh_install_gets_no_restart_note(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    assert RESTART_NOTE not in install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)


def test_existing_obsidian_with_an_older_plugin_gets_the_restart_note(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    (config(vault) / "plugins" / "colored-tags").mkdir(parents=True)
    (config(vault) / "plugins" / "colored-tags" / "main.js").write_text("old code")
    notes = install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert notes == [THEME_TIP, RESTART_NOTE]


def test_installing_again_with_nothing_changed_gets_no_restart_note(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert RESTART_NOTE not in install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)


def test_refresh_with_a_changed_plugin_gives_the_restart_note(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    (config(vault) / "plugins" / "colored-tags" / "main.js").write_text("old code")
    assert refresh_bundle(vault.root, vault.core) == [RESTART_NOTE]


def test_refresh_with_nothing_changed_gives_no_note(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    assert refresh_bundle(vault.root, vault.core) == []


def test_a_users_own_plugin_settings_never_trigger_the_note(vault):
    shutil.rmtree(config(vault), ignore_errors=True)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    (config(vault) / "plugins" / "colored-tags" / "data.json").write_text('{"mine": 1}')
    assert refresh_bundle(vault.root, vault.core) == []


def test_refresh_that_fails_after_changing_files_still_gives_the_restart_note(vault, monkeypatch):
    from bron import obsidian

    shutil.rmtree(config(vault), ignore_errors=True)
    install_bundle(vault.root, vault.core, TEMPLATE_CONFIG)
    (config(vault) / "plugins" / "colored-tags" / "main.js").write_text("old code")

    def broken(*args, **kwargs):
        raise BundleError("Bron Terminal couldn't be installed (disk full).")

    monkeypatch.setattr(obsidian, "_terminal", broken)
    with pytest.raises(BundleError) as caught:
        refresh_bundle(vault.root, vault.core)
    assert RESTART_NOTE in str(caught.value)
