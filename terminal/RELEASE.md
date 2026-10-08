# Bron Terminal release verification

## 0.6.1

Verified on 2026-10-08 using macOS Apple Silicon, Obsidian 1.13.7, Claude Code 2.1.294, and Codex 0.161.0, in a fresh `scripts/dev-vault.sh` vault.

### Changes

- When a different program starts in a tab, the composer is cleared of an earlier unconfirmed Enter. Previously, once its error message had cleared, the composer stayed blocked after Codex exited and a new session started in the same tab.
- The terminal uses Unicode 11 character widths (`@xterm/addon-unicode11` 0.9.0), matching how Claude Code and Codex draw emoji. Previously, a stale character could stay on Codex's input line after the model picker closed.

### Acceptance checks

The terminal suite passed 94 tests. The PTY helper is byte-identical to 0.6.0's.

Live checks in the clean vault cover:

- A Codex multiline draft containing accented text, emoji, and CJK characters, answered exactly.
- Opening and cancelling the Codex model picker with an emoji draft. The input line redrew without stale characters, and Codex received the draft exactly as typed.
- A forced unconfirmed Enter, followed by Codex exiting and a new Codex starting in the same tab. The new session accepted typed text and Enter.
- `codex resume --last` restoring the conversation, and `codex resume` opening its picker, where Escape opened a new session.
- `/quit` typed in the composer.
- A Claude Code message with accented text, emoji, and CJK characters, echoed exactly and displayed without overlap.

Codex drops an Enter that arrives within about 30 ms of the typed text. Only scripted input is that fast; from 30 ms on, every Enter was accepted. The composer now recovers from such a drop when a new program starts, and Escape or Ctrl+C recovers within the same session.

## 0.6.0

Verified on 2026-10-02 using macOS Apple Silicon, Obsidian 1.13.7, Claude Code 2.1.288, and Codex 0.160.0. A separate vault used the default Obsidian theme and had only Bron Terminal installed.

### Changes

- Added a default login-shell entry point. Shell commands and CLI startup arguments reach the actual shell.
- Moved the maintainable source, locked dependencies, build, native helper source, and tests into the framework repository.
- Cleared submitted text after the PTY accepts Enter, retained text typed for the next message, and bounded acknowledgment waits. An unconfirmed submission opens native controls rather than resending automatically.
- Routed multiline and tabbed drafts through bracketed paste. Live Codex testing reproduced a cancellation bug with the old Escape/Enter insertion sequence.
- Kept native controls and the composer mutually exclusive through redraws, scrolling, and menus. Preserved unsent drafts across model-picker cancellation.
- Tracked the shell's foreground process, including `exec` replacing the shell. Tab closure terminates the foreground job as well as the shell.
- Added output backpressure, idempotent process disposal, and cleanup during failed startup.
- Added a checksum-verified installer with upgrade backups and a standalone archive containing the complete runtime payload.

### Acceptance checks

The terminal suite passed 91 tests. The framework suite passed 627 tests with 14 opt-in live tests skipped; six installer tests were also rerun against the release payload. A fresh `scripts/dev-vault.sh` installation completed with no health-check errors and the expected first-use Codex trust warning.

The automated tests cover input synchronization, delayed and missing acknowledgment, write failures, completion, draft limits, multiline paste, native-dialog transitions, scrollback clipping, attachments, real PTY input and resizing, process shutdown, clean installation, upgrade preservation, and corrupt-package rejection.

Live checks in the clean vault cover:

- Shell command execution and a cleared composer afterward.
- `claude -c`, both without history and with a saved conversation.
- A real Claude response with the native prompt cropped and one visible composer.
- `codex resume` opening its native picker, and Escape opening a new session.
- `codex resume --last` restoring the saved test conversation.
- A real Codex response to a multiline draft containing accented text, emoji, and CJK characters.
- Opening and cancelling the Codex model picker with an unsent draft retained and resynchronized.
- Plugin reload and startup from the packaged payload with Termy absent.

## Release boundaries

This is a macOS payload. Both helper architectures are built and signed locally; Intel hardware has not been exercised in this run. Linux and Windows are not supported by the packaged backend. The supplied helper is ad-hoc signed, not Developer ID signed or notarized. No valid code-signing identity is installed on this machine. Public shipment remains blocked on the `npm run release:public` signing and Apple notarization step.

The automated framework suite skips its opt-in live agent tests unless `BRON_LIVE=1` is set. The terminal's real Claude and Codex exchanges above were checked separately in Obsidian. Testing establishes the listed behavior; it is not a guarantee that every external CLI version or custom shell configuration will have a recognized composer layout. Native terminal controls remain available.
