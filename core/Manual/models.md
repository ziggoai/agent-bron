---
aliases:
  claude:
    opus-5.5: claude-opus-5-5
    sonnet-5.5: claude-sonnet-5-5
    haiku-4.5: claude-haiku-4-5-20251001
    fable-5.1: claude-fable-5-1
    opus: opus
    sonnet: sonnet
    haiku: haiku
  codex: {}
---

# Models

Every agent's `Agent.md` names one model per CLI under `models:`.

- `default` means "use whatever model that CLI is set to". Bron uses this unless you ask for something else.
- A friendly name from the list above, such as `opus-5.5`, is translated to the CLI's model ID. Capitals and spaces don't matter: "Opus 5.5" works too.
- Anything else is passed to the CLI exactly as written, so a full model ID always works.

Codex model IDs can be listed inside Codex with `/model` (for example `gpt-6.1-sol` or `gpt-6-astra`).

When the user asks for a model by name, look for it here first. If it isn't listed, use the full model ID and tell the user which one you chose.
