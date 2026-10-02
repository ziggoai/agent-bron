---
name: connections
description: Find and register the connectors already set up in Claude Code and Codex, when the user asks Bron to check, refresh or list its connections, or says a connector is missing.
---

# Connections

1. From the vault folder, run `.bron/bin/bron connections scan`.
2. Tell the user in plain words what it found: new connectors, ones that need signing in again (they fix that in claude.ai connector settings or in Codex), and ones no longer found. Connectors that aren't set up yet are only counted; if the user wants one, they connect it in claude.ai or the CLI, then you scan again.
3. To give a team member a connector, add its name to that agent's `connections:` list in `System/Agents/<Name>/Agent.md` (show the change and get a yes first). Bron itself uses all of them (`connections: [all]`).
