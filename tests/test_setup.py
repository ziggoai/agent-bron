import pytest

from bron import frontmatter as fm
from bron.model import Issue
from bron.setup import Change, SetupError, apply, preview, problems
from bron.sync import SyncResult, run_sync
from vaultkit import add_agent


def agent_text(name, **extra):
    meta = {"name": name, "role": f"{name} role", "reports_to": "Bron", "runs_in": "any", **extra}
    return fm.dump(fm.Document(meta, "\nInstructions.\n"))


def snapshot(vault):
    return {p.relative_to(vault.root).as_posix(): p.read_bytes() for p in vault.system.rglob("*") if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts}


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
    monkeypatch.setattr("bron.setup.run_sync", lambda vault: SyncResult(False, [Issue("error", "sync.failed", "disk full")]))
    with pytest.raises(SetupError, match="Nothing was changed"):
        apply(vault, change)
    assert snapshot(vault) == before
    assert (vault.agents_dir / "CFO").is_dir() and not (vault.agents_dir / "Finance").exists() and not (vault.agents_dir / "New").exists()


def test_an_unexpected_error_mid_apply_also_restores(vault, monkeypatch):
    assert run_sync(vault).ok
    before = snapshot(vault)

    def boom(vault):
        raise OSError("no space left")

    monkeypatch.setattr("bron.setup.run_sync", boom)
    change = Change(summary=["x"], writes={"System/Agents/COO/Agent.md": agent_text("COO")})
    with pytest.raises(SetupError, match="no space left.*Nothing was changed"):
        apply(vault, change)
    assert snapshot(vault) == before
