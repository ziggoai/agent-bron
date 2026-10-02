import json
import shutil

import pytest

from bron import frontmatter as fm
from bron.loader import load
from bron.model import Issue
from bron.setup import STILL_BROKEN, Change, SetupError, apply, preview, problems, record, run
from bron.sync import SyncResult, run_sync
from vaultkit import add_agent, add_connection


def agent_text(name, **extra):
    meta = {"name": name, "role": f"{name} role", "reports_to": "Bron", "runs_in": "any", **extra}
    return fm.dump(fm.Document(meta, "\nInstructions.\n"))


def snapshot(vault):
    return {p.relative_to(vault.root).as_posix(): p.read_bytes() for p in vault.system.rglob("*") if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts}


def fail_first_sync(monkeypatch, fail, *, real=True, on_call=0):
    """Make one sync inside apply fail (default: the first call); every other call is the real sync."""
    from bron import setup as setup_module

    real_sync = setup_module.run_sync
    calls = []

    def wrapper(vault, **kwargs):
        calls.append(1)
        if len(calls) - 1 == on_call:
            if real:
                real_sync(vault, **kwargs)
            return fail(real_sync, vault)
        return real_sync(vault, **kwargs)

    monkeypatch.setattr("bron.setup.run_sync", wrapper)


def not_ok(real, vault):
    return SyncResult(False, [Issue("error", "sync.failed", "disk full")])


def whole_vault(vault):
    return {p.relative_to(vault.root).as_posix(): p.read_bytes() for p in vault.root.rglob("*") if p.is_file() and ".bron" not in p.relative_to(vault.root).parts and ".venv" not in p.parts and "__pycache__" not in p.parts}


def folders(vault):
    return sorted(p.relative_to(vault.root).as_posix() for p in vault.system.rglob("*") if p.is_dir() and ".venv" not in p.parts and "__pycache__" not in p.parts)


def test_preview_writes_nothing_and_returns_the_summary(vault):
    assert run_sync(vault).ok
    before = snapshot(vault)
    change = Change(summary=["New agent: COO."], writes={"System/Agents/COO/Agent.md": agent_text("COO")}, folders=["System/Agents/COO/Memory"])
    assert preview(vault, change) == ["New agent: COO."]
    assert snapshot(vault) == before and not (vault.agents_dir / "COO").exists()


def test_a_change_that_breaks_the_setup_is_refused(vault):
    broken = Change(summary=["x"], writes={"System/Agents/COO/Agent.md": agent_text("COO", reports_to="Nobody")})
    found = problems(vault, broken)
    assert found and "Nobody" in found[0]
    with pytest.raises(SetupError, match="would break the setup"):
        apply(vault, broken)
    assert not (vault.agents_dir / "COO").exists()


def test_existing_problems_dont_block_an_unrelated_change(vault):
    add_agent(vault, "Broken", reports_to="Ghost")
    change = Change(summary=["x"], writes={"System/Agents/COO/Agent.md": agent_text("COO")})
    assert problems(vault, change) == []


def test_apply_writes_moves_and_syncs(vault):
    add_agent(vault, "CFO")
    assert run_sync(vault).ok
    change = Change(
        summary=["x"],
        moves=[("System/Agents/CFO", "System/Archive/Agents/CFO")],
        writes={"Projects/Fund III audit/README.md": "# Fund III audit\n"},
        folders=["Projects/Fund III audit/Files"],
        done="Done it.",
    )
    assert apply(vault, change) == ["Done it."]
    assert (vault.system / "Archive" / "Agents" / "CFO" / "Agent.md").is_file() and not (vault.agents_dir / "CFO").exists()
    assert (vault.root / "Projects" / "Fund III audit" / "README.md").read_text() == "# Fund III audit\n"
    assert not (vault.root / ".claude" / "agents" / "cfo.md").exists()


def test_a_failed_sync_restores_everything(vault, monkeypatch):
    add_agent(vault, "CFO")
    bron = vault.agents_dir / "Bron" / "Agent.md"
    assert run_sync(vault).ok
    before = snapshot(vault)
    change = Change(
        summary=["x"],
        moves=[("System/Agents/CFO", "System/Agents/Finance")],
        writes={"System/Agents/Finance/Agent.md": agent_text("Finance"), "System/Agents/Bron/Agent.md": bron.read_text() + "\nMore.\n", "System/Agents/New/Agent.md": agent_text("New")},
        folders=["System/Agents/New/Memory"],
    )
    fail_first_sync(monkeypatch, lambda real, vault: SyncResult(False, [Issue("error", "sync.failed", "disk full")]), real=False)
    with pytest.raises(SetupError, match="Nothing was changed"):
        apply(vault, change)
    assert snapshot(vault) == before
    assert (vault.agents_dir / "CFO").is_dir() and not (vault.agents_dir / "Finance").exists() and not (vault.agents_dir / "New").exists()


