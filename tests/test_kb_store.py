import json
from pathlib import Path

import pytest

from bron.kb import store, tools
from bron.loader import load
from vaultkit import set_meta


def make_doc(**kw):
    base = dict(doc_id="", identity="drive:abc", kind="drive", source="https://drive.google.com/file/d/abc/view",
                name="SPA.pdf", path="/x/SPA.pdf", labels={"company": "Acme"}, user_labels={}, read_at="2026-10-03",
                pages=2, status="read")
    base.update(kw)
    base["doc_id"] = base["doc_id"] or store.doc_id_for(base["identity"])
    return store.Doc(**base)


def test_doc_ids_are_stable_and_short():
    assert store.doc_id_for("drive:abc") == store.doc_id_for("drive:abc")
    assert len(store.doc_id_for("drive:abc")) == 16


def test_save_and_load_round_trip(vault):
    doc = make_doc()
    store.save(vault, doc, ["page one", "page two"], [{"text": "page one", "page": 1}])
    again = store.load(vault, doc.doc_id)
    assert again == doc
    assert store.pages(vault, doc.doc_id) == ["page one", "page two"]
    assert store.passages(vault, doc.doc_id) == [{"text": "page one", "page": 1}]
    assert [d.doc_id for d in store.all_docs(vault)] == [doc.doc_id]


def test_user_labels_win(vault):
    doc = make_doc(labels={"company": "Acme", "doc_type": "SPA"}, user_labels={"company": "Acme Holdings"})
    assert store.effective_labels(doc) == {"company": "Acme Holdings", "doc_type": "SPA"}


def test_forget_removes_the_document(vault):
    doc = make_doc()
    store.save(vault, doc, ["x"], [])
    store.forget(vault, doc.doc_id)
    assert store.load(vault, doc.doc_id) is None


def test_corrupt_meta_is_skipped(vault):
    folder = store.kb_dir(vault) / "docs" / "broken"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text("{not json")
    assert store.all_docs(vault) == []


