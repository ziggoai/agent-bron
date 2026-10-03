# Agent Bron

A framework for AI agents that run entirely in Claude Code and Codex, with an Obsidian vault as the workspace. You define agents once in plain markdown under `System/`; Bron generates each CLI's setup so both behave the same.

Design: `docs/superpowers/specs/2026-10-01-bron-core-design.md`.

## Install

Paste this into Terminal (macOS):

```
curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash
```

To choose the folder: `curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash -s -- "<folder>"`.

It sets up a Bron vault with the agents, the Obsidian theme and plugins, and a `bron` command. Then open the folder in Claude Code or Codex (desktop app or terminal), or in Obsidian, and say hi to Bron.

## Updating

Say "Bron, update yourself". Details: [core/Manual/updates.md](core/Manual/updates.md).

## Development

Requirements: macOS, [uv](https://docs.astral.sh/uv/), and Claude Code and/or Codex for the live tests.

- Unit tests: `uv run --project core/Engine pytest tests -q`
- Live tests (real CLI sessions, uses your logins): `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q`
- Build or refresh a dev vault: `scripts/dev-vault.sh "<path>"`. Open it in Obsidian or start `claude` / `codex` inside it.
- Release: `scripts/release.sh <version>` (needs a `CHANGELOG.md` section first; push the commit and tag afterwards).
- Obsidian bundle: `python3 scripts/export-obsidian.py <your vault>` refreshes `core/Obsidian` and `template/.obsidian` from your own vault, without personal state.

Layout: `core/` becomes `System/Core` in every vault (framework-owned, replaced on update); `template/` is the starting vault; `core/Engine/bron` is the engine behind the `bron` command.

## Bron Terminal

The framework includes the standalone macOS [Bron Terminal plugin](terminal/README.md). Its source and tests live in `terminal/`; the verified runtime payload lives in `core/Plugins/bron-terminal/`. Bron installs it into every vault; `scripts/install-terminal.py <vault>` installs it on its own. Run `npm ci --prefix terminal` and `npm run package --prefix terminal` to rebuild the payload and standalone archive. See [release verification](terminal/RELEASE.md) for supported platforms and live acceptance coverage.

## Licence

MIT (Ziggo AI). Bundled third-party Obsidian plugins keep their own licences (`core/Obsidian/THIRD-PARTY-NOTICES.md`).
