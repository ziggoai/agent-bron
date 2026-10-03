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
    core_plugins["sync"] = False  # Obsidian Sync is a paid service the user switches on themselves
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
