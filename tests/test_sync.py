import shutil

from bron.sync import needs_sync, run_sync
from vaultkit import add_agent

EXPECTED = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/agents/bron.md",
    ".claude/agents/reader.md",
    ".claude/skills/check/SKILL.md",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".codex/rules/bron.rules",
    ".codex/agents/reader.toml",
    ".agents/skills/check/SKILL.md",
)


def snapshot(vault):
    return {p: p.read_bytes() for p in vault.root.rglob("*") if p.is_file() and ".bron" not in p.parts}


def test_sync_writes_both_setups_and_is_idempotent(vault):
    first = run_sync(vault)
    assert first.ok, first.issues
    for rel in EXPECTED:
        assert (vault.root / rel).is_file(), rel
    before = snapshot(vault)
    second = run_sync(vault)
    assert second.ok and second.report.written == [] and second.report.deleted == []
    assert snapshot(vault) == before


def test_visible_top_level_after_sync(vault):
    run_sync(vault)
    visible = sorted(p.name for p in vault.root.iterdir() if not p.name.startswith("."))
    assert visible == ["AGENTS.md", "CLAUDE.md", "Knowledge", "Projects", "Routines", "System", "Tickets"]


def test_needs_sync_follows_setup_changes_only(vault):
    assert needs_sync(vault)
    run_sync(vault)
    assert not needs_sync(vault)
    (vault.agents_dir / "Bron" / "Memory" / "2026-10-01.md").write_text("today\n")
    (vault.memory_dir / "Summary.md").write_text("summary\n")
    (vault.projects_dir / "Audit").mkdir()
    assert not needs_sync(vault)
    add_agent(vault, "CFO")
    assert needs_sync(vault)


def test_hand_edit_triggers_a_resync_with_backup(vault):
    run_sync(vault)
    (vault.root / ".claude/settings.json").write_text("{}\n")
    assert needs_sync(vault)
    result = run_sync(vault)
    assert result.report.backed_up == [".claude/settings.json"]


def test_errors_keep_the_last_good_setup(vault):
    run_sync(vault)
    before = (vault.root / ".claude/settings.json").read_bytes()
    add_agent(vault, "CFO", reports_to="Nobody")
    result = run_sync(vault)
    assert not result.ok
    assert any(i.code == "agent.reports-to-unknown" for i in result.issues)
    assert (vault.root / ".claude/settings.json").read_bytes() == before
    assert not (vault.root / ".claude/agents/cfo.md").exists()


def test_removed_agent_files_are_cleaned_up(vault):
    add_agent(vault, "CFO")
    run_sync(vault)
    assert (vault.root / ".claude/agents/cfo.md").is_file()
    shutil.rmtree(vault.agents_dir / "CFO")
    run_sync(vault)
    assert not (vault.root / ".claude/agents/cfo.md").exists()


def test_other_tools_files_survive_sync(vault):
    termy = vault.root / ".agents/skills/termy-obsidian-context/SKILL.md"
    termy.parent.mkdir(parents=True)
    termy.write_text("termy\n")
    local = vault.root / ".claude/settings.local.json"
    local.parent.mkdir(parents=True)
    local.write_text("{}\n")
    run_sync(vault)
    run_sync(vault)
    assert termy.read_text() == "termy\n"
    assert local.read_text() == "{}\n"


def test_oversized_agents_md_stops_sync(vault):
    for i in range(200):
        add_agent(vault, f"Agent{i:03d}", role="r" * 200)
    result = run_sync(vault)
    assert not result.ok
    assert any(i.code == "agents-md.too-large" for i in result.issues)


def test_dry_run_writes_nothing(vault):
    result = run_sync(vault, dry_run=True)
    assert result.ok and result.report is None
    assert not (vault.root / "AGENTS.md").exists()


def test_unsafe_target_stops_sync_without_crashing(vault):
    # Create a folder at AGENTS.md path to make it an unsafe target
    (vault.root / "AGENTS.md").mkdir()
    result = run_sync(vault)
    assert not result.ok
    assert any(i.code == "sync.failed" for i in result.issues)
    assert "folder" in " ".join(i.message for i in result.issues if i.code == "sync.failed").lower()
    # Verify that .claude/settings.json was not written (setup wasn't applied)
    assert not (vault.root / ".claude/settings.json").exists()


def test_two_syncs_at_once_never_back_up_each_others_files(vault, monkeypatch):
    import threading
    import time

    from bron import sync

    assert run_sync(vault).ok
    barrier = threading.Barrier(2)
    real_plan = sync.plan_files

    def plan(cfg):  # each sync plans a slightly different AGENTS.md, as if System/ changed in between
        files = real_plan(cfg)
        files["AGENTS.md"] += f"<!-- {threading.current_thread().name} -->\n".encode()
        return files

    class RacingWriter(sync.GeneratedWriter):
        def apply(self, files, fingerprint="", accept=frozenset()):
            try:
                barrier.wait(timeout=1)  # without a sync lock both writers have read the old manifest by now
            except threading.BrokenBarrierError:
                pass
            if threading.current_thread().name == "second":
                time.sleep(0.3)
            return super().apply(files, fingerprint, accept)

    monkeypatch.setattr(sync, "plan_files", plan)
    monkeypatch.setattr(sync, "GeneratedWriter", RacingWriter)
    results = []
    threads = [threading.Thread(target=lambda: results.append(run_sync(vault)), name=name) for name in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 2 and all(r.ok for r in results)
    assert not any(r.report.backed_up for r in results)
    assert not vault.backups_dir.exists() or not any(vault.backups_dir.iterdir())


def test_engine_version_change_triggers_sync(vault, monkeypatch):
    import bron

    run_sync(vault)
    assert not needs_sync(vault)
    monkeypatch.setattr(bron, "__version__", "99.0.0")
    assert needs_sync(vault)
