from bron import frontmatter as fm
from bron.briefing import build_briefing
from bron.loader import load

SETUP_SKILLS = ("onboarding", "create-agent", "edit-agent", "remove-agent", "add-connection", "create-project", "create-routine", "create-skill")


def test_the_setup_skills_are_published_and_say_to_preview_first(vault):
    skills = load(vault).skills
    for name in SETUP_SKILLS:
        assert name in skills, name
        text = (vault.core_skills / name / "SKILL.md").read_text(encoding="utf-8")
        assert "--preview" in text, name
        assert "wait for a yes" in text.lower(), name


def test_onboarding_covers_the_quick_setup_and_bron_default_model(vault):
    text = (vault.core_skills / "onboarding" / "SKILL.md").read_text(encoding="utf-8")
    for phrase in ("name, role and company", "Opus 5.5", "main app", "connections scan", "Tone and preferences now or later", "set up any team members", "/hooks"):
        assert phrase in text, phrase


def test_the_manual_lists_the_setup_commands(vault):
    index = (vault.core_manual / "index.md").read_text(encoding="utf-8")
    assert "](setup.md)" in index
    manual = (vault.core_manual / "setup.md").read_text(encoding="utf-8")
    for command in ("bron agent create", "bron agent set", "bron agent rename", "bron agent retire", "bron agent restore", "bron project new", "bron routine create", "bron skill new", "bron connections add", "bron settings set"):
        assert command in manual, command


def test_the_first_run_briefing_points_to_onboarding(vault):
    assert "Follow the onboarding skill" in build_briefing(vault, cli="claude")


def test_bron_starts_on_opus_in_claude_code(vault):
    assert fm.read(vault.agents_dir / "Bron" / "Agent.md").meta["models"] == {"claude": "opus-5.5", "codex": "gpt-6-astra"}


def test_onboarding_main_app_step_uses_preview_and_waits(vault):
    text = (vault.core_skills / "onboarding" / "SKILL.md").read_text(encoding="utf-8")
    assert "--default-cli <cli> --preview" in text


def test_briefing_uses_command_not_hand_editing_for_user_settings(vault):
    briefing = build_briefing(vault, cli="claude")
    assert "bron settings set --name" in briefing
    assert "save them to `user_name` and `company` in System/Settings.md" not in briefing


def test_no_skill_or_template_tells_agents_to_edit_files_by_hand(vault):
    from bron.agents_md import render_agents_md

    # Check all core skills
    skill_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(vault.core_skills.glob("*/SKILL.md")))

    # Check AGENTS template
    agents_template = (vault.core_templates / "AGENTS.md.tmpl").read_text(encoding="utf-8")

    # Check Bron's agent file
    bron_agent = (vault.agents_dir / "Bron" / "Agent.md").read_text(encoding="utf-8")

    combined_text = skill_text + "\n" + agents_template + "\n" + bron_agent

    # These phrases indicate hand-editing and should not appear
    bad_phrases = [
        "in Agent.md",
        "in System/Agents",
        "to `connections:`",
        "in System/Settings.md",
        "edit System/",
    ]

    for phrase in bad_phrases:
        assert phrase not in combined_text, f"Found hand-editing instruction: {phrase}"


def test_onboarding_uses_the_agents_own_name_and_previews_the_role(vault):
    text = (vault.core_skills / "onboarding" / "SKILL.md").read_text(encoding="utf-8")
    assert "agent rename Bron" not in text and "agent set Bron" not in text
    assert "`.bron/bin/bron agent rename '<your name>' '<NewName>' --preview`" in text
    assert "`.bron/bin/bron agent set '<your name>' --role '<role>' --instructions-file .bron/tmp/<your name>-instructions.md --preview`, show the summary, wait for a yes" in text
    assert "`.bron/bin/bron agent set '<your name>' --model 'claude=<model>' --preview`" in text


def test_who_you_means_in_the_create_skills(vault):
    agent = (vault.core_skills / "create-agent" / "SKILL.md").read_text(encoding="utf-8")
    assert "leave `--reports-to` out and it reports to the main agent; `--reports-to you` means the user" in agent
    routine = (vault.core_skills / "create-routine" / "SKILL.md").read_text(encoding="utf-8")
    assert "owner: your own name, unless the user says otherwise" in routine


def test_onboarding_asks_which_connectors_and_sets_the_list(vault):
    text = (vault.core_skills / "onboarding" / "SKILL.md").read_text(encoding="utf-8")
    assert "Which of these should I use?" in text
    assert "--remove-connection all --add-connection '<connection>'" in text
    assert "the same app twice" in text
    assert "not a memory" in text


def test_a_role_change_rewrites_who_you_are_in_the_same_command(vault):
    for name in ("onboarding", "edit-agent"):
        text = (vault.core_skills / name / "SKILL.md").read_text(encoding="utf-8")
        assert 'rewrite "Who you are" for the new role' in text, name
        assert "--role '<role>' --instructions-file" in text, name


def test_edit_agent_covers_stopping_a_connector(vault):
    meta = fm.read(vault.core_skills / "edit-agent" / "SKILL.md").meta
    assert "stop using a connector" in meta["description"]


def test_a_fact_about_one_wiki_thing_goes_on_its_page_not_in_memory(vault):
    text = (vault.core_templates / "AGENTS.md.tmpl").read_text(encoding="utf-8")
    assert "with a `Knowledge/` page goes there as \"(the user, <date>)\", not in memory" in text
