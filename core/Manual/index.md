# Bron manual

How the Bron framework works, one page per topic. Read the page you need before changing any setup.

| Page | What it covers |
|---|---|
| [models.md](models.md) | Choosing a model per agent and CLI, and the friendly names Bron understands |
| [permissions.md](permissions.md) | `ask_before`, `always_allow`, action groups, and how approvals work in both CLIs |

## The basics

- **Your files:** everything in `System/` except `System/Core/`. Agents live in `System/Agents/<Name>/Agent.md`.
- **Framework files:** `System/Core/`. Replaced on update; never edit.
- **Generated files:** `AGENTS.md`, `CLAUDE.md`, `.mcp.json`, `.claude/`, `.codex/`, `.agents/`. Rebuilt by `.bron/bin/bron sync` from `System/`, automatically at the start of each session.
- **Health check:** `.bron/bin/bron check`.
