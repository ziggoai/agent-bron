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
            # Plan 2 routes @-mentions from the prompt; for now just drain stdin.
            _payload(stdin)
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
    try:
        if needs_sync(vault):
            result = run_sync(vault)
            if not result.ok:
                notes.append("Bron couldn't apply recent setup changes; the previous setup is still active. Problems:")
                notes += ["- " + issue.render(vault.root) for issue in result.issues if issue.level == "error"]
            elif result.report and (result.report.written or result.report.deleted):
                notes.append("Bron applied recent setup changes. Some take effect from the next session.")
                if result.report.backup_dir:
                    notes.append(f"A hand-edited generated file was replaced; the edited copy is in {result.report.backup_dir.relative_to(vault.root)}.")
    except Exception as exc:  # noqa: BLE001
        _log_error("session-start", cli, exc)
        notes.append(f"Bron couldn't check the setup ({exc.__class__.__name__}). Ask Bron to run `.bron/bin/bron check`.")
    return build_briefing(vault, cli=cli, notes=notes)


def _log_error(event: str, cli: str, exc: Exception) -> None:
    try:
        with open(_state_dir() / "hook-errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {cli} {event} {exc.__class__.__name__}: {exc}\n")
    except Exception:  # noqa: BLE001
        pass
