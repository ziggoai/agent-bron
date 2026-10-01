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


def test_tampered_manifest_cannot_delete_user_files(vault):
    """Tampered manifest with keys outside allowed roots should not delete those files."""
    # Create a user file that is NOT in allowed roots
    settings_file = vault.settings_file
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    original_content = "user data\n"
    settings_file.write_text(original_content)

    # Create a tampered manifest claiming to have written System/Settings.md
    vault.state_dir.mkdir(parents=True)
    tampered = {
        "files": {
            "System/Settings.md": sha256(original_content.encode()),
            "AGENTS.md": sha256(b"safe\n")
        },
        "fingerprint": ""
    }
    (vault.state_dir / "sync.json").write_text(json.dumps(tampered))

    # Try to sync with empty files - should not delete System/Settings.md
    report = write(vault, {})
    assert report.deleted == []
    assert settings_file.read_text() == original_content


def test_symlinked_generated_folder_is_refused(vault):
    """Symlinks pointing outside the vault should be refused."""
    # Create a folder outside the vault
    outside = vault.root.parent / "outside"
    outside.mkdir(exist_ok=True)

    # Create a symlink in an allowed location pointing outside
    (vault.root / ".claude").mkdir(exist_ok=True)
    (vault.root / ".claude/evil").symlink_to(outside)

    # Try to write through the symlink - should raise ValueError
    with pytest.raises(ValueError, match="outside the vault"):
        write(vault, {".claude/evil/file.json": "{}\n"})

    # Verify nothing was written outside
    assert not list(outside.glob("*"))


def test_folder_at_a_generated_path_is_refused(vault):
    """Folders at generated paths should be refused."""
    # Create a folder where a file should be
    (vault.root / "AGENTS.md").mkdir(exist_ok=True)

    # Try to write a file at that location - should raise ValueError
    with pytest.raises(ValueError, match="folder or a link"):
        write(vault, {"AGENTS.md": "content\n"})

    # Also test that other files in the same batch are not written
    with pytest.raises(ValueError, match="folder or a link"):
        write(vault, {"AGENTS.md": "content\n", "CLAUDE.md": "other\n"})

    # Verify CLAUDE.md was not written
    assert not (vault.root / "CLAUDE.md").exists()


# Helper for symlink/folder tests
def sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()