def test_missing_tools_are_installed_with_uv(vault, monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    monkeypatch.setattr("bron.update.find_uv", lambda: "/usr/bin/uv")

    class Done:
        returncode, stdout, stderr = 0, "", ""

    said = []
    tools.ensure(vault, say=said.append, run=lambda argv, **kw: calls.append(argv) or Done())
    assert said == ["Setting up the knowledge base tools (about 300 MB, one time)…"]
    assert calls[0][:3] == ["/usr/bin/uv", "pip", "install"] and "-r" in calls[0]


def test_tool_install_failure_is_plain(vault, monkeypatch):
    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    monkeypatch.setattr("bron.update.find_uv", lambda: None)
    with pytest.raises(store.KbError, match="couldn't be installed"):
        tools.ensure(vault, say=lambda s: None)


def test_a_second_setup_waits_for_the_first_and_never_installs_twice(vault, monkeypatch):
    import fcntl
    import threading
    import time

    present = {"now": True}  # mid-install the tools can already look present: only the lock says it's done
    monkeypatch.setattr(tools, "missing", lambda: [] if present["now"] else ["fastembed"])
    lock = tools._lock_path(vault)
    lock.parent.mkdir(parents=True, exist_ok=True)
    held = open(lock, "a+")
    fcntl.flock(held, fcntl.LOCK_EX)

    def finish():
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()

    threading.Timer(0.3, finish).start()
    started = time.monotonic()
    tools.ensure(vault, say=lambda s: None, run=lambda *a, **k: pytest.fail("installed twice"))
    assert time.monotonic() - started >= 0.25


def test_nothing_to_install_is_silent(vault, monkeypatch):
    monkeypatch.setattr(tools, "missing", lambda: [])
    said = []
    tools.ensure(vault, say=said.append, run=lambda *a, **k: pytest.fail("should not run"))
    assert said == []


def test_knowledge_settings(vault):
    s = load(vault).settings
    assert (s.kb_model_pages, s.kb_max_model_pages) == (True, 20)
    set_meta(vault.settings_file, knowledge={"model_pages": False, "max_model_pages": 5, "labels": False, "doc_types": ["x"]})
    cfg = load(vault)
    assert (cfg.settings.kb_model_pages, cfg.settings.kb_max_model_pages) == (False, 5)
    assert not [i for i in cfg.issues if "knowledge" in i.message]  # 0.7 keys are ignored until the migration removes them


def test_a_stored_fund_label_folds_into_company():
    """Bron 0.7.0 had a "fund" label; it counts as the company when there is none, and never crashes."""
    assert store.effective_labels(make_doc(labels={"company": "", "fund": "Fund I"})) == {"company": "Fund I"}
    assert store.effective_labels(make_doc(labels={"company": "Acme"}, user_labels={"fund": "Fund I"})) == {"company": "Acme"}
    assert store.effective_labels(make_doc(labels={}, user_labels={"fund": "Fund I"})) == {"company": "Fund I"}
    assert store.effective_labels(make_doc(labels=["odd"], user_labels={})) == {}


def test_a_070_meta_with_fund_loads(vault):
    doc = make_doc(labels={"company": "", "fund": "Fund I", "doc_type": "LPA"})
    store.save(vault, doc, ["text"], [{"text": "text", "page": 1}])
    folder = store.kb_dir(vault) / "docs" / doc.doc_id
    (folder / store.USER_LABELS).write_text(json.dumps({"fund": "Fund II"}), encoding="utf-8")
    loaded = store.load(vault, doc.doc_id)
    assert loaded.user_labels == {"fund": "Fund II"}
    assert store.effective_labels(loaded) == {"company": "Fund II", "doc_type": "LPA"}


def test_template_has_inbox_files_and_the_wiki_folders():
    root = Path(__file__).resolve().parents[1] / "template" / "Knowledge"
    for name in ("Inbox", "Files", "Documents", "Organisations", "People", "Topics"):
        assert (root / name).is_dir(), name
    for name in ("Schema.md", "index.md", "log.md"):
        assert (root / name).is_file(), name


def test_requirements_list_is_complete():
    text = tools.KB_REQUIREMENTS.read_text()
    for name in ("pypdfium2", "ocrmac", "python-calamine", "python-docx", "python-pptx", "trafilatura", "fastembed", "numpy"):
        assert name in text


def test_a_resave_that_crashes_never_leaves_the_old_meta_with_new_pages(vault, monkeypatch):
    doc = make_doc()
    store.save(vault, doc, ["old page"], [{"text": "old page", "page": 1}])
    real = store._write

    def crash_on_passages(path, text):
        if path.name == "passages.jsonl":
            raise OSError("disk full")
        real(path, text)

    monkeypatch.setattr(store, "_write", crash_on_passages)
    with pytest.raises(OSError):
        store.save(vault, doc, ["new page"], [{"text": "new page", "page": 1}])
    assert store.load(vault, doc.doc_id) is None  # not complete: re-read next time, never mixed


def _run_ensure(vault, monkeypatch):
    seen = []
    monkeypatch.setattr(tools, "missing", lambda: ["numpy"])
    done = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    tools.ensure(vault, say=lambda *_: None, run=lambda argv, **kw: seen.append(argv) or done)
    return seen


def test_tools_install_from_the_vaults_own_requirements_file(vault, monkeypatch):
    """The engine runs from site-packages, so the requirements file is read from System/Core/Engine."""
    (vault.core / "Engine").mkdir(parents=True, exist_ok=True)
    (vault.core / "Engine" / "kb-requirements.txt").write_text("numpy>=1.26\n")
    assert str(vault.core / "Engine" / "kb-requirements.txt") in _run_ensure(vault, monkeypatch)[0]


def test_tools_fall_back_to_the_source_requirements_file(vault, monkeypatch):
    import shutil

    shutil.rmtree(vault.core / "Engine", ignore_errors=True)
    assert str(tools.KB_REQUIREMENTS) in _run_ensure(vault, monkeypatch)[0]


def test_a_failed_install_shows_one_plain_line(vault, monkeypatch):
    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    monkeypatch.setattr("bron.update.find_uv", lambda: "/usr/bin/uv")
    stderr = ("Resolved 40 packages in 1.2s\n"
              "  × Failed to download `onnxruntime==1.20.0`\n"
              "  ├─▶ Request failed after 3 retries\n"
              "  ╰─▶ error sending request for url (https://files.pythonhosted.org/onnxruntime.whl): No route to host\n"
              "  help: Check your network connection\n\n")
    done = type("R", (), {"returncode": 2, "stdout": "", "stderr": stderr})()
    with pytest.raises(store.KbError) as err:
        tools.ensure(vault, say=lambda *_: None, run=lambda argv, **kw: done)
    message = str(err.value)
    assert message == ("The knowledge base tools couldn't be installed (error sending request for url "
                       "(https://files.pythonhosted.org/onnxruntime.whl): No route to host). "
                       "Check the internet connection and try again.")
    assert "\n" not in message and "Resolved" not in message


def test_a_meta_from_a_newer_bron_still_loads(vault):
    doc = make_doc()
    store.save(vault, doc, ["page"], [{"text": "page", "page": 1}])
    meta = store.kb_dir(vault) / "docs" / doc.doc_id / "meta.json"
    data = json.loads(meta.read_text())
    meta.write_text(json.dumps({**data, "some_later_field": 3}))
    assert store.load(vault, doc.doc_id) == doc
    meta.write_text("[1, 2]")
    assert store.load(vault, doc.doc_id) is None
