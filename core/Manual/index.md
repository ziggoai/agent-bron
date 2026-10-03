# Bron manual

How the Bron framework works, one page per topic. Read the page you need before changing any setup.

| Page | What it covers |
|---|---|
| [models.md](models.md) | Choosing a model per agent and CLI, and the friendly names Bron understands |
| [permissions.md](permissions.md) | `ask_before`, `always_allow`, action groups, and how approvals work in both CLIs |
| [connections.md](connections.md) | Connectors: how Bron finds them and which agent may use which |
| [tickets.md](tickets.md) | Tickets: handing work between agents, statuses, approvals |
| [routines.md](routines.md) | Routines: repeating work per period, checklists and due dates |
| [setup.md](setup.md) | Setup commands: agents, projects, routines, skills, connectors and settings, each previewed first |
| [memory.md](memory.md) | What Bron remembers, where it's kept, searching past conversations, and turning summaries off |
| [updates.md](updates.md) | Installing Bron, updating it, undoing an update, and the daily new-version check |

## The basics

- **Your files:** everything in `System/` except `System/Core/`. Agents live in `System/Agents/<Name>/Agent.md`.
- **Framework files:** `System/Core/`. Replaced on update; never edit.
- **Generated files:** `AGENTS.md`, `CLAUDE.md`, `.mcp.json`, `.claude/`, `.codex/`, `.agents/`. Rebuilt by `.bron/bin/bron sync` from `System/`, automatically at the start of each session.
- **Health check:** `.bron/bin/bron check`.
- **Updating Bron:** say "Bron, update yourself". Bron shows what's new first, keeps your files, and can undo the update (see updates.md).
