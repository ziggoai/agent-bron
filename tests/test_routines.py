import copy
import os
from datetime import date

import pytest

from bron import frontmatter as fm
from bron.routines import (
    RoutineError,
    due_date,
    last_ended,
    load_runbooks,
    parse_list_items,
    period_bounds,
    period_of,
    refresh_tracking,
    start_period,
)
from vaultkit import write_md

RUNBOOK = {
    "cadence": "quarterly",
    "owner": "bron",
    "due": "45 days after period end",
    "lists": {
        "companies": "active portfolio companies of each fund in Carta (FMV > 0), grouped by fund",
        "funds": ["Fund I", "Fund II", "Fund III"],
    },
    "steps": [
        {"name": "Collect financials and KPIs", "for": "companies"},
        {"name": "Stacked ranking", "for": "once", "items": ["Sent to the investment team", "Back from the investment team"]},
        {"name": "One-pager", "for": "funds", "after": ["Collect financials and KPIs", "Stacked ranking"]},
    ],
}
COMPANIES = [("Fund I", "Company A"), ("Fund I", "Company B"), ("Fund II", "Company C")]


def add_routine(vault, name="Portco Monitoring", **changes):
    meta = {**copy.deepcopy(RUNBOOK), **changes}
    meta = {k: v for k, v in meta.items() if v is not None}
    return write_md(vault.routines_dir / name / "Runbook.md", meta, "## How to do each step\n")


def runbook(vault):
    runbooks, _ = load_runbooks(vault)
    return runbooks[0]


def test_a_runbook_loads(vault):
    add_routine(vault)
    runbooks, issues = load_runbooks(vault)
    rb = runbooks[0]
    assert issues == []
    assert rb.name == "Portco Monitoring" and rb.cadence == "quarterly" and rb.owner == "bron"
    assert [s.name for s in rb.steps] == ["Collect financials and KPIs", "Stacked ranking", "One-pager"]
    assert rb.steps[2].after == ["Collect financials and KPIs", "Stacked ranking"] and rb.steps[0].for_ == "companies"
    assert rb.lists["funds"] == ["Fund I", "Fund II", "Fund III"] and isinstance(rb.lists["companies"], str)


def test_runbook_problems_are_reported(vault):
    add_routine(vault, "Weekly", cadence="weekly")
    add_routine(vault, "Broken", owner=None, steps=[
        {"name": "A", "for": "missing"},
        {"name": "B", "after": ["C"]},
        {"name": "C"},
        {"name": "c"},
        {"for": "funds"},
    ])
    runbooks, issues = load_runbooks(vault)
    assert [rb.name for rb in runbooks] == ["Broken"]
    codes = {issue.code for issue in issues}
    assert {"routine.cadence", "routine.step-list", "routine.step-after", "routine.step-duplicate", "routine.step", "routine.owner"} <= codes
    assert next(i for i in issues if i.code == "routine.owner").level == "warning"


def test_periods():
    assert period_of("monthly", date(2026, 9, 30)) == "2026-09"
    assert period_of("quarterly", date(2026, 10, 1)) == "2026-Q4"
    assert period_of("annual", date(2026, 3, 1)) == "2026"
    assert period_bounds("quarterly", "2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert period_bounds("monthly", "2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert period_bounds("monthly", "2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_bounds("annual", "2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert last_ended("quarterly", date(2026, 10, 1)) == "2026-Q3"
    assert last_ended("monthly", date(2026, 1, 15)) == "2025-12"
    assert last_ended("annual", date(2026, 3, 1)) == "2025"
    for cadence, name in (("quarterly", "2026-Q5"), ("monthly", "2026-13"), ("annual", "26"), ("quarterly", "2026-09")):
        with pytest.raises(ValueError):
            period_bounds(cadence, name)


def test_due_dates():
    assert due_date("45 days after period end", date(2026, 9, 30)) == date(2026, 11, 14)
    assert due_date("1 day after the period end", date(2026, 9, 30)) == date(2026, 10, 1)
    assert due_date("before the quarterly meeting", date(2026, 9, 30)) is None
    assert due_date("", date(2026, 9, 30)) is None


def test_list_files():
    text = "Fund I: Company A\n- Fund I: Company B\n\n# a note\nCompany C\n"
    assert parse_list_items(text) == [("Fund I", "Company A"), ("Fund I", "Company B"), ("", "Company C")]


def test_starting_a_period_writes_the_tracking_note(vault):
    add_routine(vault)
    path = start_period(vault, runbook(vault), "2026-Q3", {"companies": COMPANIES})
    assert path == vault.routines_dir / "Portco Monitoring" / "2026-Q3" / "Tracking.md"
    doc = fm.read(path)
    assert doc.meta["routine"] == "Portco Monitoring" and doc.meta["period"] == "2026-Q3"
    assert str(doc.meta["due"]) == "2026-11-14" and doc.meta["status"] == "todo"
    assert doc.meta["progress"] == "Collect financials and KPIs 0/3 · Stacked ranking 0/2 · One-pager waiting"
    assert doc.body == (
        "## Collect financials and KPIs\n### Fund I\n- [ ] Company A\n- [ ] Company B\n### Fund II\n- [ ] Company C\n\n"
        "## Stacked ranking\n- [ ] Sent to the investment team\n- [ ] Back from the investment team\n\n"
        "## One-pager\n- [ ] Fund I\n- [ ] Fund II\n- [ ] Fund III\n"
    )


def test_starting_needs_source_lists_a_valid_period_and_happens_once(vault):
    add_routine(vault)
    rb = runbook(vault)
    with pytest.raises(RoutineError, match="comes from a source"):
        start_period(vault, rb, "2026-Q3", {})
    with pytest.raises(RoutineError, match="isn't a quarterly period"):
        start_period(vault, rb, "2026-Q5", {"companies": COMPANIES})
    with pytest.raises(RoutineError, match="is empty"):
        start_period(vault, rb, "2026-Q3", {"companies": []})
    start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})
    with pytest.raises(RoutineError, match="has already started"):
        start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})


