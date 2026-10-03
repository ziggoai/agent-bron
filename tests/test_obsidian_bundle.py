"""The shipped Obsidian bundle: complete, and free of personal state."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "core" / "Obsidian"
TEMPLATE = REPO / "template" / ".obsidian"
SCRIPT = REPO / "scripts" / "export-obsidian.py"
PLUGINS = ["bron-workspace", "colored-tags", "data-files-editor", "file-explorer-note-count", "obsidian-icon-folder", "obsidian-style-settings", "xlsx-viewer"]
THIRD_PARTY = [p for p in PLUGINS if p != "bron-workspace"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")


def all_files():
    return [p for root in (BUNDLE, TEMPLATE) for p in root.rglob("*") if p.is_file()]


def test_bundle_has_the_theme_and_every_plugin():
    assert (BUNDLE / "themes" / "Bron" / "theme.css").is_file()
    for plugin in PLUGINS:
        assert (BUNDLE / "plugins" / plugin / "main.js").is_file(), plugin
        assert json.loads((BUNDLE / "plugins" / plugin / "manifest.json").read_text())["id"] == plugin


def test_left_out_items_are_not_shipped():
    shipped = {p.name for p in (BUNDLE / "plugins").iterdir()}
    assert not shipped & {"obsidian-file-color", "termy", "bron-v2-terminal", "bron-v2-ai-usage", "bron-terminal"}
    assert {p.name for p in (BUNDLE / "themes").iterdir()} == {"Bron"}
    assert not list((TEMPLATE / "icons").rglob("*.zip"))


def test_the_theme_keeps_its_embedded_icons_exactly():
    css = (BUNDLE / "themes" / "Bron" / "theme.css").read_text()
    assert css.count("data:image/svg+xml") >= 30
    source = REPO / ".obsidian" / "themes" / "Bron" / "theme.css"
    if source.is_file():  # the maintainer's own vault (not in git)
        assert (BUNDLE / "themes" / "Bron" / "theme.css").read_bytes() == source.read_bytes()


def test_the_icons_the_vault_uses_ship_too():
    icons = [p for p in (TEMPLATE / "icons").rglob("*") if p.is_file()]
    assert icons and all(p.suffix == ".svg" for p in icons)
    assert sum(p.stat().st_size for p in icons) < 1_000_000
    assert (TEMPLATE / "icons" / "tabler-icons" / "FileTextAi.svg").is_file()


def test_no_settings_in_the_code_bundle():
    assert not list(BUNDLE.rglob("data.json"))


def test_no_personal_state_in_template():
    for name in ("workspace.json", "workspace-mobile.json", "graph.json", "devin-backups"):
        assert not (TEMPLATE / name).exists(), name


def test_no_personal_paths_or_emails_anywhere():
    for path in all_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "/Users/" not in text, path
        assert not EMAIL.search(text), (path, EMAIL.search(text).group(0))


def test_bron_owned_items_are_credited_to_ziggo_ai():
    for manifest in (BUNDLE / "themes" / "Bron" / "manifest.json", BUNDLE / "plugins" / "bron-workspace" / "manifest.json"):
        data = json.loads(manifest.read_text())
        assert data["author"] == "Ziggo AI"
        assert "authorUrl" not in data and "fundingUrl" not in data


def test_first_install_settings():
    appearance = json.loads((TEMPLATE / "appearance.json").read_text())
    assert appearance["cssTheme"] == "Bron"
    enabled = json.loads((TEMPLATE / "community-plugins.json").read_text())
    assert "bron-terminal" in enabled and "bron-workspace" in enabled
    assert "obsidian-icon-folder" not in enabled
    iconize = json.loads((TEMPLATE / "plugins" / "obsidian-icon-folder" / "data.json").read_text())
    assert iconize["settings"]["recentlyUsedIcons"] == []
    assert iconize["AGENTS.md"] == "TiFileTextAi"  # the icon the maintainer's vault shows for AGENTS.md


def test_template_obsidian_is_tracked_by_git():
    done = subprocess.run(["git", "check-ignore", "-q", str(TEMPLATE / "appearance.json")], cwd=REPO)
    assert done.returncode == 1  # 1 = not ignored


def test_third_party_notices_cover_every_plugin():
    notices = (BUNDLE / "THIRD-PARTY-NOTICES.md").read_text()
    for plugin in THIRD_PARTY:
        assert plugin in notices, plugin
    assert "GPL-3.0" in notices  # Style Settings


def make_source(root: Path, *, leak: str = "") -> Path:
    """A fake maintainer vault built from the shipped bundle, with personal state added."""
    config = root / ".obsidian"
    for plugin in PLUGINS:
        shutil.copytree(BUNDLE / "plugins" / plugin, config / "plugins" / plugin)
        (config / "plugins" / plugin / "data.json").write_text('{"secret": "personal"}')
    manifest = config / "plugins" / "bron-workspace" / "manifest.json"
    data = json.loads(manifest.read_text())
    data.update(author="Somebody Personal", authorUrl="https://example.org/me")
    manifest.write_text(json.dumps(data))
    shutil.copytree(BUNDLE / "themes" / "Bron", config / "themes" / "Bron")
    (config / "themes" / "Bron" / "README.md").write_text("theme notes")
    (config / "icons" / "tabler-icons").mkdir(parents=True)
    (config / "icons" / "tabler-icons" / "FileTextAi.svg").write_text("<svg/>")
    (config / "icons" / "tabler-icons.zip").write_bytes(b"big archive")
    (config / "workspace.json").write_text('{"open": "Somebody notes"}')
    (config / "core-plugins.json").write_text(json.dumps({"file-explorer": True, "graph": False}))
    (config / "appearance.json").write_text(json.dumps({"cssTheme": "Bron v2"}))
    if leak:
        with open(config / "plugins" / "xlsx-viewer" / "main.js", "a") as fh:
            fh.write(leak)
    return root


def run_export(source: Path, repo: Path):
    return subprocess.run([sys.executable, str(SCRIPT), str(source), "--repo", str(repo)], capture_output=True, text=True)


def test_export_scrubs_a_source_vault(tmp_path):
    source = make_source(tmp_path / "Source Vault")
    repo = tmp_path / "repo"
    done = run_export(source, repo)
    assert done.returncode == 0, done.stdout + done.stderr
    out = repo / "core" / "Obsidian"
    tpl = repo / "template" / ".obsidian"
    assert not list(out.rglob("data.json"))
    assert not (out / "themes" / "Bron" / "README.md").exists()
    assert json.loads((out / "plugins" / "bron-workspace" / "manifest.json").read_text())["author"] == "Ziggo AI"
    assert not (tpl / "workspace.json").exists()
    assert json.loads((tpl / "appearance.json").read_text())["cssTheme"] == "Bron"
    assert json.loads((tpl / "core-plugins.json").read_text()) == {"file-explorer": True, "graph": False}
    assert "secret" not in (tpl / "plugins" / "colored-tags" / "data.json").read_text()
    assert (tpl / "icons" / "tabler-icons" / "FileTextAi.svg").read_text() == "<svg/>"
    assert not list((tpl / "icons").rglob("*.zip"))


def test_export_refuses_a_personal_path(tmp_path):
    source = make_source(tmp_path / "Source Vault", leak='var p="/Users/someone/vault";')
    done = run_export(source, tmp_path / "repo")
    assert done.returncode == 1
    assert "xlsx-viewer" in done.stdout + done.stderr


def test_export_needs_every_plugin(tmp_path):
    source = make_source(tmp_path / "Source Vault")
    shutil.rmtree(source / ".obsidian" / "plugins" / "xlsx-viewer")
    done = run_export(source, tmp_path / "repo")
    assert done.returncode == 1
    assert "xlsx-viewer" in done.stdout + done.stderr
