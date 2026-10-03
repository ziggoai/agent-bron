#!/usr/bin/env bash
# Create or refresh a development Bron vault from this repository (the same steps as install.sh, from this folder).
# Usage: scripts/dev-vault.sh <vault-path>
# - Your files are only copied where missing; nothing of yours is overwritten.
# - System/Core is always replaced with the repository's core/.
# - `bron update` in that vault keeps following this folder.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?usage: scripts/dev-vault.sh <vault-path>}"
mkdir -p "$TARGET"
VAULT="$(cd "$TARGET" && pwd)"

uv venv --quiet --allow-existing --python 3.12 "$VAULT/.bron/venv"
uv pip install --quiet --python "$VAULT/.bron/venv/bin/python" --reinstall-package bron-engine "$REPO/core/Engine"
"$VAULT/.bron/venv/bin/python" -m bron.install "$VAULT" --tree "$REPO" --source "$REPO" --no-home
echo "Dev vault ready: $VAULT"
