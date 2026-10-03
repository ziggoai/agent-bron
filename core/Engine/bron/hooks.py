"""Entry point for both CLIs' automatic triggers. A trigger must never break the user's session."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

QUICK = ("pre-compact", "stop", "session-end")


def main(event: str, cli: str, stdin=None, stdout=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        if event in QUICK:
            payload = _payload(stdin)
            _marker(event, cli, payload)
            if event == "session-end":
                _close_chats(cli, payload)
        elif event == "session-start":
            try:
                output = _session_start(cli)
            except Exception as exc:  # noqa: BLE001
                _log_error(event, cli, exc)
                output = f"Bron: the startup check failed ({exc.__class__.__name__}). Ask Bron to run `.bron/bin/bron check`.\n"
            try:
                stdout.write(output)
            except Exception:  # noqa: BLE001
                pass
        elif event == "user-prompt":
            payload = _payload(stdin)
            text = _route(cli, payload) + _ticket_updates()
            if text:
                try:
                    stdout.write(text)
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001 - a trigger must never fail the session
        _log_error(event, cli, exc)
    return 0


def _payload(stdin) -> dict:
    try:
        if hasattr(stdin, "isatty") and stdin.isatty():
            return {}
        raw = stdin.read()
    except (OSError, ValueError):
        return {}
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _state_dir() -> Path:
    from .vault import Vault

    path = Vault.find().state_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _marker(event: str, cli: str, payload: dict) -> None:
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        "cli": cli,
        "agent": os.environ.get("BRON_AGENT", ""),
        "ticket": os.environ.get("BRON_TICKET", ""),
        "session_id": str(payload.get("session_id", "")),
        "transcript_path": str(payload.get("transcript_path", "")),
    }
    with open(_state_dir() / "markers.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _session_start(cli: str) -> str:
    from .briefing import build_briefing
    from .sync import needs_sync, run_sync
    from .vault import Vault

    vault = Vault.find()
    notes: list[str] = []
    changed: list[str] = []
    try:
        if needs_sync(vault):
            result = run_sync(vault)
            if not result.ok:
                notes.append("Bron couldn't apply recent setup changes; the previous setup is still active. Problems:")
                notes += ["- " + issue.render(vault.root) for issue in result.issues if issue.level == "error"]
            elif result.report and (result.report.written or result.report.deleted):
                changed = result.report.written + result.report.deleted
                notes.append("Setup note for you (mention it only if the user asks about setup): recent changes in System/ were applied. Changes to models, permissions, connections and skills take effect from the next session.")
                if result.report.backup_dir:
                    notes.append(f"A hand-edited generated file was replaced; the edited copy is in {result.report.backup_dir.relative_to(vault.root)}.")
            notes += [f"Saved approvals: {issue.message}. Tell the user in one line." for issue in result.issues if issue.code == "approvals.import"]
    except Exception as exc:  # noqa: BLE001
        _log_error("session-start", cli, exc)
        notes.append(f"Bron couldn't check the setup ({exc.__class__.__name__}). Ask Bron to run `.bron/bin/bron check`.")
    try:
        from .runner import recover_orphans

        recover_orphans(vault)
    except Exception as exc:  # noqa: BLE001 - best effort, never fails the briefing
        _log_error("session-start", cli, exc)
    try:
        from .mentions import close_stale_chats

        close_stale_chats(vault)
    except Exception as exc:  # noqa: BLE001 - best effort, never fails the briefing
        _log_error("session-start", cli, exc)
    return build_briefing(vault, cli=cli, notes=notes, changed=changed)


def _ticket_updates() -> str:
    from .model import slug
    from .notifications import FILE, describe, take
    from .vault import Vault, VaultNotFound

    if os.environ.get("BRON_TICKET"):
        return ""  # a headless ticket run: the updates belong to the requester's own sessions
    try:
        vault = Vault.find()
    except VaultNotFound:
        return ""
    if not (vault.state_dir / FILE).is_file():
        return ""
    default_name = _default_agent(vault)
    agent = os.environ.get("BRON_AGENT") or default_name
    updates = take(vault, slug(agent), slug(default_name))
    if not updates:
        return ""
    shown = updates[:8]
    lines = ["Ticket updates since your last message:", *[f"- {_truncate_title(describe(u))}" for u in shown]]
    if len(updates) > 8:
        lines.append(f"- …and {len(updates) - 8} more: run `.bron/bin/bron ticket list`")
    lines.append("Read the ticket (.bron/bin/bron ticket show <id>) and tell the user what changed.")
    return "\n".join(lines) + "\n"


def _route(cli: str, payload: dict) -> str:
    """@-mentions: start the tagged agents now and tell the session's agent to wait for them."""
    if os.environ.get("BRON_TICKET"):
        return ""  # a headless ticket run never routes
    prompt = str(payload.get("prompt") or "")
    if "@" not in prompt:
        return ""
    from . import mentions
    from .vault import Vault, VaultNotFound

    try:
        vault = Vault.find()
    except VaultNotFound:
        return ""
    try:
        return mentions.route(
            vault,
            cli=cli,
            prompt=prompt,
            session_id=str(payload.get("session_id") or ""),
            transcript_path=str(payload.get("transcript_path") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - a trigger must never fail the message
        _log_error("user-prompt", cli, exc)
        return f"Bron couldn't pass the @-mention on this time ({exc.__class__.__name__}); answer the message yourself and say so.\n"


def _close_chats(cli: str, payload: dict) -> None:
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return
    try:
        from .mentions import close_session_chats
        from .vault import Vault

        close_session_chats(Vault.find(), f"{cli}:{session_id}")
    except Exception as exc:  # noqa: BLE001
        _log_error("session-end", cli, exc)


def _truncate_title(text: str, limit: int = 80) -> str:
    """Truncate text to limit chars, adding '…' if truncated."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _default_agent(vault) -> str:
    from . import frontmatter as fm

    try:
        return str(fm.read(vault.settings_file).meta.get("default_agent") or "Bron")
    except Exception:  # noqa: BLE001
        return "Bron"


def _log_error(event: str, cli: str, exc: Exception) -> None:
    try:
        with open(_state_dir() / "hook-errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {cli} {event} {exc.__class__.__name__}: {exc}\n")
    except Exception:  # noqa: BLE001
        pass
