import pytest

from bron.cli import main
from bron.loader import load
from bron.memory import commands
from vaultkit import add_agent, set_meta


@pytest.fixture
def run(vault, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))

    def _run(*args):
        code = main(list(args))
        return code, capsys.readouterr().out
    return _run


def shared(vault):
    return (vault.memory_dir / "Facts.md").read_text(encoding="utf-8")


def test_remember_shared_by_default(run, vault):
    code, out = run("memory", "remember", "Reports only include active companies (FMV > 0)", "--as", "Bron")
    assert code == 0
    assert out.strip() == "Noted: Reports only include active companies (FMV > 0)."
    assert "## Decisions" in shared(vault)
    assert "(FMV > 0). (" in shared(vault) and ", Bron)" in shared(vault)


def test_remember_mine_goes_to_the_agents_own_notes(run, vault):
    add_agent(vault, "CFO")
    code, out = run("memory", "remember", "The one-pager uses the fund template", "--as", "cfo", "--mine", "--section", "how")
    assert code == 0
    text = (vault.agents_dir / "CFO" / "Memory" / "Facts.md").read_text()
    assert "## How you like things done" in text and "fund template. (" in text and ", CFO)" in text


def test_replaces_updates_the_old_line(run, vault):
    run("memory", "remember", "Cutoff is FMV > 0", "--as", "Bron")
    code, out = run("memory", "remember", "Cutoff is FMV > 0 and not written off", "--as", "Bron", "--replaces", "cutoff is fmv")
    assert out.strip() == "Updated: Cutoff is FMV > 0 and not written off."
    assert shared(vault).count("Cutoff") == 1


def test_replaces_with_no_match_just_adds(run, vault):
    code, out = run("memory", "remember", "New fact", "--as", "Bron", "--replaces", "nothing like this")
    assert code == 0 and out.startswith("Noted: New fact.")


def test_secrets_are_refused(run, vault):
    code, out = run("memory", "remember", "The portal password: hunter2", "--as", "Bron")
    assert code == 1
    assert "looks like a password or key" in out
    facts_md = vault.memory_dir / "Facts.md"
    assert not facts_md.exists() or "hunter2" not in facts_md.read_text()


def test_ticket_runs_cannot_change_shared_memory(run, vault, monkeypatch):
    monkeypatch.setenv("BRON_TICKET", "T-1")
    code, out = run("memory", "remember", "Board meets on Tuesdays", "--as", "Bron")
    assert code == 0
    assert out.startswith("Only a conversation with you can change shared memory, so I saved this to my own notes. Noted:")
    facts_md = vault.memory_dir / "Facts.md"
    assert not facts_md.exists() or "Board meets" not in facts_md.read_text()
    assert "Board meets on Tuesdays." in (vault.agents_dir / "Bron" / "Memory" / "Facts.md").read_text()


def test_forget_one_match(run, vault):
    run("memory", "remember", "Prefers PDFs", "--as", "Bron", "--section", "about-you")
    code, out = run("memory", "forget", "pdfs", "--as", "Bron")
    assert code == 0 and out.strip() == "Forgotten: Prefers PDFs."
    assert "Prefers PDFs" not in shared(vault)


def test_forget_searches_own_notes_too(run, vault):
    run("memory", "remember", "Own habit", "--as", "Bron", "--mine")
    code, out = run("memory", "forget", "own habit", "--as", "Bron")
    assert code == 0 and "Forgotten" in out


def test_forget_with_several_matches_changes_nothing(run, vault):
    run("memory", "remember", "Fund I closes in May", "--as", "Bron")
    run("memory", "remember", "Fund II closes in June", "--as", "Bron")
    code, out = run("memory", "forget", "closes", "--as", "Bron")
    assert code == 1
    assert "more than one" in out and "Fund I closes in May." in out and "Fund II closes in June." in out
    assert shared(vault).count("closes") == 2


def test_forget_nothing_found(run, vault):
    code, out = run("memory", "forget", "unicorns", "--as", "Bron")
    assert code == 1 and "couldn't find" in out


def test_forget_a_conversation(run, vault):
    folder = vault.agents_dir / "Bron" / "Memory" / "Conversations" / "2026-10"
    folder.mkdir(parents=True)
    note = folder / "2026-10-03 09.15 Q3 report fields.md"
    note.write_text("---\nsession_id: s1\n---\n## Asked\n- x\n")
    code, out = run("memory", "forget", "--conversation", "q3 report", "--as", "Bron")
    assert code == 0 and "Forgotten: the conversation" in out
    assert not note.exists()


def test_unknown_agent(run):
    code, out = run("memory", "remember", "x", "--as", "Nobody")
    assert code == 1 and "no agent called Nobody" in out


def test_near_the_limit_offers_to_tidy(run, vault):
    for i in range(40):
        run("memory", "remember", f"Fact number {i} " + "x" * 80, "--as", "Bron")
    _, out = run("memory", "remember", "One more fact " + "y" * 80, "--as", "Bron")
    assert "Memory is getting long; I can tidy it." in out


def test_memory_settings(vault):
    set_meta(vault.settings_file, memory={"summaries": False, "summary_model": {"codex": "gpt-6-sol"}})
    settings = load(vault).settings
    assert settings.memory_summaries is False
    assert settings.summary_models == {"claude": "haiku", "codex": "gpt-6-sol"}


def test_memory_settings_defaults(vault):
    settings = load(vault).settings
    assert settings.memory_summaries is True
    assert settings.summary_models == {"claude": "haiku", "codex": "gpt-6-luna"}