def tick(path, *items):
    text = path.read_text(encoding="utf-8")
    for item in items:
        text = text.replace(f"- [ ] {item}\n", f"- [x] {item}\n", 1)
    path.write_text(text, encoding="utf-8")


def test_progress_counts_ticks_groups_and_waiting_steps(vault):
    add_routine(vault)
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})
    text = path.read_text(encoding="utf-8")
    text = text.replace("- [ ] Company A\n", "- [x] Company A: received 12 Oct\n").replace("- [ ] Company C\n", "* [X] Company C\n")
    path.write_text(text, encoding="utf-8")
    tick(path, "Sent to the investment team", "Back from the investment team")
    body = fm.read(path).body
    state = refresh_tracking(path, rb)
    assert state.status == "in-progress"
    assert state.progress == "Collect financials and KPIs 2/3 · Stacked ranking 2/2 · One-pager waiting"
    assert fm.read(path).meta["progress"] == state.progress and fm.read(path).body == body
    tick(path, "Company B")
    assert refresh_tracking(path, rb).progress == "Collect financials and KPIs 3/3 · Stacked ranking 2/2 · One-pager 0/3"
    tick(path, "Fund I", "Fund II", "Fund III")
    assert refresh_tracking(path, rb).status == "done"


def test_refresh_only_writes_when_something_changed(vault):
    add_routine(vault)
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})
    refresh_tracking(path, rb)
    before = os.stat(path).st_mtime_ns
    refresh_tracking(path, rb)
    assert os.stat(path).st_mtime_ns == before


def test_a_runbook_without_steps_is_one_checklist(vault):
    write_md(vault.routines_dir / "Board Pack" / "Runbook.md", {"cadence": "monthly", "owner": "bron", "lists": {"items": ["Deck", "Minutes"]}})
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-09", {})
    assert fm.read(path).body == "## Board Pack\n- [ ] Deck\n- [ ] Minutes\n"


# ---- final review ----

def test_a_section_the_user_adds_is_ignored_by_status_and_progress(vault):
    steps = [{"name": "Close", "for": "funds"}]
    write_md(vault.routines_dir / "Close" / "Runbook.md", {"cadence": "monthly", "owner": "bron", "lists": {"funds": ["Fund I"]}, "steps": steps}, "")
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-09", {})
    text = path.read_text(encoding="utf-8").replace("- [ ] Fund I", "- [x] Fund I")
    path.write_text(text + "\n## Notes\nBank was late.\n- [ ] ask about fees\n", encoding="utf-8")
    state = refresh_tracking(path, rb)
    assert state.status == "done" and state.progress == "Close 1/1"
    assert "Bank was late." in path.read_text(encoding="utf-8")


def test_refresh_reads_the_tracking_note_once(vault, monkeypatch):
    from bron import routines

    add_routine(vault)
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})
    reads = []
    real = routines.fm.read
    monkeypatch.setattr(routines.fm, "read", lambda p: reads.append(p) or real(p))
    refresh_tracking(path, rb)
    assert reads == [path]


def test_an_absurd_due_rule_has_no_date():
    assert due_date("99999999999 days after period end", date(2026, 9, 30)) is None
    assert due_date("3000000 days after period end", date(2026, 9, 30)) is None


def test_a_due_date_given_at_start_wins_over_the_runbook_rule(vault):
    add_routine(vault, due="before the quarterly meeting")
    path = start_period(vault, runbook(vault), "2026-Q3", {"companies": COMPANIES}, due=date(2026, 11, 20))
    assert str(fm.read(path).meta["due"]) == "2026-11-20"
