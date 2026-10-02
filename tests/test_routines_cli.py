from datetime import date

import yaml

from bron.briefing import build_briefing
from bron.check import run_checks
from bron.cli import main
from bron.loader import load
from bron.routines import briefing_lines, load_runbooks, start_period
from test_routines import COMPANIES, add_routine, tick
from vaultkit import add_agent


def lines(vault, agent="bron", today=date(2026, 10, 1)):
    return briefing_lines(vault, load(vault), agent, today)


def started(vault):
    rb = load_runbooks(vault)[0][0]
    return rb, start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})


def test_the_briefing_offers_to_start_then_shows_progress_and_due_dates(vault):
    add_routine(vault)
    assert lines(vault) == ["Portco Monitoring 2026-Q3: can start (due 14 Nov 2026). Offer to set it up (routines skill)."]
    _, path = started(vault)
    tick(path, "Company A", "Company C", "Sent to the investment team", "Back from the investment team")
    progress = "Collect financials and KPIs 2/3 · Stacked ranking 2/2 · One-pager waiting"
    assert lines(vault, today=date(2026, 11, 2)) == [f"Portco Monitoring 2026-Q3: {progress}; due in 12 days"]
    assert lines(vault, today=date(2026, 11, 13)) == [f"Portco Monitoring 2026-Q3: {progress}; due tomorrow"]
    assert lines(vault, today=date(2026, 11, 14)) == [f"Portco Monitoring 2026-Q3: {progress}; due today"]
    assert lines(vault, today=date(2026, 11, 17)) == [f"Portco Monitoring 2026-Q3: {progress}; overdue by 3 days"]
    tick(path, "Company B", "Fund I", "Fund II", "Fund III")
    assert lines(vault, today=date(2026, 11, 2)) == []


def test_routines_follow_their_owner(vault):
    add_agent(vault, "CFO")
    add_routine(vault, owner="CFO")
    assert lines(vault, "bron") == [] and len(lines(vault, "cfo")) == 1
    add_routine(vault, "Orphan", owner="Ghost")
    assert [line.split(":")[0] for line in lines(vault, "bron")] == ["Orphan 2026-Q3"]


def test_the_session_briefing_has_a_routines_block_capped_at_eight(vault):
    for index in range(10):
        add_routine(vault, f"Routine {index:02d}")
    text = build_briefing(vault, cli="claude", today=date(2026, 10, 1))
    block = text.split("## Routines\n", 1)[1]
    assert block.startswith("- Routine 00 2026-Q3: can start (due 14 Nov 2026).")
    assert block.count("\n- Routine") == 7 and "- …and 2 more: run `.bron/bin/bron routine list`" in block


def test_routine_commands(vault, monkeypatch, capsys):
    monkeypatch.chdir(vault.root)
    monkeypatch.setattr("bron.routines.today", lambda: date(2026, 10, 1))
    add_routine(vault)
    (vault.root / "companies.txt").write_text("Fund I: Company A\nFund I: Company B\nFund II: Company C\n", encoding="utf-8")
    assert main(["routine", "list"]) == 0
    assert capsys.readouterr().out == "Portco Monitoring 2026-Q3: not started (due 14 Nov 2026)\n"
    assert main(["routine", "start", "portco monitoring", "--list", "companies=companies.txt"]) == 0
    assert capsys.readouterr().out == "Started Portco Monitoring 2026-Q3: Routines/Portco Monitoring/2026-Q3/Tracking.md\n"
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q3", "--list", "companies=companies.txt"]) == 1
    assert "has already started" in capsys.readouterr().out
    assert main(["routine", "list"]) == 0
    assert capsys.readouterr().out == "Portco Monitoring 2026-Q3 [todo] Collect financials and KPIs 0/3 · Stacked ranking 0/2 · One-pager waiting; due in 44 days\n"
    assert main(["routine", "refresh", "Portco Monitoring"]) == 0
    assert "Portco Monitoring 2026-Q3 [todo]" in capsys.readouterr().out
    assert main(["routine", "start", "Nope"]) == 1
    assert capsys.readouterr().out == "There's no routine called 'Nope'. Routines: Portco Monitoring\n"
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q2", "--list", "companies"]) == 1
    assert "--list needs NAME=FILE" in capsys.readouterr().out
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q2", "--list", "companies=missing.txt"]) == 1
    assert "Couldn't read a list file" in capsys.readouterr().out


def test_runbook_problems_show_in_the_health_check_but_never_stop_a_sync(vault):
    add_routine(vault, cadence="weekly")
    add_routine(vault, "Orphan", owner="Ghost")
    cfg = load(vault)
    codes = {issue.code for issue in run_checks(cfg)}
    assert {"routine.cadence", "routine.owner-unknown"} <= codes
    assert not {"routine.cadence", "routine.owner-unknown"} & {i.code for i in run_checks(cfg, include_environment=False)}


