# Connections

Each file in `System/Connections/` is one outside tool an agent can use.

- **Native connectors** (`type: native`) are the ones already set up in Claude Code (including claude.ai connectors and plugins) or in Codex. Bron finds them with `.bron/bin/bron connections scan` (also run after every update) and writes one file each:
  - `claude:` the name Claude Code uses (tools appear as `mcp__<claude>__<tool>`)
  - `codex:` the name in Codex's own settings
  - `status:` connected, needs sign-in, available or not found
  Bron only ever changes those lines; edit the description or add notes freely.
- **Vault connections** (`type: mcp-stdio` or `mcp-http`) are servers Bron defines itself for both CLIs.

An agent's `connections:` list decides what it may use. `all` means every connection (Bron's default). Anything not listed is switched off for that agent in both CLIs, including when it works a ticket in the background.
