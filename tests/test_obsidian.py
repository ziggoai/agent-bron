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
