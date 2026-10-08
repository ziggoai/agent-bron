# Bron Terminal 0.6.0 release verification

Verified on 2026-10-02 using macOS Apple Silicon, Obsidian 1.13.7, Claude Code 2.1.288, and Codex 0.160.0. A separate vault used the default Obsidian theme and had only Bron Terminal installed.

## Changes

- Added a default login-shell entry point. Shell commands and CLI startup arguments reach the actual shell.
- Moved the maintainable source, locked dependencies, build, native helper source, and tests into the framework repository.
- Cleared submitted text after the PTY accepts Enter, retained text typed for the next message, and bounded acknowledgment waits. An unconfirmed submission opens native controls rather than resending automatically.
- Routed multiline and tabbed drafts through bracketed paste. Live Codex testing reproduced a cancellation bug with the old Escape/Enter insertion sequence.
- Kept native controls and the composer mutually exclusive through redraws, scrolling, and menus. Preserved unsent drafts across model-picker cancellation.
- Tracked the shell's foreground process, including `exec` replacing the shell. Tab closure terminates the foreground job as well as the shell.
- Added output backpressure, idempotent process disposal, and cleanup during failed startup.
- Added a checksum-verified installer with upgrade backups and a standalone archive containing the complete runtime payload.

## Acceptance checks

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

## Recheck with Codex 0.161.0

Rechecked on 2026-10-08 with Codex 0.161.0 and Claude Code 2.1.294 in a fresh `scripts/dev-vault.sh` vault. The terminal code was unchanged. The following Codex checks passed:

- A multiline draft with accented text, emoji, and CJK characters reached Codex unchanged and was answered. The composer was then empty.
- With an unsent draft in the composer, opening and cancelling the model picker kept the draft. Codex then received it exactly as typed.
- `codex resume --last` restored the saved test conversation.
- `codex resume` opened its native picker, and Escape opened a new session.
- `/quit` typed in the composer exited Codex.

Found during the recheck; neither is specific to 0.161.0:

- After an Enter is not confirmed, the composer stays blocked even if Codex exits and a new session starts in the same tab. Once the error message clears, typing and Enter do nothing. Escape, Ctrl+C, or editing in terminal controls clears the block. Codex drops an Enter that arrives within about 30 ms of the typed text, which happens only with scripted input. From 30 ms on, every Enter was accepted.
- After an emoji, a stale character can stay visible in Codex's input line once the model picker closes. The text Codex receives is correct. The cause is that xterm counts emoji as one column wide and Codex counts them as two.

## Release boundaries

This is a macOS payload. Both helper architectures are built and signed locally; Intel hardware has not been exercised in this run. Linux and Windows are not supported by the packaged backend. The supplied helper is ad-hoc signed, not Developer ID signed or notarized. No valid code-signing identity is installed on this machine. Public shipment remains blocked on the `npm run release:public` signing and Apple notarization step.

The automated framework suite skips its opt-in live agent tests unless `BRON_LIVE=1` is set. The terminal's real Claude and Codex exchanges above were checked separately in Obsidian. Testing establishes the listed behavior; it is not a guarantee that every external CLI version or custom shell configuration will have a recognized composer layout. Native terminal controls remain available.
