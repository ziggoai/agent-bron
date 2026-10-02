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
    assert fm.read(vault.agents_dir / "Bron" / "Agent.md").meta["models"] == {"claude": "opus-5.5", "codex": "default"}
