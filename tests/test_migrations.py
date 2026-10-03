from bron import migrations
from bron.migrations import Migration, apply_pending, pending
from bron.setup import Change


def note(text):
    return lambda cfg: Change(summary=[text], writes={"Projects/Migrated.md": text + "\n"}, done=f"Applied: {text}")


REGISTRY = [
    Migration("old", "0.4.0", "Old change", note("old")),
    Migration("five", "0.5.0", "Five change", note("five")),
    Migration("six", "0.6.0", "Six change", note("six")),
]


def test_pending_is_between_versions_and_in_order(vault):
    assert [m.id for m in pending(vault, "0.4.1", "0.6.0", REGISTRY)] == ["five", "six"]
    assert pending(vault, "0.6.0", "0.4.1", REGISTRY) == []


def test_each_migration_applies_once(vault):
    apply_pending(vault, "0.4.1", "0.5.0", REGISTRY)
    assert (vault.root / "Projects" / "Migrated.md").read_text() == "five\n"
    (vault.root / "Projects" / "Migrated.md").unlink()
    apply_pending(vault, "0.4.1", "0.5.0", REGISTRY)
    assert not (vault.root / "Projects" / "Migrated.md").exists()


def test_the_registry_starts_empty():
    assert migrations.MIGRATIONS == []
