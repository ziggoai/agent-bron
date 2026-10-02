import pytest

from bron import frontmatter as fm
from bron.agent_setup import rename_agent, restore_agent, retire_agent
from bron.cli import main
from bron.loader import load
from bron.setup import SetupError, apply
from bron.sync import run_sync
from bron.tickets import editing, load_ticket, new_ticket
from test_routines import add_routine
from vaultkit import add_agent, set_meta


@pytest.fixture
def team(vault):
    add_agent(vault, "CFO")
    add_agent(vault, "Analyst", reports_to="CFO")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", can_assign_to=["CFO"])
    set_meta(vault.agents_dir / "CFO" / "Agent.md", can_assign_to=["Analyst"])
    return vault


def meta(vault, name, archived=False):
    folder = vault.system / "Archive" / "Agents" if archived else vault.agents_dir
    return fm.read(folder / name / "Agent.md").meta


def test_rename_updates_every_reference_and_open_tickets(team):
    add_routine(team, owner="CFO")
    open_ticket = new_ticket(team, title="Q3", assignee="cfo", request="x", requested_by="bron")
    closed = new_ticket(team, title="Old", assignee="cfo", request="x", requested_by="bron", status="done")
    change = rename_agent(load(team), "cfo", "Finance")
    assert change.summary[0] == "Rename CFO to Finance."
    apply(team, change)
    assert meta(team, "Finance")["name"] == "Finance" and not (team.agents_dir / "CFO").exists()
    assert meta(team, "Bron")["can_assign_to"] == ["Finance"] and meta(team, "Analyst")["reports_to"] == "Finance"
    assert fm.read(team.routines_dir / "Portco Monitoring" / "Runbook.md").meta["owner"] == "Finance"
    assert load_ticket(open_ticket.path).assignee == "finance" and load_ticket(closed.path).assignee == "cfo"
    assert (team.root / ".claude" / "agents" / "finance.md").is_file() and not (team.root / ".claude" / "agents" / "cfo.md").exists()


def test_renaming_the_default_agent_updates_settings_and_still_syncs(team):
    apply(team, rename_agent(load(team), "Bron", "Ava"))
    assert fm.read(team.settings_file).meta["default_agent"] == "Ava"
    assert meta(team, "CFO")["reports_to"] == "Ava"
    cfg = load(team)
    assert cfg.default_agent.name == "Ava" and run_sync(team).ok


def test_rename_refuses_bad_or_taken_names(team):
    for bad in ("Analyst", "a/b", "CFO", "cfo"):
        with pytest.raises(SetupError):
            rename_agent(load(team), "CFO", bad)


def test_retire_hands_over_work_and_archives(team):
    add_routine(team, owner="CFO")
    work = new_ticket(team, title="Q3", assignee="cfo", request="x", requested_by="bron")
    chat = new_ticket(team, title="Chat", assignee="cfo", request="hi", requested_by="bron", kind="chat", status="in-review")
    change = retire_agent(load(team), "CFO")
    assert change.summary[0] == "Retire CFO."
    apply(team, change)
    assert (team.system / "Archive" / "Agents" / "CFO" / "Agent.md").is_file() and not (team.agents_dir / "CFO").exists()
    assert load_ticket(work.path).assignee == "bron" and "handed over from CFO to Bron" in "\n".join(load_ticket(work.path).thread)
    assert load_ticket(chat.path).status == "done"
    assert meta(team, "Bron")["can_assign_to"] == [] and meta(team, "Analyst")["reports_to"] == "Bron"
    assert fm.read(team.routines_dir / "Portco Monitoring" / "Runbook.md").meta["owner"] == "Bron"


def test_retire_refuses_the_main_agent_and_a_busy_agent(team):
    with pytest.raises(SetupError, match="main agent"):
        retire_agent(load(team), "Bron")
    busy = new_ticket(team, title="Q3", assignee="cfo", request="x", requested_by="bron")
    with editing(team, busy.id) as current:
        current.status = "in-progress"
    with pytest.raises(SetupError, match="working on"):
        retire_agent(load(team), "CFO")
    assert (team.agents_dir / "CFO" / "Agent.md").is_file()


def test_bring_back_restores_the_agent(team):
    apply(team, retire_agent(load(team), "Analyst", hand_to="Bron"))
    change = restore_agent(load(team), "analyst")
    assert change.summary[0] == "Bring back Analyst."
    apply(team, change)
    assert meta(team, "Analyst")["reports_to"] == "CFO" and "Analyst" in meta(team, "CFO")["can_assign_to"]
    with pytest.raises(SetupError, match="no retired agent"):
        restore_agent(load(team), "Nobody")