def test_an_unexpected_error_mid_apply_also_restores(vault, monkeypatch):
    assert run_sync(vault).ok
    before = snapshot(vault)

    def boom(real, vault):
        raise OSError("no space left")

    fail_first_sync(monkeypatch, boom, real=False)
    change = Change(summary=["x"], writes={"System/Agents/COO/Agent.md": agent_text("COO")})
    with pytest.raises(SetupError, match="no space left.*Nothing was changed"):
        apply(vault, change)
    assert snapshot(vault) == before


def test_rollback_keeps_going_and_names_what_it_could_not_restore(vault, monkeypatch):
    add_agent(vault, "CFO")
    assert run_sync(vault).ok
    bron = vault.agents_dir / "Bron" / "Agent.md"
    change = Change(
        summary=["x"],
        moves=[("System/Agents/CFO", "System/Agents/Finance")],
        writes={"System/Agents/Finance/Agent.md": agent_text("Finance"), "System/Agents/Bron/Agent.md": bron.read_text() + "\nMore.\n", "System/Agents/New/Agent.md": agent_text("New")},
    )
    fail_first_sync(monkeypatch, not_ok, real=False, on_call=0)
    real_copy = shutil.copy2
    backups = str(vault.backups_dir)

    def copy(src, dst, *args, **kwargs):
        if str(src).startswith(backups):
            raise OSError("disk went away")
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr("bron.setup.shutil.copy2", copy)
    with pytest.raises(SetupError) as caught:
        apply(vault, change)
    message = str(caught.value)
    assert "System/Agents/Bron/Agent.md" in message and ".bron/backups/setup-" in message and "Nothing was changed" not in message
    assert (vault.agents_dir / "CFO").is_dir() and not (vault.agents_dir / "Finance").exists() and not (vault.agents_dir / "New").exists()


def test_a_move_and_a_write_at_its_old_place_both_go_back(vault, monkeypatch):
    add_agent(vault, "CFO")
    assert run_sync(vault).ok
    before, tree = whole_vault(vault), folders(vault)
    change = Change(
        summary=["x"],
        moves=[("System/Agents/CFO", "System/Archive/Agents/CFO")],
        writes={"System/Agents/CFO/Agent.md": agent_text("CFO", role="Other")},
    )
    fail_first_sync(monkeypatch, not_ok, real=False)
    with pytest.raises(SetupError, match="Nothing was changed"):
        apply(vault, change)
    assert whole_vault(vault) == before and folders(vault) == tree
    assert not (vault.system / "Archive" / "Agents" / "CFO").exists()
    assert not (vault.system / "Archive").exists()


def test_the_generated_setup_goes_back_too(vault, monkeypatch):
    add_agent(vault, "CFO")
    assert run_sync(vault).ok
    before = whole_vault(vault)
    change = Change(summary=["x"], writes={"System/Agents/COO/Agent.md": agent_text("COO")}, folders=["System/Agents/COO/Memory"])
    fail_first_sync(monkeypatch, not_ok, real=True)
    with pytest.raises(SetupError, match="Nothing was changed"):
        apply(vault, change)
    assert whole_vault(vault) == before


