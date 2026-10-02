"""Routines: repeating work tracked per period (Routines/<Routine>/Runbook.md and <Period>/Tracking.md)."""
from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import frontmatter as fm
from .model import Issue, slug
from .vault import Vault

CADENCES = ("monthly", "quarterly", "annual")
ONCE = "once"
TRACKING = "Tracking.md"
_DUE = re.compile(r"^\s*(\d+)\s+days?\s+after\s+(?:the\s+)?period\s+end\s*$", re.I)
_BOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+")


class RoutineError(ValueError):
    """A routine problem to show the user as it is."""


@dataclass
class Step:
    name: str
    for_: str = ONCE
    after: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)


@dataclass
class Runbook:
    name: str
    path: Path
    cadence: str
    owner: str = ""
    due: str = ""
    lists: dict[str, list[str] | str] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)

    @property
    def folder(self) -> Path:
        return self.path.parent


@dataclass
class StepCount:
    name: str
    done: int = 0
    total: int = 0


@dataclass
class TrackingState:
    meta: dict
    status: str
    progress: str


# ---- runbooks ----

def load_runbooks(vault: Vault) -> tuple[list[Runbook], list[Issue]]:
    runbooks: list[Runbook] = []
    issues: list[Issue] = []
    folder = vault.routines_dir
    if not folder.is_dir():
        return runbooks, issues
    for sub in sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")):
        path = sub / "Runbook.md"
        if not path.is_file():
            continue
        try:
            meta = fm.read(path).meta
        except (fm.FrontmatterError, OSError, UnicodeDecodeError) as exc:
            issues.append(Issue("error", "routine.unreadable", f"Bron can't read this runbook: {exc}", path))
            continue
        runbook = _runbook(sub.name, path, meta, issues)
        if runbook is not None:
            runbooks.append(runbook)
    return runbooks, issues


def _names(value) -> list[str] | None:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
        return [str(v).strip() for v in value if str(v).strip()]
    return None


def _runbook(name: str, path: Path, meta: dict, issues: list[Issue]) -> Runbook | None:
    def bad(code: str, message: str, level: str = "error") -> None:
        issues.append(Issue(level, code, message, path))

    cadence = str(meta.get("cadence") or "").strip().lower()
    if cadence not in CADENCES:
        bad("routine.cadence", f"'cadence' should be monthly, quarterly or annual (it is '{meta.get('cadence') or ''}')")
        return None
    lists: dict[str, list[str] | str] = {}
    raw_lists = meta.get("lists") or {}
    if not isinstance(raw_lists, dict):
        bad("routine.lists", "'lists' should name each list, like 'funds: [Fund I, Fund II]'")
        raw_lists = {}
    for key, value in raw_lists.items():
        if isinstance(value, str) and value.strip():
            lists[str(key)] = value.strip()
        elif (items := _names(value)) is not None and isinstance(value, list):
            lists[str(key)] = items
        else:
            bad("routine.lists", f"The list '{key}' should be a list of items or a sentence saying where its items come from")
    steps: list[Step] = []
    raw_steps = meta.get("steps")
    if raw_steps is None:
        steps = [Step(name=name, for_=next(iter(lists), ONCE))]
    elif not isinstance(raw_steps, list):
        bad("routine.step", "'steps' should be a list of steps, each with a name")
    else:
        seen: list[str] = []
        for index, raw in enumerate(raw_steps, 1):
            if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
                bad("routine.step", f"Step {index} needs a name")
                continue
            step_name = str(raw["name"]).strip()
            if step_name.lower() in (s.lower() for s in seen):
                bad("routine.step-duplicate", f"Two steps are called '{step_name}'")
                continue
            for_ = str(raw.get("for") or ONCE).strip()
            if for_ != ONCE and for_ not in lists:
                bad("routine.step-list", f"The step '{step_name}' is done for '{for_}', which isn't one of the lists")
            after = _names(raw.get("after"))
            if after is None:
                bad("routine.step-after", f"'after' in the step '{step_name}' should be a list of earlier steps")
                after = []
            for other in after:
                if other.lower() not in (s.lower() for s in seen):
                    bad("routine.step-after", f"The step '{step_name}' waits for '{other}', which isn't an earlier step")
            items = _names(raw.get("items")) or []
            steps.append(Step(step_name, for_, after, items))
            seen.append(step_name)
    owner = str(meta.get("owner") or "").strip()
    if not owner:
        bad("routine.owner", f"The routine '{name}' has no 'owner'; the default agent looks after it", "warning")
    return Runbook(name, path, cadence, owner, str(meta.get("due") or "").strip(), lists, steps)


