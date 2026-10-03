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
