import json

import pytest

from bron.writer import GeneratedWriter


def write(vault, files, fingerprint=""):
    return GeneratedWriter(vault).apply({k: v.encode() for k, v in files.items()}, fingerprint)


def test_writes_files_and_records_them(vault):
    report = write(vault, {".claude/settings.json": "{}\n", "AGENTS.md": "rules\n"}, "fp1")
    assert sorted(report.written) == [".claude/settings.json", "AGENTS.md"]
    assert (vault.root / "AGENTS.md").read_text() == "rules\n"
    manifest = json.loads((vault.state_dir / "sync.json").read_text())
    assert set(manifest["files"]) == {".claude/settings.json", "AGENTS.md"}
    assert manifest["fingerprint"] == "fp1"


def test_same_content_writes_nothing(vault):
    write(vault, {"AGENTS.md": "rules\n"})
    report = write(vault, {"AGENTS.md": "rules\n"})
    assert report.written == [] and report.deleted == [] and report.backed_up == []


def test_hand_edited_file_is_backed_up_then_replaced(vault):
    write(vault, {".claude/settings.json": "{}\n"})
    (vault.root / ".claude/settings.json").write_text('{"mine": true}\n')
    report = write(vault, {".claude/settings.json": '{"agent": "bron"}\n'})
    assert report.backed_up == [".claude/settings.json"]
    assert (report.backup_dir / ".claude/settings.json").read_text() == '{"mine": true}\n'
    assert (vault.root / ".claude/settings.json").read_text() == '{"agent": "bron"}\n'


def test_existing_file_bron_never_wrote_is_backed_up(vault):
    (vault.root / ".claude").mkdir()
    (vault.root / ".claude/settings.json").write_text('{"theirs": 1}\n')
    report = write(vault, {".claude/settings.json": "{}\n"})
    assert report.backed_up == [".claude/settings.json"]


def test_dropped_files_are_removed_but_other_tools_files_survive(vault):
    termy = vault.root / ".agents/skills/termy-obsidian-context/SKILL.md"
    termy.parent.mkdir(parents=True)
    termy.write_text("termy\n")
    local = vault.root / ".claude/settings.local.json"
    local.parent.mkdir(parents=True)
    local.write_text("{}\n")
    write(vault, {".agents/skills/check/SKILL.md": "a\n", ".claude/agents/cfo.md": "b\n"})
    report = write(vault, {})
    assert sorted(report.deleted) == [".agents/skills/check/SKILL.md", ".claude/agents/cfo.md"]
    assert not (vault.root / ".agents/skills/check").exists()
    assert termy.read_text() == "termy\n"
    assert local.read_text() == "{}\n"


def test_refuses_paths_outside_generated_places(vault):
    with pytest.raises(ValueError, match="outside"):
        write(vault, {"System/Settings.md": "x"})
    with pytest.raises(ValueError, match="outside"):
        write(vault, {".claude/../System/Settings.md": "x"})


def test_drift_detects_edits_and_deletions(vault):
    write(vault, {"AGENTS.md": "a\n", "CLAUDE.md": "@AGENTS.md\n"})
    (vault.root / "AGENTS.md").write_text("edited\n")
    (vault.root / "CLAUDE.md").unlink()
    assert GeneratedWriter(vault).drift() == ["AGENTS.md", "CLAUDE.md"]


def test_corrupt_manifest_is_treated_as_empty(vault):
    vault.state_dir.mkdir(parents=True)
    (vault.state_dir / "sync.json").write_text("{not json")
    assert GeneratedWriter(vault).drift() == []