def check_runbook(name: str, meta: dict) -> tuple["Runbook | None", list[Issue]]:
    """Validate a runbook's settings before it is written (the same checks `bron check` runs)."""
    issues: list[Issue] = []
    runbook = _runbook(name, Path("Runbook.md"), meta, issues)
    return runbook, issues


# ---- periods ----

def period_of(cadence: str, day: date) -> str:
    if cadence == "monthly":
        return f"{day.year}-{day.month:02d}"
    if cadence == "quarterly":
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    return f"{day.year}"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def period_bounds(cadence: str, name: str) -> tuple[date, date]:
    """First and last day of a period ('2026-09', '2026-Q3', '2026'). ValueError for a name that doesn't fit."""
    patterns = {"monthly": r"(\d{4})-(\d{2})", "quarterly": r"(\d{4})-Q([1-4])", "annual": r"(\d{4})"}
    match = re.fullmatch(patterns.get(cadence, "$^"), name.strip())
    if not match:
        raise ValueError(f"'{name}' isn't a {cadence} period")
    year = int(match.group(1))
    if cadence == "annual":
        return date(year, 1, 1), date(year, 12, 31)
    number = int(match.group(2))
    if cadence == "monthly":
        if not 1 <= number <= 12:
            raise ValueError(f"'{name}' isn't a {cadence} period")
        return date(year, number, 1), _month_end(year, number)
    first = 3 * (number - 1) + 1
    return date(year, first, 1), _month_end(year, first + 2)


def last_ended(cadence: str, today: date) -> str:
    """The latest period that has ended: the one to run now (Q3's run starts on 1 October)."""
    start, _ = period_bounds(cadence, period_of(cadence, today))
    return period_of(cadence, start - timedelta(days=1))


def due_date(rule: str, period_end: date) -> date | None:
    match = _DUE.match(rule or "")
    if not match:
        return None
    try:
        return period_end + timedelta(days=int(match.group(1)))
    except (OverflowError, ValueError):
        return None  # a day count too big to be a date


# ---- tracking notes ----

def parse_list_items(text: str) -> list[tuple[str, str]]:
    """One item per line, optionally 'Group: item'. Blank lines and '# notes' are skipped."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line or line.startswith("#"):
            continue
        group, sep, item = line.partition(": ")
        out.append((group.strip(), item.strip()) if sep and group.strip() and item.strip() else ("", line))
    return out


def _step_lines(step: Step, items: list[tuple[str, str]]) -> list[str]:
    lines = [f"## {step.name}"]
    group = ""
    for item_group, item in items:
        if item_group != group:
            if item_group:
                lines.append(f"### {item_group}")
            group = item_group
        lines.append(f"- [ ] {item}")
    return lines


def start_period(vault: Vault, runbook: Runbook, period: str, lists: dict[str, list[tuple[str, str]]], *, due: date | None = None) -> Path:
    """Create <Routine>/<period>/Tracking.md with one checklist per step. `due` overrides the runbook's due rule."""
    try:
        _, end = period_bounds(runbook.cadence, period)
    except ValueError as exc:
        raise RoutineError(str(exc)) from exc
    path = runbook.folder / period / TRACKING
    if path.exists():
        raise RoutineError(f"{runbook.name} {period} has already started ({path.relative_to(vault.root)})")
    sections: list[str] = []
    for step in runbook.steps:
        if step.for_ == ONCE:
            items = [("", item) for item in (step.items or [step.name])]
        elif step.for_ in lists:
            items = lists[step.for_]
        elif isinstance(runbook.lists.get(step.for_), list):
            items = [("", item) for item in runbook.lists[step.for_]]
        else:
            source = runbook.lists.get(step.for_, "")
            raise RoutineError(f"The list '{step.for_}' comes from a source ({source}); give it with --list {step.for_}=<file>")
        if not items:
            raise RoutineError(f"The list '{step.for_}' is empty")
        sections.append("\n".join(_step_lines(step, items)))
    meta: dict = {"routine": runbook.name, "period": period, "status": "todo"}
    due = due or due_date(runbook.due, end)
    if due:
        meta["due"] = due.isoformat()
    meta["progress"] = ""
    fm.write(path, fm.Document(meta, "\n\n".join(sections) + "\n"))
    refresh_tracking(path, runbook)
    return path