def test_bringing_back_an_agent_whose_boss_is_gone_reports_to_the_main_agent(team):
    apply(team, retire_agent(load(team), "Analyst"))
    apply(team, retire_agent(load(team), "CFO"))
    apply(team, restore_agent(load(team), "Analyst"))
    assert meta(team, "Analyst")["reports_to"] == "Bron" and "Analyst" in meta(team, "Bron")["can_assign_to"]


def test_the_lifecycle_commands(team, monkeypatch, capsys):
    monkeypatch.chdir(team.root)
    assert main(["agent", "retire", "Analyst", "--preview"]) == 0
    assert capsys.readouterr().out.startswith("Retire Analyst.") and (team.agents_dir / "Analyst").is_dir()
    assert main(["agent", "retire", "Analyst"]) == 0
    assert "say 'bring back Analyst'" in capsys.readouterr().out
    assert main(["agent", "restore", "Analyst"]) == 0
    assert main(["agent", "rename", "Analyst", "Researcher One"]) == 0
    assert (team.agents_dir / "Researcher One" / "Agent.md").is_file()


def test_retire_repoints_requests_and_explains_chats_and_bring_back(team):
    asked = new_ticket(team, title="Ask", assignee="analyst", request="x", requested_by="cfo")
    new_ticket(team, title="Chat", assignee="cfo", request="hi", requested_by="bron", kind="chat", status="in-review")
    change = retire_agent(load(team), "CFO")
    text = "\n".join(change.summary)
    assert "Its 1 open chat will be ended." in text
    assert "Tickets it asked others for now report back to Bron: 1." in text
    assert "you can bring it back later (it rejoins its boss's team; other team lists stay as they are now)." in text
    apply(team, change)
    ticket = load_ticket(asked.path)
    assert ticket.requested_by == "bron" and "requested by CFO, now followed up by Bron (CFO retired)" in "\n".join(ticket.thread)
    restored = restore_agent(load(team), "CFO")
    assert "Other team lists it was on aren't restored; ask if you want it added back." in restored.summary


def test_rename_refuses_a_busy_agent_and_mentions_skills(team):
    busy = new_ticket(team, title="Q3", assignee="cfo", request="x", requested_by="bron")
    with editing(team, busy.id) as current:
        current.status = "in-progress"
    with pytest.raises(SetupError, match="rename it once"):
        rename_agent(load(team), "CFO", "Finance")
    skill = team.agents_dir / "Analyst" / "Skills" / "tally" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: tally\ndescription: Count things\n---\nCount.\n", encoding="utf-8")
    change = rename_agent(load(team), "Analyst", "Scout")
    assert "Its own skills are renamed to scout-tally." in change.summary


def test_retire_and_rename_refuse_while_a_ticket_they_would_rewrite_is_being_worked_on(team):
    asked = new_ticket(team, title="Ask", assignee="analyst", request="x", requested_by="cfo")
    with editing(team, asked.id) as current:
        current.status = "in-progress"
    before = asked.path.read_text(encoding="utf-8")
    with pytest.raises(SetupError, match=f"{asked.id} is being worked on right now; try again once it's finished."):
        retire_agent(load(team), "CFO")
    with pytest.raises(SetupError, match=f"{asked.id} is being worked on right now"):
        rename_agent(load(team), "CFO", "Finance")
    assert asked.path.read_text(encoding="utf-8") == before and (team.agents_dir / "CFO").is_dir()


def test_retire_refuses_while_a_run_holds_the_ticket(team):
    import os

    from bron.locks import acquire, release

    queued = new_ticket(team, title="Q3", assignee="cfo", request="x", requested_by="bron")
    assert acquire(team, queued.id, "run-1", pid=os.getpid(), waiting=True)
    with pytest.raises(SetupError, match=f"{queued.id} is being worked on right now"):
        retire_agent(load(team), "CFO")
    release(team, queued.id, "run-1")
    retire_agent(load(team), "CFO")


def test_retire_through_the_command_reports_an_unrelated_existing_problem(team, monkeypatch, capsys):
    add_agent(team, "Broken", reports_to="Ghost")
    monkeypatch.chdir(team.root)
    assert main(["project", "new", "Audit"]) == 0
    out = capsys.readouterr().out
    assert "Bron's setup still has problems from before" in out and "Ghost" in out
    assert (team.root / "Projects" / "Audit" / "README.md").is_file()
    assert main(["agent", "retire", "Analyst"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Retired Analyst.") and "still has problems from before" in out and "Ghost" in out
    assert (team.system / "Archive" / "Agents" / "Analyst" / "Agent.md").is_file()
