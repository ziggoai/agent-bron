---
name: check
description: Run Bron's health check when the user asks Bron to check itself, when the setup seems broken, or after anything in System/ changed. Explains each problem in plain words and offers fixes.
---

# Health check

1. From the vault folder, run `.bron/bin/bron check`.
2. If it reports "all good", say so in one line.
3. Otherwise explain each problem in plain words: what is wrong, in which file, and what you propose to change.
4. Offer to fix the problems. Show the exact change to any file in `System/` and wait for a yes before editing it.
5. After fixing, run `.bron/bin/bron sync`, then the check again, and report the result.
