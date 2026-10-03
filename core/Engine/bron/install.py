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
from .statefile import read_json, write_json

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


TEMPLATE_RECORD = Path(".bron") / "state" / "template.json"


def _template_items(template: Path) -> list[tuple[str, Path]]:
    items = []
    for src in sorted(template.rglob("*")):
        rel = src.relative_to(template)
        if rel.parts[0] == ".obsidian" or src.name == ".DS_Store" or "__pycache__" in rel.parts:
            continue
        items.append((rel.as_posix(), src))
    return items


def copy_template(vault_root: Path, template: Path) -> None:
    """Copy each starting file and folder once; nothing that exists is overwritten. Obsidian is obsidian.py's job.

    Every template path ever seeded (or found already there) is recorded in .bron/state/template.json,
    so a starting file the user deleted or renamed (the main agent, a board) never comes back. A new
    starting file in a newer release is copied, unless its folder was seeded before and is gone now.
    A vault from before the record keeps System/Agents/ as it is when it already has an agent.
    """
    record = vault_root / TEMPLATE_RECORD
    data = read_json(record, {})
    known = data.get("seeded") if isinstance(data.get("seeded"), list) else None
    seeded = {str(item) for item in known or []}
    agents = vault_root / "System" / "Agents"
    keep_agents = known is None and agents.is_dir() and any(p.is_dir() for p in agents.iterdir())
    before = set(seeded)
    for key, src in _template_items(template):
        if key in seeded:
            continue
        seeded.add(key)
        rel = Path(key)
        if keep_agents and rel.parts[:2] == ("System", "Agents") and len(rel.parts) > 2:
            continue
        if any(parent.as_posix() in before and not (vault_root / parent).is_dir() for parent in rel.parents if parent != Path(".")):
            continue  # its folder was seeded once and the user removed or renamed it
        dest = vault_root / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists() and not dest.is_symlink():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    write_json(record, {"seeded": sorted(seeded)})


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
    new_text = text + separator + f"\n[projects.{json.dumps(key, ensure_ascii=False)}]\ntrust_level = \"trusted\"\n"
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        return cannot
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        shutil.copy2(config, config.with_name(f"config.toml.bron-backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    config.write_text(new_text, encoding="utf-8")
    return "Codex now trusts this vault (its settings were backed up next to them first)."


def _reason(exc: BaseException) -> str:
    if isinstance(exc, UnicodeDecodeError):
        return "it isn't plain text"
    return (getattr(exc, "strerror", None) or exc.__class__.__name__).lower()


def _home_step(step, failed: str) -> str | None:
    """A home-folder step never stops the install: a problem becomes a plain note."""
    try:
        return step()
    except (OSError, UnicodeDecodeError) as exc:
        return failed.format(reason=_reason(exc))


def home_steps(home: Path, vault_root: Path) -> list[str]:
    notes = (
        _home_step(lambda: install_launcher(home),
                   "The global bron command couldn't be added ({reason}); inside your vault, use .bron/bin/bron."),
        _home_step(lambda: ensure_path(home, os.environ.get("PATH", "")),
                   "~/.zprofile couldn't be updated ({reason}), so the global bron command may not work in new Terminal windows; "
                   "inside your vault, use .bron/bin/bron."),
        _home_step(lambda: trust_codex(home, vault_root, codex_installed=shutil.which("codex") is not None),
                   "Codex's settings couldn't be updated ({reason}); Codex will ask the first time you open this vault."),
    )
    return [note for note in notes if note]


def _migrations(vault_root: Path, previous: str | None) -> list[str]:
    """A fresh vault already has every migration; a repaired older vault gets the ones it misses."""
    from .migrations import apply_pending, record_all
    from .setup import SetupError
    from .vault import Vault

    vault = Vault(vault_root)
    if previous is None:
        record_all(vault)
        return []
    try:
        return apply_pending(vault, previous, vault.version())
    except SetupError as exc:
        return [f"A change to your setup that this version needs couldn't be made: {exc}"]


def install_vault(vault_root: Path, tree: Path, *, source: str, home: Path | None) -> int:
    from .obsidian import BundleError, install_bundle

    notes: list[str] = []
    version_file = vault_root / "System" / "Core" / "VERSION"
    previous = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else None
    copy_template(vault_root, tree / "template")
    replace_core(vault_root, tree / "core")
    write_shim(vault_root)
    write_source(vault_root, source)
    notes += _migrations(vault_root, previous)
    try:
        notes += install_bundle(vault_root, vault_root / "System" / "Core", tree / "template" / ".obsidian")
    except BundleError as exc:
        notes.append(f"Obsidian: {exc}")
    if home is not None:
        notes += home_steps(home, vault_root)
    for note in notes:
        print(note)
    from .cli import main as bron

    previous_env = os.environ.get("BRON_VAULT")
    os.environ["BRON_VAULT"] = str(vault_root)
    try:
        code = bron(["sync"])
        bron(["check"])
    finally:
        if previous_env is None:
            os.environ.pop("BRON_VAULT", None)
        else:
            os.environ["BRON_VAULT"] = previous_env
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