def test_a_failed_refresh_after_rollback_says_to_run_sync(vault, monkeypatch):
    assert run_sync(vault).ok
    change = Change(summary=["x"], writes={"System/Agents/COO/Agent.md": agent_text("COO")})
    from bron import setup as setup_module

    real_sync = setup_module.run_sync
    calls = []

    def wrapper(vault, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            real_sync(vault, **kwargs)
            return SyncResult(False, [Issue("error", "sync.failed", "disk full")])
        return SyncResult(False, [Issue("error", "sync.failed", "still full")])

    monkeypatch.setattr("bron.setup.run_sync", wrapper)
    with pytest.raises(SetupError, match=r"bron sync") as caught:
        apply(vault, change)
    assert "Nothing was changed" not in str(caught.value)


def click(vault, *rules):
    """A "don't ask again" click in Claude Code: it adds allow rules to .claude/settings.json."""
    settings = vault.root / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data.setdefault("permissions", {}).setdefault("allow", []).extend(rules)
    settings.write_text(json.dumps(data, indent=4), encoding="utf-8")


def test_clicks_imported_before_the_change_survive_a_rollback(vault, monkeypatch):
    add_connection(vault, "Gmail", type="native", claude="claude_ai_Gmail")
    assert run_sync(vault).ok
    click(vault, "mcp__claude_ai_Gmail__reply")
    bron = vault.agents_dir / "Bron" / "Agent.md"
    build = lambda cfg: Change(summary=["x"], writes={"System/Agents/Bron/Agent.md": bron.read_text() + "\nMore.\n"})  # noqa: E731
    fail_first_sync(monkeypatch, not_ok, real=True, on_call=1)  # call 0 is the catch-up sync, call 1 the sync after the change
    with pytest.raises(SetupError, match="Nothing was changed"):
        run(vault, build, preview_only=False)
    assert "mcp:Gmail:reply" in load(vault).agents["bron"].always_allow
    assert "mcp:Gmail:reply" in bron.read_text()


def test_a_change_built_before_a_click_was_imported_is_refused_not_written(vault):
    add_connection(vault, "Gmail", type="native", claude="claude_ai_Gmail")
    assert run_sync(vault).ok
    click(vault, "mcp__claude_ai_Gmail__reply")
    bron = vault.agents_dir / "Bron" / "Agent.md"
    stale = Change(summary=["x"], writes={"System/Agents/Bron/Agent.md": bron.read_text() + "\nMore.\n"})
    with pytest.raises(SetupError, match="Something changed System/Agents/Bron/Agent.md while Bron was preparing this; nothing was changed — try again."):
        apply(vault, stale)  # the catch-up sync imports the click into the very file the change would overwrite
    assert "mcp:Gmail:reply" in bron.read_text() and "More." not in bron.read_text()


def test_run_builds_from_the_setup_after_catching_up(vault):
    assert run_sync(vault).ok
    click(vault, "Bash(git push:*)")
    seen = []

    def build(cfg):
        seen.append(list(cfg.agents["bron"].always_allow))
        bron = cfg.agents["bron"].path
        return Change(summary=["x"], writes={"System/Agents/Bron/Agent.md": bron.read_text() + "\nMore.\n"}, done="Done it.")

    assert run(vault, build, preview_only=False) == ["Done it."]
    assert seen == [["shell:git push"]]
    assert "shell:git push" in load(vault).agents["bron"].always_allow


def test_a_preview_through_run_writes_nothing_even_with_a_click_pending(vault):
    assert run_sync(vault).ok
    click(vault, "Bash(git push:*)")
    before = whole_vault(vault)
    assert run(vault, lambda cfg: Change(summary=["New agent: COO."], writes={"System/Agents/COO/Agent.md": agent_text("COO")}), preview_only=True) == ["New agent: COO."]
    assert whole_vault(vault) == before


def test_a_file_changed_between_build_and_apply_is_refused(vault, monkeypatch):
    assert run_sync(vault).ok
    bron = vault.agents_dir / "Bron" / "Agent.md"
    from bron import setup as setup_module

    real_preview = setup_module.preview

    def preview_then_someone_edits(vault, change):
        lines = real_preview(vault, change)
        bron.write_text(bron.read_text() + "\nEdited in Obsidian meanwhile.\n", encoding="utf-8")
        return lines

    monkeypatch.setattr("bron.setup.preview", preview_then_someone_edits)
    build = lambda cfg: Change(summary=["x"], writes={"System/Agents/Bron/Agent.md": cfg.agents["bron"].path.read_text() + "\nMore.\n", "System/Agents/COO/Agent.md": agent_text("COO")})  # noqa: E731
    with pytest.raises(SetupError, match="Something changed System/Agents/Bron/Agent.md"):
        run(vault, build, preview_only=False)
    assert "Edited in Obsidian meanwhile." in bron.read_text() and "More." not in bron.read_text()
    assert not (vault.agents_dir / "COO").exists()


def test_a_recorded_folder_that_changed_is_refused(vault):
    add_agent(vault, "CFO")
    assert run_sync(vault).ok
    change = Change(summary=["x"], moves=[("System/Agents/CFO", "System/Archive/Agents/CFO")])
    record(vault, change)
    (vault.agents_dir / "CFO" / "Agent.md").write_text(agent_text("CFO", role="Changed"), encoding="utf-8")
    with pytest.raises(SetupError, match="Something changed System/Agents/CFO"):
        apply(vault, change)
    assert (vault.agents_dir / "CFO" / "Agent.md").is_file() and not (vault.system / "Archive").exists()


def test_setup_commands_take_turns(vault, monkeypatch):
    import threading

    assert run_sync(vault).ok
    inside, overlap = [], []
    lock = threading.Lock()

    def build(n):
        def inner(cfg):
            with lock:
                inside.append(n)
                if len(inside) > 1:
                    overlap.append(n)
            import time

            time.sleep(0.2)
            with lock:
                inside.remove(n)
            return Change(summary=[f"{n}"], writes={f"Projects/P{n}/README.md": "x\n"})
        return inner

    threads = [threading.Thread(target=run, args=(vault, build(n)), kwargs={"preview_only": False}) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlap == [] and (vault.root / "Projects" / "P0").is_dir() and (vault.root / "Projects" / "P1").is_dir()


def test_an_existing_problem_doesnt_block_a_change_and_is_reported(vault):
    add_agent(vault, "Broken", reports_to="Ghost")
    assert not run_sync(vault).ok
    lines = run(vault, lambda cfg: Change(summary=["x"], writes={"Projects/Audit/README.md": "# Audit\n"}, done="Done it."), preview_only=False)
    assert lines[:2] == ["Done it.", STILL_BROKEN]
    assert any("Ghost" in line for line in lines[2:]) and all(line.startswith("- ") for line in lines[2:])
    assert (vault.root / "Projects" / "Audit" / "README.md").is_file()


def test_a_change_that_fixes_the_existing_problem_syncs_again(vault):
    add_agent(vault, "Broken", reports_to="Ghost")
    assert not run_sync(vault).ok
    fixed = agent_text("Broken", reports_to="Bron")
    assert run(vault, lambda cfg: Change(summary=["x"], writes={"System/Agents/Broken/Agent.md": fixed}, done="Done it."), preview_only=False) == ["Done it."]
    assert run_sync(vault).ok and (vault.root / ".claude" / "agents" / "broken.md").is_file()


def test_a_new_problem_after_the_change_still_rolls_back_when_the_setup_was_already_broken(vault, monkeypatch):
    add_agent(vault, "Broken", reports_to="Ghost")
    before = whole_vault(vault)
    from bron import setup as setup_module

    real_sync = setup_module.run_sync
    calls = []

    def wrapper(vault, **kwargs):
        calls.append(1)
        result = real_sync(vault, **kwargs)
        if len(calls) == 2:  # the sync after the change: the old problem plus a new one
            return SyncResult(False, result.issues + [Issue("error", "sync.failed", "disk full")])
        return result

    monkeypatch.setattr("bron.setup.run_sync", wrapper)
    with pytest.raises(SetupError, match=r"\(disk full\)\. Nothing was changed"):
        run(vault, lambda cfg: Change(summary=["x"], writes={"Projects/Audit/README.md": "# Audit\n"}), preview_only=False)
    assert whole_vault(vault) == before


def test_a_write_onto_a_folder_is_refused_and_existing_folders_stay(vault):
    add_agent(vault, "CFO")
    assert run_sync(vault).ok
    before, tree = whole_vault(vault), folders(vault)
    change = Change(summary=["x"], writes={"System/Agents/CFO": "text"}, folders=["System/Agents/CFO/Memory"])
    with pytest.raises(SetupError, match="is a folder"):
        preview(vault, change)
    with pytest.raises(SetupError, match="is a folder"):
        apply(vault, change)
    assert whole_vault(vault) == before and folders(vault) == tree


def test_moves_must_have_a_source_and_a_free_target(vault):
    add_agent(vault, "CFO")
    with pytest.raises(SetupError, match="doesn't exist"):
        preview(vault, Change(summary=["x"], moves=[("System/Agents/Nope", "System/Archive/Agents/Nope")]))
    with pytest.raises(SetupError, match="already exists"):
        preview(vault, Change(summary=["x"], moves=[("System/Agents/CFO", "System/Agents/Bron")]))
    with pytest.raises(SetupError, match="doesn't exist"):
        preview(vault, Change(summary=["x"], moves=[("Projects/Nope", "Archive/Nope")]))


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.md", "System/../../outside.md", ""])
def test_paths_outside_the_vault_are_refused(vault, bad):
    change = Change(summary=["x"], writes={bad: "x"})
    with pytest.raises(SetupError, match="outside the vault"):
        preview(vault, change)
    with pytest.raises(SetupError, match="outside the vault"):
        apply(vault, change)
    with pytest.raises(SetupError, match="outside the vault"):
        preview(vault, Change(summary=["x"], moves=[("System/Agents/Bron", bad)]))


def test_each_apply_gets_its_own_backup_folder(vault):
    assert run_sync(vault).ok
    bron = vault.agents_dir / "Bron" / "Agent.md"
    for n in range(2):
        apply(vault, Change(summary=["x"], writes={"System/Agents/Bron/Agent.md": bron.read_text() + f"\nRound {n}.\n"}))
    assert len(list(vault.backups_dir.glob("setup-*"))) == 2
