# Bron Terminal

Bron Terminal 0.6.1 is a standalone Obsidian desktop plugin. It bundles xterm.js, its styles, and a native PTY helper. It does not load Termy, use Termy's server, or require a Bron theme or framework installation.

The current release targets macOS 11 or later on Apple Silicon and Intel. The helper contains both architectures; live acceptance was run on Apple Silicon. Obsidian 1.8.7 or later is required. Linux and Windows backends are not included.

## Use

Open **Bron Terminal: Open Bron Terminal**. Enter a shell command, or press Enter with an empty composer to start your login shell. The working directory defaults to the vault. The folder menu can change it before startup.

Commands are interpreted by your shell, including aliases, pipelines, environment assignments, `claude -c`, `codex resume`, and `codex resume --last`. Authentication and CLI environment settings are inherited. The default Terminal entry does not require either AI CLI to be installed.

When Claude Code or Codex displays a recognized message editor, Bron replaces its visible input area with the composer. Enter sends; Shift+Enter adds a line. Multiline text, tabs, and large drafts use bracketed paste. Short single-line drafts support the CLI's own completion and history controls. Attachment paths are sent as part of an agent message; shell commands use ordinary file paths instead.

Menus, approvals, password prompts, full-screen applications, and unrecognized screens use native terminal controls. The terminal button also opens those controls. **Back to message** returns to the composer when the application has a recognized editor. Returning after editing a native shell line cancels that unsubmitted line before accepting a new command.

The **Open Claude Code** and **Open Codex** commands remain direct CLI shortcuts. Their initial text is an agent prompt. Use the default **Open Bron Terminal** command for shell commands and custom CLI launch arguments.

Closing a tab ends its shell and foreground process. Obsidian restart does not preserve running processes. Claude and Codex session history remains managed by the CLIs and can be resumed from a new terminal.

## Install with Bron Framework

The framework's `scripts/dev-vault.sh <vault>` installs the prebuilt payload from `core/Plugins/bron-terminal/`. No Node.js, npm, compiler, or Termy installation is required inside the destination vault.

To install only the terminal:

```sh
python3 scripts/install-terminal.py "/path/to/vault"
```

The installer checks payload hashes, restores the helper's executable permission, preserves `data.json` and other plugins, and backs up an existing plugin under `.bron/backups/terminal-<timestamp>/`. Pass `--no-enable` to copy the plugin without adding it to the enabled list. Obsidian may ask you to enable community plugins when opening a new vault.

An already loaded plugin keeps its current code until reloaded. Finish active terminal sessions before reloading it; reload ends those processes.

For a manual installation, extract `dist/bron-terminal-<version>-macos.zip` and copy the entire `bron-terminal` directory into `<vault>/.obsidian/plugins/`. Keep `bin/pty-host-darwin` with the JavaScript, CSS, manifest, and notices. Enable Bron Terminal in Obsidian. If an extraction tool loses permissions, run `chmod +x <vault>/.obsidian/plugins/bron-terminal/bin/pty-host-darwin`.

The macOS helper has an ad-hoc signature. Developer ID signing and Apple notarization are not part of this build. Distribution channels that require notarized binaries need that additional release step.

## Build and verify

On macOS with Node.js, npm, Python 3, and Xcode command-line tools:

```sh
cd terminal
npm ci
npm run package
```

`package` builds the JavaScript and universal helper, runs terminal tests, refreshes the framework payload and its checksums, and creates the standalone ZIP. Dependencies are locked in `package-lock.json`; the destination vault receives bundled code only.

From the repository root, run installer and framework checks with:

```sh
uv run --project core/Engine pytest tests -q
```

The source is maintained here rather than patched into an installed bundle. `src/terminal-service.js` owns sessions; `native/pty-host.c` owns PTYs; `src/terminal-input.js` serializes editor changes and submission acknowledgment; `src/terminal-presentation.js` controls input visibility. Third-party license notices are included in every release payload.

CLI screen layouts can change independently of this plugin. An unrecognized screen falls back to native controls, preserving access to the application. Re-run the clean-vault acceptance checks in `RELEASE.md` when changing supported CLI versions.

For a public macOS release, install your Developer ID Application certificate in the keychain and configure a `notarytool` keychain profile. Then run:

```sh
BRON_SIGN_IDENTITY="Developer ID Application: ..." \
BRON_NOTARY_PROFILE="your-keychain-profile" \
npm run release:public
```

This command requires both settings, verifies the Developer ID signature and hardened runtime, and submits the archive to Apple. It copies the approved archive into `dist/public/` only after Apple returns `Accepted`. Keep the resulting notarization JSON with the release. The current development machine has no valid signing identity, so the supplied archive has not passed this public-release step.
