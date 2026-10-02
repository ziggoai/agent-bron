---
name: update
description: Update the Bron framework when the user asks Bron to update itself ("Bron, update yourself", "update Bron", "get the latest Bron"). Keeps all the user's own files and reports what changed.
---

# Update Bron

1. From the vault folder, run `.bron/bin/bron update`. It can take a minute.
2. Report the result in plain words:
   - the first line says which version Bron moved to, or that it was already up to date;
   - mention any problem the health check lists at the end, and offer to fix it;
   - remind the user that their own files were kept, and that a new session is needed for every change to apply.
3. If it says the update didn't finish, explain the reason it gives in simple terms and suggest the fix it names. Don't retry more than once.
4. Never edit `System/Core/` or the generated folders yourself to "finish" an update.
