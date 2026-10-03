---
name: update
description: Update the Bron framework when the user asks Bron to update itself ("Bron, update yourself", "update Bron", "get the latest Bron"), or undo the last update ("undo the update", "go back to the previous Bron"). Shows what's new first and keeps all the user's own files.
---

# Update Bron

## Update
1. Run `.bron/bin/bron update --preview`.
   - "up to date": tell the user in one line; stop.
   - A problem (for example "GitHub didn't answer"): say it in plain words; stop.
2. Otherwise summarise what's new in a few short bullets, in plain words, and ask: "Update now?" Wait for a yes.
3. After a yes, run `.bron/bin/bron update`. It can take a few minutes.
4. Report the result in plain words:
   - the first line says which version Bron moved to;
   - mention any problem the health check lists at the end, and offer to fix it;
   - say their own files were kept, that "undo the update" goes back, and that a new session is needed for every change to apply.
5. If it says the update didn't finish, explain the reason it gives in simple terms. Bron has already gone back to the previous version by itself. Don't retry more than once.

## Undo the update
Run `.bron/bin/bron update --undo` and report its first line in plain words, plus that a new session is needed.

Never edit `System/Core/` or the generated folders yourself to "finish" an update.
