# Bron Core, Plan 4: install, Obsidian bundle, updates

Status: design approved in conversation on 2026-10-02. Refines the core spec (`2026-10-01-bron-core-design.md`) §9 (repository), §10.1 (install), §10.3 (updates) and §11 (Obsidian bundle); builds on Plans 1–3 and the polish round as built (framework 0.4.1), plus the Bron Terminal integration (`terminal/`, `core/Plugins/bron-terminal/`). Where they disagree, this spec wins.

## 1. Purpose

1. Anyone with a Mac installs Bron with one line pasted into Terminal, in the folder they choose, and can then work with it from Claude Code or Codex (desktop app or terminal) or Obsidian.
2. Every vault looks and works like the maintainer's: the Bron theme and plugins, without personal state.
3. "Bron, update yourself" pulls the newest release from GitHub, with a preview of what changed, a backup, automatic rollback on failure, and "undo the update".

Prerequisites (outside this plan's code, done once by the maintainer): the repository's history is cleaned of personal details (author shown as "Ziggo AI"), an MIT licence is added (copyright "Ziggo AI"), and the repository is made public.

## 2. Decisions (approved by the user)

- **D1. Public repository** `github.com/ziggoai/agent-bron`; installs and updates download from it without any sign-in.
- **D2. Works anywhere:** nothing in the install or onboarding assumes Obsidian; Obsidian is the recommended way to see the vault, not a requirement.
- **D3. Installs where it's run:** the folder the command is run in (or a folder given on the command line); home and system folders are refused in favour of asking (default `~/Documents/Bron`); a non-empty folder that isn't a Bron vault needs one confirmation; an existing Bron vault is repaired.
- **D4. Obsidian bundle v1:** Bron theme, Bron Terminal, Bron Workspace and the other plugins the maintainer uses (Colored Tags, File Explorer Note Count, Style Settings, Data Files Editor, XLSX Viewer; Iconize shipped disabled); File Color, Termy (replaced by Bron Terminal), the v2 theme and v2 plugins left out; personal state scrubbed.
- **D5. Bron Terminal is a standalone plugin** maintained in `terminal/`; the framework always ships its latest build (`core/Plugins/bron-terminal/`, checked against `terminal/` by a test) and installs it from the vault's own framework copy.
- **D6. Updates notify, never apply on their own;** applying needs the user's yes.
- **D7. Releases are version tags** (`v0.5.0`) with a `CHANGELOG.md` entry; the maintainer's assistant creates them when a plan is merged.

## 3. Repository layout (additions)

```
install.sh                      the one-line installer (bash, macOS)
CHANGELOG.md                    one section per version, newest first
LICENSE                         MIT, Ziggo AI
core/Obsidian/                  framework-owned Obsidian files, refreshed on update:
  themes/Bron/                  theme.css, manifest.json
  plugins/<id>/                 main.js, manifest.json, styles.css (no data.json)
  snippets/, icons/             the ones the theme uses (if any)
core/Plugins/bron-terminal/     Bron Terminal build (exists)
template/.obsidian/             first-install settings only: app.json, appearance.json,
                                core-plugins.json, community-plugins.json, plugin data.json defaults
scripts/release.sh              maintainer: bump version, check changelog, tag
scripts/export-obsidian.py      maintainer: refresh core/Obsidian + template/.obsidian from a source vault, scrubbing personal state
```

## 4. Install (`install.sh`)

Run as `curl -fsSL https://raw.githubusercontent.com/ziggoai/agent-bron/main/install.sh | bash` (optionally `| bash -s -- <folder>`).

1. **Mac check:** macOS 12+; `curl`, `tar` present. Warn (not stop) when neither `claude` nor `codex` is on PATH ("install Claude Code or Codex before talking to Bron").
2. **Choose the folder** (D3). If the folder is inside iCloud Drive (`~/Library/Mobile Documents`), warn that Bron's engine doesn't work well there and ask to confirm.
3. **Download** the latest release: the newest `vX.Y.Z` tag (GitHub tags API, sorted by version), its source tarball from `codeload.github.com`, unpacked to a temporary folder. `BRON_INSTALL_SOURCE=<folder or tarball path>` overrides the download (for development and tests).
4. **`uv`:** use it if present; otherwise install it with Astral's official installer into `~/.local/bin`.
5. **Set up the vault:** the template copied where missing (never overwriting), `System/Core` replaced from `core/`, the engine installed into `.bron/venv` (Python 3.12 via uv), `.bron/bin/bron` shim, `.bron/source` set to `github`.
6. **Obsidian bundle:** if the vault has no `.obsidian/`, copy `template/.obsidian/` and the files from `System/Core/Obsidian/`; if it has one, add the theme and plugin files without changing the user's existing settings, enable Bron Terminal and Bron Workspace in `community-plugins.json`, and leave the theme choice alone (the finish message says how to pick it). Install Bron Terminal from `System/Core/Plugins/bron-terminal` (the existing installer).
7. **Global `bron` command:** `~/.local/bin/bron`, a small launcher that finds the vault from the current folder (walking up to `System/Core/VERSION`) and runs that vault's shim; if `~/.local/bin` isn't on PATH, add it to `~/.zprofile` (once, with a comment) and say so.
8. **Codex trust:** if `~/.codex/config.toml` exists (or `codex` is installed), add `[projects."<vault>"] trust_level = "trusted"` when missing, after backing the file up.
9. **First refresh and health check** (`bron sync`, `bron check`).
10. **Finish message:** "Your Bron vault is ready at <folder>. Open this folder in Claude Code or Codex (desktop app or terminal), or in Obsidian, and say hi to Bron." Plus the theme tip when an existing `.obsidian` was kept.

Safe to re-run: every step is idempotent; user files are never overwritten; a failure prints the step and a plain reason and leaves what was there.

## 5. Updates

- **`bron update`** (default source: GitHub; `--from <folder>` keeps today's development behaviour with `.bron/source`):
  1. Find the latest version (as in §4.3). Already current → say so.
  2. **Preview** (`bron update --preview`): print the `CHANGELOG.md` sections between the current and the latest version. The `update` skill shows them and waits for a yes.
  3. **Apply:** download and unpack; check the unpacked `core/VERSION` equals the tag; back up `System/Core` to `.bron/backups/core-<old version>-<time>/`; replace `System/Core`; reinstall the engine into `.bron/venv`; run migrations (§5.1); refresh `.obsidian` plugin and theme files from `System/Core/Obsidian` and Bron Terminal from `System/Core/Plugins` (never `data.json` or the user's settings files); `bron sync`; `bron check`. Any failure restores the backup (and reinstalls the old engine) automatically and says what went wrong.
  4. Report: "Updated Bron from <old> to <new>." plus anything the health check lists.
- **`bron update --undo`:** restore the newest `core-*` backup, reinstall its engine, refresh the plugins from it, sync, check. The `update` skill handles "undo the update".
- **Daily check:** at session start, at most once per 24 hours, with a 2-second limit and silence when offline: if a newer version exists, the briefing adds "Bron <version> is available. Say 'update yourself' to see what's new." Result cached in `.bron/state/update-check.json`. `update_check: false` in Settings.md turns it off.

### 5.1 Migrations
`core/Engine/bron/migrations/`: ordered steps keyed by the version that introduced them, each previewed (plain summary) and applied through the Plan 3 change runner (backup and rollback included). None exist yet; the mechanism and an empty registry ship now.

## 6. The Obsidian bundle

- `scripts/export-obsidian.py <source vault>` copies, from the maintainer's vault, the v1 theme and the bundled plugins' code files into `core/Obsidian/`, and their settings into `template/.obsidian/`, with personal state removed: no `workspace.json`, `workspace-mobile.json`, `devin-backups/`, `graph.json`; each plugin's `data.json` reset to the plugin's defaults or a reviewed clean version (no absolute paths, vault names, IDs, shortcuts or section lists); File Color, Termy, the v2 theme and v2 plugins excluded. A test fails if any bundled file contains `/Users/`, an email address, or the source vault's name.
- Bron Terminal comes from `core/Plugins/bron-terminal` (not from the export).
- Third-party plugins are pinned copies; an update refreshes their code from `core/Obsidian`.

## 7. Releases

`scripts/release.sh <version>`: refuses unless the working tree is clean, the version is newer than the latest tag, and `CHANGELOG.md` has a section for it; bumps `core/VERSION`, `pyproject.toml`, `__init__.py`, `uv.lock`; runs the test suite; commits and creates the tag. Pushing is a separate, explicit step.

## 8. Error handling
- No network → plain message, nothing changed.
- GitHub rate limit or an unreadable tag list → plain message ("GitHub didn't answer; try again later").
- A download that doesn't contain a matching `core/VERSION` → refused, nothing changed.
- Every update step that fails rolls back to the backup.

## 9. Testing
- `install.sh` runs against `BRON_INSTALL_SOURCE` (a local tarball of the repo) with a temporary `HOME`: empty folder, existing notes folder (with confirmation), existing Bron vault (repair), refused home folder, `.obsidian` merge, PATH line added once, Codex trust entry added once, re-run idempotent.
- `bron update` against a local fake release source (tags JSON + tarballs): preview text, apply, failure → rollback, undo, daily check caching and offline silence.
- Bundle scrub test (§6); Bron Terminal payload test (exists).
- One live check: install from the public GitHub URL into a temporary folder after the repository is public.