def test_the_routines_board_lists_tracking_notes(vault):
    board = yaml.safe_load((vault.routines_dir / "Board.base").read_text(encoding="utf-8"))
    assert 'file.basename == "Tracking"' in str(board["filters"])
    assert board["views"][0]["groupBy"]["property"] == "status"
    assert board["views"][0]["order"] == ["routine", "period", "status", "progress", "due"]


def test_the_routines_skill_and_manual_are_published(vault):
    cfg = load(vault)
    assert "routines" in cfg.skills
    index = (vault.core_manual / "index.md").read_text(encoding="utf-8")
    assert "](routines.md)" in index and (vault.core_manual / "routines.md").is_file()


def test_refresh_survives_a_damaged_tracking_note(vault, monkeypatch, capsys):
    monkeypatch.chdir(vault.root)
    add_routine(vault)
    _, path = started(vault)
    path.write_text("---\nstatus: [unclosed\n---\nbody\n", encoding="utf-8")
    assert main(["routine", "refresh"]) == 0
    assert "Portco Monitoring 2026-Q3: its Tracking note can't be read (Routines/Portco Monitoring/2026-Q3/Tracking.md)" in capsys.readouterr().out


def test_start_reads_a_latin1_list_file(vault, monkeypatch, capsys):
    monkeypatch.chdir(vault.root)
    add_routine(vault)
    (vault.root / "companies.txt").write_bytes("Fund I: Société A\n".encode("latin-1"))
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q3", "--list", "companies=companies.txt"]) == 0
    tracking = vault.routines_dir / "Portco Monitoring" / "2026-Q3" / "Tracking.md"
    assert "Société A" in tracking.read_text(encoding="utf-8")


# ---- final review ----

def start_q3(vault, *extra, data="Fund I: Company A\n".encode("utf-8")):
    (vault.root / "companies.txt").write_bytes(data)
    return main(["routine", "start", "Portco Monitoring", "--period", "2026-Q3", "--list", "companies=companies.txt", *extra])


def q3_note(vault):
    return vault.routines_dir / "Portco Monitoring" / "2026-Q3" / "Tracking.md"


def test_start_takes_a_due_date_for_rules_bron_cannot_work_out(vault, monkeypatch, capsys):
    from bron import frontmatter as fm

    monkeypatch.chdir(vault.root)
    add_routine(vault, due="two weeks before the LP meeting")
    assert start_q3(vault, "--due", "2026-11-14") == 0
    assert str(fm.read(q3_note(vault)).meta["due"]) == "2026-11-14"


def test_a_bad_due_date_is_a_plain_error(vault, monkeypatch, capsys):
    monkeypatch.chdir(vault.root)
    add_routine(vault)
    assert start_q3(vault, "--due", "14 Nov") == 1
    assert capsys.readouterr().out == "--due needs a date written as YYYY-MM-DD, like 2026-11-14 (got '14 Nov')\n"
    assert not q3_note(vault).exists()


def test_list_files_with_a_byte_order_mark_or_in_utf16_are_read(vault, monkeypatch, capsys):
    from bron import frontmatter as fm

    monkeypatch.chdir(vault.root)
    add_routine(vault)
    assert start_q3(vault, data="Fund I: Company A\nFund II: Company B\n".encode("utf-8-sig")) == 0
    assert fm.read(q3_note(vault)).body.startswith("## Collect financials and KPIs\n### Fund I\n- [ ] Company A\n")
    add_routine(vault, "Second")
    (vault.root / "companies.txt").write_bytes("Fund I: Société A\n".encode("utf-16"))
    assert main(["routine", "start", "Second", "--period", "2026-Q3", "--list", "companies=companies.txt"]) == 0
    assert "- [ ] Société A\n" in (vault.routines_dir / "Second" / "2026-Q3" / "Tracking.md").read_text(encoding="utf-8")


def test_a_list_the_runbook_does_not_have_is_a_plain_error(vault, monkeypatch, capsys):
    monkeypatch.chdir(vault.root)
    add_routine(vault)
    (vault.root / "foo.txt").write_text("x\n", encoding="utf-8")
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q3", "--list", "foo=foo.txt"]) == 1
    assert capsys.readouterr().out == "Portco Monitoring has no list called 'foo'. Its lists: companies, funds\n"
    assert not q3_note(vault).exists()


def test_the_health_check_warns_about_a_tracking_note_it_cannot_read(vault):
    add_routine(vault)
    _, path = started(vault)
    assert "routine.tracking-unreadable" not in {i.code for i in run_checks(load(vault))}
    path.write_text("---\nstatus: [unclosed\n---\nbody\n", encoding="utf-8")
    issue = next(i for i in run_checks(load(vault)) if i.code == "routine.tracking-unreadable")
    assert issue.level == "warning" and issue.path == path and "Portco Monitoring 2026-Q3" in issue.message
