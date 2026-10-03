# Installing and updating Bron

## Installing
Paste into Terminal (macOS):

    curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash

It installs into the folder you're in, or into a folder you name: `… | bash -s -- "<folder>"`. In your home folder or a system folder it asks where to go instead (default `~/Documents/Bron`). If the folder is in iCloud Drive, or in Desktop or Documents while iCloud syncs them, it warns you first. Running it again on a Bron vault repairs it; your files are never overwritten.

It also adds a `bron` command that works from any folder inside a vault (`~/.local/bin/bron`), and, if you use Codex, marks the vault as trusted there.

## Updating
Say "Bron, update yourself". Bron shows what's new and waits for your yes. It can take a few minutes. Or run:

- `.bron/bin/bron update --preview`: what's new, without changing anything.
- `.bron/bin/bron update`: update now.
- `.bron/bin/bron update --undo`: go back to the version before the last update.

Before updating, Bron backs up `System/Core` to `.bron/backups/core-<version>-<date>/` (the last 3 are kept). If anything fails, or the update is stopped, it goes back by itself; if the Mac shut down in the middle, the next `bron update` finishes going back first. Your own files (everything in `System/` except `System/Core/`, and all your notes) are never touched, and a starting file you deleted or renamed (such as the main agent) never comes back. Obsidian keeps your settings, and only Bron's theme and plugin code are refreshed (a plugin you updated yourself to a newer version is left alone). If an update changes the theme or plugins, Bron tells you to quit Obsidian completely (⌘Q) and open it again, because Obsidian only loads plugins when it starts.

Once a day, at the start of a session, Bron checks whether a new version is out and tells you. To stop that, set `update_check: false` in `System/Settings.md`.

A development vault made with `scripts/dev-vault.sh` follows its Bron project folder instead of GitHub (`bron update --from <folder>` switches folders).
