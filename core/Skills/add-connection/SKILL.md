---
name: add-connection
description: Connect a new tool ("connect Notion", "add the time server"). Guides the user through signing in for claude.ai and Codex connectors, or sets up tools that run on this Mac, then asks which agents may use it.
---

# Add a connector

1. **A connector you sign in to** (Notion, Slack, Gmail, Drive, HubSpot…): tell the user exactly where to connect it.
   - Claude: claude.ai → Settings → Connectors → find it → Connect (it then appears in Claude Code too).
   - Codex: Codex's settings → MCP servers, or `codex mcp add` as the connector's own instructions say.
   When they say it's done, run `.bron/bin/bron connections scan` and confirm you found it.
2. **A tool that runs on this Mac or at a web address** (the user or its documentation gives the command or address): preview `.bron/bin/bron connections add --name '<Name>' --command '<command>' --args '<args>' --preview` (or `--url '<url>'`), show it, wait for a yes, then apply without `--preview`. Never put passwords or keys in it; those stay in the tool's own sign-in.
3. Ask which agents may use it, then for each: `.bron/bin/bron agent set '<Name>' --add-connection '<connection>' --preview`, show, wait for a yes, apply.
