"""Setting up a vault from a Bron release folder. Used by install.sh, scripts/dev-vault.sh and `bron update`.

Run as: python -m bron.install <vault> --tree <release folder> --source <github|project folder> [--no-home]
(the engine's venv in <vault>/.bron/venv must already exist; install.sh and dev-vault.sh create it).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import tomllib
from pathlib import Path

from .releases import SOURCE_FILE

CORE_IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", ".pytest_cache", ".DS_Store")
SHIM = """#!/bin/sh
VAULT="$(cd "$(dirname "$0")/../.." && pwd)"
export BRON_VAULT="$VAULT"
exec "$VAULT/.bron/venv/bin/python" -m bron "$@"
"""
LAUNCHER_MARK = "installed by Bron's installer"
LAUNCHER = f"""#!/bin/sh
# Bron: runs the bron command of the vault you're in ({LAUNCHER_MARK}).
dir="$PWD"
while :; do
  if [ -f "$dir/System/Core/VERSION" ] && [ -x "$dir/.bron/bin/bron" ]; then
    exec "$dir/.bron/bin/bron" "$@"
  fi
  [ "$dir" = "/" ] && break
  dir="$(dirname "$dir")"
done
echo "bron: this folder isn't inside a Bron vault. Go to your vault folder first (cd \\"<your vault>\\")." >&2
exit 2
"""
PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH"  # added by the Bron installer'


def copy_template(vault_root: Path, template: Path) -> None:
    """Copy the starting vault where files are missing; nothing that exists is overwritten. Obsidian is obsidian.py's job."""
    for src in sorted(template.rglob("*")):
        rel = src.relative_to(template)
        if rel.parts[0] == ".obsidian" or src.name == ".DS_Store" or "__pycache__" in rel.parts:
            continue
        dest = vault_root / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists() and not dest.is_symlink():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def replace_core(vault_root: Path, core_src: Path) -> None:
    """System/Core becomes an exact copy of the release's core/ (it is framework-owned)."""
    system = vault_root / "System"
    system.mkdir(parents=True, exist_ok=True)
    target = system / "Core"
    stage = system / f".Core-new-{os.getpid()}"
    old = system / f".Core-old-{os.getpid()}"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    shutil.copytree(core_src, stage, ignore=CORE_IGNORE)
    if target.exists():
        target.rename(old)
    try:
        stage.rename(target)
    except OSError:
        if old.exists():
            old.rename(target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def write_shim(vault_root: Path) -> None:
    shim = vault_root / ".bron" / "bin" / "bron"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(SHIM, encoding="utf-8")
    shim.chmod(0o755)


def write_source(vault_root: Path, label: str) -> None:
    path = vault_root / ".bron" / SOURCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(label + "\n", encoding="utf-8")


def install_launcher(home: Path) -> str | None:
    launcher = home / ".local" / "bin" / "bron"
    if launcher.exists() or launcher.is_symlink():
        try:
            ours = LAUNCHER_MARK in launcher.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ours = False
        if not ours:
            return f"There's already a different `bron` command at {launcher}, so Bron's own wasn't added. Inside your vault, use .bron/bin/bron."
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)
    return None


def ensure_path(home: Path, path_env: str) -> str | None:
    if str(home / ".local" / "bin") in path_env.split(":"):
        return None
    profile = home / ".zprofile"
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if PATH_LINE in text:
        return None
    separator = "" if not text or text.endswith("\n") else "\n"
    profile.write_text(text + separator + PATH_LINE + "\n", encoding="utf-8")
    return "Added ~/.local/bin to your PATH in ~/.zprofile, so the `bron` command works in new Terminal windows."


def trust_codex(home: Path, vault_root: Path, *, codex_installed: bool) -> str | None:
    config = home / ".codex" / "config.toml"
    if not config.exists() and not codex_installed:
        return None
    cannot = "Codex's settings file couldn't be extended, so this vault wasn't marked as trusted there; Codex will ask the first time you open it."
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return cannot
    projects = data.get("projects")
    key = str(vault_root)
    if isinstance(projects, dict) and key in projects:
        return None
    separator = "" if not text or text.endswith("\n") else "\n"
    new_text = text + separator + f"\n[projects.{json.dumps(key)}]\ntrust_level = \"trusted\"\n"
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        return cannot
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        shutil.copy2(config, config.with_name(f"config.toml.bron-backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    config.write_text(new_text, encoding="utf-8")
    return "Codex now trusts this vault (its settings were backed up next to them first)."


def install_vault(vault_root: Path, tree: Path, *, source: str, home: Path | None) -> int:
    from .obsidian import BundleError, install_bundle

    notes: list[str] = []
    copy_template(vault_root, tree / "template")
    replace_core(vault_root, tree / "core")
    write_shim(vault_root)
    write_source(vault_root, source)
    try:
        notes += install_bundle(vault_root, vault_root / "System" / "Core", tree / "template" / ".obsidian")
    except BundleError as exc:
        notes.append(f"Obsidian: {exc}")
    if home is not None:
        notes += [note for note in (
            install_launcher(home),
            ensure_path(home, os.environ.get("PATH", "")),
            trust_codex(home, vault_root, codex_installed=shutil.which("codex") is not None),
        ) if note]
    for note in notes:
        print(note)
    from .cli import main as bron

    previous = os.environ.get("BRON_VAULT")
    os.environ["BRON_VAULT"] = str(vault_root)
    try:
        code = bron(["sync"])
        bron(["check"])
    finally:
        if previous is None:
            os.environ.pop("BRON_VAULT", None)
        else:
            os.environ["BRON_VAULT"] = previous
    return 0 if code == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bron.install")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--tree", type=Path, required=True, help="the unpacked release (with core/ and template/)")
    parser.add_argument("--source", required=True, help="'github' or the Bron project folder updates come from")
    parser.add_argument("--no-home", action="store_true", help="don't add the global bron command, PATH line or Codex trust")
    args = parser.parse_args(argv)
    if not (args.tree / "core" / "VERSION").is_file():
        print(f"{args.tree} isn't a Bron release (no core/VERSION).", file=sys.stderr)
        return 1
    return install_vault(args.vault.resolve(), args.tree.resolve(), source=args.source, home=None if args.no_home else Path.home())


if __name__ == "__main__":
    sys.exit(main())
