# Agent Bron

A framework for AI agents that run entirely in Claude Code and Codex, with an Obsidian vault as the workspace. You define agents once in plain markdown under `System/`; Bron generates each CLI's setup so both behave the same.

Design: `docs/superpowers/specs/2026-10-01-bron-core-design.md`.

## Development

Requirements: macOS, [uv](https://docs.astral.sh/uv/), and Claude Code and/or Codex for the live tests.

- Unit tests: `uv run --project core/Engine pytest tests -q`
- Live tests (real CLI sessions, uses your logins): `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q`
- Build or refresh a dev vault: `scripts/dev-vault.sh "<path>"`. Open it in Obsidian or start `claude` / `codex` inside it.

Layout: `core/` becomes `System/Core` in every vault (framework-owned, replaced on update); `template/` is the starting vault; `core/Engine/bron` is the engine behind the `bron` command.

## Bron Terminal

The framework includes the standalone macOS [Bron Terminal plugin](terminal/README.md). Its source and tests live in `terminal/`; the verified runtime payload lives in `core/Plugins/bron-terminal/`. `scripts/dev-vault.sh` installs it without Termy. Run `npm ci --prefix terminal` and `npm run package --prefix terminal` to rebuild the payload and standalone archive. See [release verification](terminal/RELEASE.md) for supported platforms and live acceptance coverage.
