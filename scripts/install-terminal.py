#!/usr/bin/env python3
"""Install the bundled Bron Terminal, preserving settings and backing up upgrades."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

KEEP_BACKUPS = 3

FILES = {'main.js', 'manifest.json', 'styles.css', 'THIRD-PARTY-NOTICES.txt', 'bin/pty-host-darwin'}


def _already_current(target: Path, hashes: dict) -> bool:
    """True when the installed plugin matches the payload, byte for byte."""
    try:
        if json.loads((target / 'checksums.json').read_text()) != hashes:
            return False
        for name, expected in hashes.items():
            path = target / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
    except (OSError, ValueError):
        return False
    return True


def _prune_backups(backups: Path) -> None:
    def stamp(path: Path) -> int:
        try:
            return int(path.name[len('terminal-'):])
        except ValueError:
            return -1
    found = sorted((p for p in backups.glob('terminal-*') if p.is_dir()), key=stamp)
    for old in found[:-KEEP_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)


def _enable(config: Path, enabled_path: Path, enabled: list) -> None:
    if 'bron-terminal' in enabled:
        return
    enabled.append('bron-terminal')
    fd, tmp = tempfile.mkstemp(prefix='.community-plugins-', dir=config)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(enabled, stream, indent=2)
            stream.write('\n')
        os.replace(tmp, enabled_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def install(vault: Path, source: Path, enable: bool = True) -> Path:
    hashes = json.loads((source / 'checksums.json').read_text())
    if set(hashes) != FILES:
        raise ValueError('Incomplete terminal release manifest')
    for name, expected in hashes.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Terminal release checksum mismatch: {name}')
    if json.loads((source / 'manifest.json').read_text())['id'] != 'bron-terminal':
        raise ValueError('Unexpected plugin identity')
    config = vault / '.obsidian'
    target = config / 'plugins' / 'bron-terminal'
    if target.is_symlink():
        raise ValueError('Refusing to replace a symlinked plugin directory')
    enabled_path = config / 'community-plugins.json'
    enabled = json.loads(enabled_path.read_text()) if enabled_path.exists() else []
    if not isinstance(enabled, list) or any(not isinstance(item, str) for item in enabled):
        raise ValueError('Invalid community-plugins.json; existing configuration was preserved')
    if target.exists() and _already_current(target, hashes):
        if enable:
            _enable(config, enabled_path, enabled)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.bron-terminal-', dir=target.parent))
    backup = None
    try:
        if target.exists():
            shutil.copytree(target, stage, dirs_exist_ok=True, symlinks=True)
        if (stage / 'bin').is_symlink():
            (stage / 'bin').unlink()
        for name in [*FILES, 'checksums.json']:
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Do not follow an old payload symlink when replacing release files.
            if dest.is_symlink():
                dest.unlink()
            shutil.copy2(source / name, dest)
        (stage / 'bin/pty-host-darwin').chmod(0o755)
        if target.exists():
            backup = vault / '.bron' / 'backups' / f'terminal-{time.time_ns()}'
            backup.parent.mkdir(parents=True, exist_ok=True)
            target.rename(backup)
        try:
            stage.rename(target)
        except BaseException:
            if backup is not None:
                backup.rename(target)
            raise
        if backup is not None:
            _prune_backups(backup.parent)
        if enable:
            _enable(config, enabled_path, enabled)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vault', type=Path)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'core/Plugins/bron-terminal')
    parser.add_argument('--no-enable', action='store_true')
    args = parser.parse_args()
    target = install(args.vault.resolve(), args.source.resolve(), not args.no_enable)
    print(f'Installed Bron Terminal: {target}')
    print('Open the vault and enable community plugins if requested. Existing sessions use their current version until the plugin is reloaded.')
