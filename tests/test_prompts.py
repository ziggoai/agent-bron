import shlex

from bron import frontmatter as fm
from bron.agents_md import render_agents_md
from bron.hookconfig import hooks_block
from bron.loader import load
from bron.prompts import agent_prompt, helper_prompt
from bron.skills import skill_files
from vaultkit import add_agent, set_meta, write_md


def test_agents_md_lists_team_rules_and_manual(vault):
    add_agent(vault, "CFO", role="Chief Financial Officer")
    text = render_agents_md(load(vault))
    assert "| CFO | Chief Financial Officer | Bron | `@cfo` |" in text
    assert "| Bron | Chief of Staff | you | `@bron` |" in text
    assert "System/Core/Manual/index.md" in text
    assert "Team members never run as subagents" in text
    assert "the only exception: saving the user's own name and company" in text
    assert "Framework version 0.3.1." in text
    assert "work with the user" in text
    assert len(text.encode()) < 8 * 1024


def test_agents_md_uses_the_users_name(vault):
    set_meta(vault.settings_file, user_name="Alex")
    assert "work with Alex" in render_agents_md(load(vault))


def test_bron_prompt(vault):
    cfg = load(vault)
    prompt = agent_prompt(cfg.agents["bron"], cfg)
    assert prompt.startswith("# You are Bron\n")
    assert "You report to the user." in prompt
    assert "You work on your own" in prompt
    assert "reader, researcher, reviewer" in prompt
    assert "# Boundaries" in prompt


def test_team_member_prompt(vault):
    add_agent(vault, "CFO", can_assign_to=["Bron"])
    cfg = load(vault)
    prompt = agent_prompt(cfg.agents["cfo"], cfg)
    assert "You report to Bron." in prompt
    assert "You can hand work to Bron through tickets." in prompt
    assert "Instructions for CFO." in prompt


def test_helper_prompt_is_read_only(vault):
    cfg = load(vault)
    prompt = helper_prompt(cfg.helpers["reader"])
    assert prompt.startswith("# You are the reader helper\n")
    assert "never create, change or delete files" in prompt


def test_skill_files_copy_folders_and_rename_agent_skills(vault):
    folder = vault.agents_dir / "Bron" / "Skills" / "brief"
    write_md(folder / "SKILL.md", {"name": "brief", "description": "Daily brief"}, "Steps\n")
    (folder / "notes.txt").write_text("n\n")
    (folder / ".DS_Store").write_text("junk")
    files = skill_files(load(vault), ".claude/skills")
    assert ".claude/skills/check/SKILL.md" in files
    doc = fm.parse(files[".claude/skills/bron-brief/SKILL.md"].decode())
    assert doc.meta == {"name": "bron-brief", "description": "(For Bron only) Daily brief"}
    assert doc.body == "Steps\n"
    assert files[".claude/skills/bron-brief/notes.txt"] == b"n\n"
    assert not any(".DS_Store" in key for key in files)


def test_trigger_commands_are_fixed_and_survive_spaces_and_accents(vault):
    block = hooks_block(vault, "codex")
    assert set(block) == {"SessionStart", "UserPromptSubmit", "PreCompact", "Stop", "SessionEnd"}
    command = block["SessionStart"][0]["hooks"][0]["command"]
    assert command == f"{shlex.quote(str(vault.bron_command))} hook session-start --cli codex"
    assert shlex.split(command)[0] == str(vault.bron_command)
    assert block["SessionEnd"][0]["hooks"][0]["timeout"] <= 3
    assert hooks_block(vault, "codex") == block