def count_steps(body: str, runbook: Runbook) -> list[StepCount]:
    """Ticks per step section. Only `##` sections named like a runbook step count: any other section the
    user adds (for example `## Notes`) is ignored, checkboxes and all."""
    names = {step.name.lower() for step in runbook.steps}
    steps: list[StepCount] = []
    current: StepCount | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            current = StepCount(name) if name.lower() in names else None
            if current is not None:
                steps.append(current)
        elif current is not None and (match := _BOX.match(line)):
            current.total += 1
            if match.group(1) in "xX":
                current.done += 1
    return steps


def refresh_tracking(path: Path, runbook: Runbook) -> TrackingState:
    """Recount the checklists and update status and progress (never the checkboxes). Writes only on change."""
    doc = fm.read(path)
    steps = count_steps(doc.body, runbook)
    complete = {s.name.lower() for s in steps if s.total and s.done == s.total}
    by_name = {s.name.lower(): s for s in runbook.steps}
    parts: list[str] = []
    for count in steps:
        rule = by_name.get(count.name.lower())
        waiting = rule is not None and count.done == 0 and any(a.lower() not in complete for a in rule.after)
        parts.append(f"{count.name} waiting" if waiting else f"{count.name} {count.done}/{count.total}")
    progress = " · ".join(parts)
    if steps and all(s.total and s.done == s.total for s in steps):
        status = "done"
    elif any(s.done for s in steps):
        status = "in-progress"
    else:
        status = "todo"
    if doc.meta.get("status") != status or doc.meta.get("progress") != progress:
        doc.meta["status"], doc.meta["progress"] = status, progress
        tmp = path.with_name(f"{path.name}.{os.getpid()}.bron-tmp")
        tmp.write_text(fm.dump(doc), encoding="utf-8")
        tmp.replace(path)
    return TrackingState(doc.meta, status, progress)


def tracking_notes(runbook: Runbook) -> list[Path]:
    return sorted(runbook.folder.glob(f"*/{TRACKING}"))


# ---- what's due ----

def today() -> date:
    return date.today()


def format_day(day: date) -> str:
    return f"{day.day} {day.strftime('%b %Y')}"


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def due_text(value, today_: date) -> str:
    due = _as_date(value)
    if due is None:
        return ""
    days = (due - today_).days
    if days > 1:
        return f"; due in {days} days"
    if days == 1:
        return "; due tomorrow"
    if days == 0:
        return "; due today"
    return f"; overdue by {-days} day{'s' if days < -1 else ''}"


def find_runbook(runbooks: list[Runbook], name: str) -> Runbook:
    for runbook in runbooks:
        if runbook.name.lower() == name.strip().lower():
            return runbook
    known = ", ".join(r.name for r in runbooks) or "none yet"
    raise RoutineError(f"There's no routine called '{name}'. Routines: {known}")


def _period_lines(runbook: Runbook, today_: date, *, briefing: bool) -> list[str]:
    out: list[str] = []
    for path in tracking_notes(runbook):
        period = path.parent.name
        try:
            state = refresh_tracking(path, runbook)
        except (fm.FrontmatterError, OSError, UnicodeDecodeError):
            out.append(f"{runbook.name} {period}: its Tracking note can't be read (Routines/{runbook.folder.name}/{period}/{TRACKING})")
            continue
        due = due_text(state.meta.get("due"), today_) if state.status != "done" else ""
        if briefing:
            if state.status != "done":
                out.append(f"{runbook.name} {period}: {state.progress}{due}")
        else:
            out.append(f"{runbook.name} {period} [{state.status}] {state.progress}{due}")
    period = last_ended(runbook.cadence, today_)
    if not (runbook.folder / period / TRACKING).exists():
        due = due_date(runbook.due, period_bounds(runbook.cadence, period)[1])
        when = f" (due {format_day(due)})" if due else ""
        if briefing:
            out.append(f"{runbook.name} {period}: can start{when}. Offer to set it up (routines skill).")
        else:
            out.append(f"{runbook.name} {period}: not started{when}")
    return out


def status_lines(runbooks: list[Runbook], today_: date) -> list[str]:
    return [line for runbook in runbooks for line in _period_lines(runbook, today_, briefing=False)]


def briefing_lines(vault: Vault, cfg, agent_key: str, today_: date) -> list[str]:
    """Due and in-progress periods of the routines this agent owns (the default agent also gets ownerless ones)."""
    runbooks, _ = load_runbooks(vault)
    default_key = cfg.default_agent.key if cfg.default_agent else ""
    out: list[str] = []
    for runbook in runbooks:
        owner = slug(runbook.owner) if runbook.owner else ""
        if owner == agent_key or (agent_key == default_key and owner not in cfg.agents):
            out += _period_lines(runbook, today_, briefing=True)
    return out
