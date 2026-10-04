"""Starting Bron's own commands as detached background processes."""
from __future__ import annotations

import subprocess

from .vault import Vault


def spawn_detached(vault: Vault, argv: list[str], log_name: str, *, popen=subprocess.Popen) -> bool:
    """Run `bron <argv…>` detached, with its output in `.bron/logs/<log_name>`. False if the vault has no bron command."""
    if not vault.bron_command.is_file():
        return False
    log = vault.bron_dir / "logs" / log_name
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log, "a", encoding="utf-8") as out:
            popen([str(vault.bron_command), *argv], cwd=vault.root, stdout=out, stderr=subprocess.STDOUT,
                  stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True
