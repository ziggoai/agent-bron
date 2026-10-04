import json
import re
import shlex

from bron.agents_md import render_agents_md
from bron.check import run_checks
from bron.cli import build_parser
from bron.kb import cli as kb_cli, health, ingest, store
from bron.kb.store import Doc
from bron.loader import load


def codes(vault):
    return {i.code: i for i in run_checks(load(vault))}


def put_doc(vault, name, status="read", error=""):
    doc = Doc(doc_id=store.doc_id_for(name), identity=name, kind="file", source=name, name=name, path=name,
              status=status, error=error)
    store.save(vault, doc, ["page one"], [])
    return doc


def test_a_clean_knowledge_base_has_no_issues(vault):
    put_doc(vault, "a.pdf")
    assert not [c for c in codes(vault) if c.startswith("kb.")]


def test_failed_documents_warn_with_a_count(vault):
    put_doc(vault, "a.pdf")
    put_doc(vault, "b.pdf", status="failed", error="it is locked")
    put_doc(vault, "c.pdf", status="failed", error="it is empty")
    issue = codes(vault)["kb.failed-documents"]
    assert issue.level == "warning"
    assert "2 documents couldn't be read" in issue.message and "bron kb list --failed" in issue.message


def test_one_failed_document_is_singular(vault):
    put_doc(vault, "b.pdf", status="failed", error="x")
    assert "1 document couldn't be read" in codes(vault)["kb.failed-documents"].message


def test_an_unreadable_index_warns(vault):
    folder = store.kb_dir(vault)
    folder.mkdir(parents=True)
    (folder / "index.db").write_bytes(b"this is not a database" * 100)
    issue = codes(vault)["kb.index-unreadable"]
    assert issue.level == "warning" and "rebuilt" in issue.message


def test_a_missing_index_is_fine(vault):
    assert "kb.index-unreadable" not in codes(vault)


def test_health_never_breaks_the_check(vault, monkeypatch):
    def boom(cfg):
        raise RuntimeError("boom")

    monkeypatch.setattr(health, "issues", boom)
    assert isinstance(run_checks(load(vault)), list)


def test_list_failed_shows_only_failed_documents(vault, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    put_doc(vault, "a.pdf")
    put_doc(vault, "b.pdf", status="failed", error="it is locked")
    args = build_parser().parse_args(["kb", "list", "--failed"])
    assert kb_cli.handle(args, vault) == 0
    out = capsys.readouterr().out
    assert "b.pdf" in out and "a.pdf" not in out


def test_list_failed_with_none_says_so(vault, capsys):
    put_doc(vault, "a.pdf")
    kb_cli.handle(build_parser().parse_args(["kb", "list", "--failed"]), vault)
    assert "No documents failed" in capsys.readouterr().out


def test_agents_md_has_the_knowledge_section_and_its_commands_parse(vault):
    text = render_agents_md(load(vault))
    assert "## Knowledge base" in text
    section = text.split("## Knowledge base", 1)[1].split("\n## ", 1)[0]
    assert len(section) <= 1600
    commands = re.findall(r"\.bron/bin/bron\s+[^\n`]+", section)
    assert len(commands) >= 6
    parser = build_parser()
    for cmd in commands:
        for keep in (False, True):
            norm = cmd.replace(".bron/bin/bron", "").strip()
            norm = re.sub(r"\[(.*?)\]", r"\1", norm) if keep else re.sub(r"\s*\[.*?\]\s*", " ", norm)
            norm = norm.replace("…", "x").replace("<link or path>", "x").replace("<file>", "x").replace("<link>", "https://x.example")
            norm = norm.replace("<title>", "x").replace("<question>", "x").replace("<document>", "x").replace("N-M", "1-2")
            norm = norm.replace("--company X", "--company X").replace("--type T", "--type T")
            norm = norm.replace("--company x --type x --date x", "--company x --type x --date 2025-01-01")
            argv = shlex.split(" ".join(norm.split()).replace(" ...", ""))
            parser.parse_args(argv)


def test_agents_md_asks_for_a_long_timeout_on_the_first_knowledge_command(vault):
    text = render_agents_md(load(vault))
    section = text.split("## Knowledge base", 1)[1].split("\n## ", 1)[0]
    assert ("The first `bron kb` command in a vault can take a few minutes; use a long command timeout (10 minutes)."
            in section)
    assert len(section) <= 1600


def test_the_manual_says_online_only_drive_files_are_fine():
    from pathlib import Path

    manual = (Path(__file__).resolve().parents[1] / "core" / "Manual" / "knowledge.md").read_text()
    assert "not online-only" not in manual
    assert "Online-only files are downloaded as they're read" in manual


def test_the_live_knowledge_test_always_stops_its_helper():
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent / "live" / "test_knowledge.py").read_text()
    fixture = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "vault")
    tries = [n for n in ast.walk(fixture) if isinstance(n, ast.Try) and n.finalbody]
    assert tries, "the vault fixture has no try/finally"
    cleanup = ast.unparse(tries[0].finalbody[0]) if tries[0].finalbody else ""
    assert any("stop_helper" in ast.unparse(s) for t in tries for s in t.finalbody), cleanup
    assert any(isinstance(s, ast.Expr) and isinstance(s.value, ast.Yield) for t in tries for s in t.body)
