#!/usr/bin/env bash
# Create or refresh a development Bron vault from this repository.
# Usage: scripts/dev-vault.sh <vault-path>
# - Your files (template/) are only copied where missing; nothing of yours is overwritten.
# - System/Core is always replaced with the repository's core/.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?usage: scripts/dev-vault.sh <vault-path>}"
mkdir -p "$TARGET"
VAULT="$(cd "$TARGET" && pwd)"

rsync -a --ignore-existing "$REPO/template/" "$VAULT/"
rm -rf "$VAULT/System/Core"
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '*.egg-info' --exclude '.pytest_cache' "$REPO/core/" "$VAULT/System/Core/"

# Install the self-contained terminal payload; no Termy or npm is needed in the vault.
python3 "$REPO/scripts/install-terminal.py" "$VAULT"

uv venv --quiet --allow-existing --python 3.12 "$VAULT/.bron/venv"
uv pip install --quiet --python "$VAULT/.bron/venv/bin/python" --reinstall-package bron-engine "$VAULT/System/Core/Engine"

mkdir -p "$VAULT/.bron/bin"
printf '%s\n' "$REPO" > "$VAULT/.bron/source"  # lets `bron update` find this project again
cat > "$VAULT/.bron/bin/bron" <<'SHIM'
#!/bin/sh
VAULT="$(cd "$(dirname "$0")/../.." && pwd)"
export BRON_VAULT="$VAULT"
exec "$VAULT/.bron/venv/bin/python" -m bron "$@"
SHIM
chmod +x "$VAULT/.bron/bin/bron"

"$VAULT/.bron/bin/bron" sync
"$VAULT/.bron/bin/bron" check || true
echo "Dev vault ready: $VAULT"
