import pytest

from bron.kb import sources
from kbkit import fake_drive, set_drive_id


@pytest.mark.parametrize("link, expected", [
    ("https://drive.google.com/file/d/1o0oTQu3rBac/view?usp=sharing", "1o0oTQu3rBac"),
    ("https://docs.google.com/document/d/1AbC-dEf_123/edit", "1AbC-dEf_123"),
    ("https://docs.google.com/spreadsheets/d/1Xy_Z/edit#gid=0", "1Xy_Z"),
    ("https://docs.google.com/presentation/d/1Pq/edit", "1Pq"),
    ("https://drive.google.com/drive/folders/0B_folder123", "0B_folder123"),
    ("https://drive.google.com/drive/u/0/folders/1FoLd", "1FoLd"),
    ("https://drive.google.com/open?id=1OpEn", "1OpEn"),
    ("https://drive.google.com/uc?id=1Uc&export=download", "1Uc"),
    ("https://example.com/report", None),
])
def test_drive_id_from_links(link, expected):
    assert sources.drive_id(link) == expected


def test_drive_file_and_folder_links_resolve(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    folder = root / "Portfolio" / "Acme"
    folder.mkdir(parents=True)
    spa = folder / "2025.01.21 - SPA.pdf"
    spa.write_bytes(b"%PDF-1.4")
    set_drive_id(folder, "FOLDER1")
    set_drive_id(spa, "FILE1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    items, failed = sources.resolve(vault, ["https://drive.google.com/file/d/FILE1/view"])
    assert failed == [] and items[0].kind == "drive" and items[0].identity == "drive:FILE1" and items[0].path == str(spa)
    items, failed = sources.resolve(vault, ["https://drive.google.com/drive/folders/FOLDER1"])
    assert [i.name for i in items] == ["2025.01.21 - SPA.pdf"]


def test_found_ids_are_cached_and_revalidated(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    f = root / "a.pdf"
    f.write_bytes(b"x")
    set_drive_id(f, "ID1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    assert sources.find_drive_item(vault, "ID1") == f
    moved = root / "b.pdf"
    f.rename(moved)
    assert sources.find_drive_item(vault, "ID1") == moved  # stale cache entry re-checked, then found again


def test_unknown_drive_id_is_a_plain_failure(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(fake_drive(tmp_path)))
    items, failed = sources.resolve(vault, ["https://drive.google.com/file/d/NOPE/view", "https://drive.google.com/file/d/NOPE2/view"])
    assert items == [] and len(failed) == 2 and "Google Drive on this Mac" in failed[0]


def test_google_native_files_need_export(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    stub = root / "Fund II LPA.gdoc"
    stub.write_text("{}")
    set_drive_id(stub, "DOC1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    items, _ = sources.resolve(vault, ["https://docs.google.com/document/d/DOC1/edit"])
    assert items[0].kind == "native" and items[0].source == "https://drive.google.com/open?id=DOC1"


def test_paths_inbox_and_urls(vault, tmp_path):
    f = tmp_path / "memo.docx"
    f.write_bytes(b"x")
    inbox = vault.root / "Knowledge" / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "deck.pptx").write_bytes(b"x")
    (inbox / ".DS_Store").write_bytes(b"x")
    items, failed = sources.resolve(vault, [str(f), "https://example.com/news#top", str(tmp_path / "missing.pdf")], inbox=True)
    kinds = {(i.kind, i.name) for i in items}
    assert kinds == {("file", "memo.docx"), ("web", "https://example.com/news"), ("file", "deck.pptx")}
    assert any("There's no file at" in line for line in failed)
    web = next(i for i in items if i.kind == "web")
    assert web.identity == "web:https://example.com/news"


def _drive_with(tmp_path, monkeypatch, names):
    root = fake_drive(tmp_path)
    paths = []
    for i, n in enumerate(names):
        p = root / n
        p.write_bytes(b"x")
        set_drive_id(p, f"ID{i}")
        paths.append(p)
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    return root, paths


def test_unknown_ids_share_one_walk(vault, tmp_path, monkeypatch):
    root, _ = _drive_with(tmp_path, monkeypatch, ["a.pdf", "b.pdf", "c.pdf"])
    reads = []
    real = sources._read_attr
    monkeypatch.setattr(sources, "_read_attr", lambda p: reads.append(str(p)) or real(p))
    items, failed = sources.resolve(vault, ["https://drive.google.com/file/d/N1/view", "https://drive.google.com/file/d/N2/view"])
    assert len(failed) == 2
    assert len(reads) == 3  # each file read once for the whole batch, not once per link


def test_budget_exceeded_is_a_plain_failure(vault, tmp_path, monkeypatch):
    _drive_with(tmp_path, monkeypatch, ["a.pdf", "b.pdf", "c.pdf"])
    monkeypatch.setattr(sources, "MAX_ENTRIES", 1)
    items, failed = sources.resolve(vault, ["https://drive.google.com/file/d/NOPE/view"])
    assert items == [] and "searched for 2 minutes" in failed[0] and "Google Drive on this Mac" in failed[0]


def test_cache_is_saved_when_the_walk_is_interrupted(vault, tmp_path, monkeypatch):
    from bron.kb.store import kb_dir
    from bron import statefile
    _drive_with(tmp_path, monkeypatch, ["a.pdf", "b.pdf", "c.pdf"])
    monkeypatch.setattr(sources, "SAVE_EVERY", 1)
    real = sources._read_attr
    calls = []

    def flaky(p):
        calls.append(p)
        if len(calls) == 3:
            raise KeyboardInterrupt
        return real(p)
    monkeypatch.setattr(sources, "_read_attr", flaky)
    with pytest.raises(KeyboardInterrupt):
        sources.find_drive_item(vault, "NOPE")
    assert len(statefile.read_json(kb_dir(vault) / "drive-ids.json", {})) == 2


def test_dead_cache_entries_are_dropped_on_save(vault, tmp_path, monkeypatch):
    from bron.kb.store import kb_dir
    from bron import statefile
    _, (a, b) = _drive_with(tmp_path, monkeypatch, ["a.pdf", "b.pdf"])
    sources.find_drive_item(vault, "NOPE")
    cache = kb_dir(vault) / "drive-ids.json"
    assert set(statefile.read_json(cache, {})) == {"ID0", "ID1"}
    a.unlink()
    sources.find_drive_item(vault, "NOPE")
    assert set(statefile.read_json(cache, {})) == {"ID1"}


@pytest.mark.parametrize("link, expected", [
    ("https://docs.google.com/document/u/0/d/1AbC/edit", "1AbC"),
    ("https://docs.google.com/spreadsheets/d/e/2PACX-1vQ/pubhtml", None),
])
def test_more_link_forms(link, expected):
    assert sources.drive_id(link) == expected


def test_path_with_drive_id_is_a_drive_item(vault, tmp_path, monkeypatch):
    _, (a,) = _drive_with(tmp_path, monkeypatch, ["a.pdf"])
    items, _ = sources.resolve(vault, [str(a)])
    assert items[0].kind == "drive" and items[0].identity == "drive:ID0"


def test_hidden_items_skipped_in_folder_link(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    folder = root / "F"
    (folder / ".hidden").mkdir(parents=True)
    (folder / ".hidden" / "x.pdf").write_bytes(b"x")
    (folder / ".secret.pdf").write_bytes(b"x")
    (folder / "ok.pdf").write_bytes(b"x")
    set_drive_id(folder, "F1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    items, _ = sources.resolve(vault, ["https://drive.google.com/drive/folders/F1"])
    assert [i.name for i in items] == ["ok.pdf"]


def test_cached_path_with_a_different_id_is_refound(vault, tmp_path, monkeypatch):
    root, (a, b) = _drive_with(tmp_path, monkeypatch, ["a.pdf", "b.pdf"])
    assert sources.find_drive_item(vault, "ID0") == a
    a.unlink()
    a.write_bytes(b"y")
    set_drive_id(a, "OTHER")
    assert sources.find_drive_item(vault, "ID0") is None
    assert sources.find_drive_item(vault, "OTHER") == a


def test_inbox_files_are_always_kept_copies_even_with_a_drive_id(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    inbox = vault.root / "Knowledge" / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    dragged = inbox / "spa.pdf"
    dragged.write_bytes(b"%PDF-1.4")
    set_drive_id(dragged, "DRAGGED1")  # dragged out of the Drive folder: the attribute travels with it
    items, _ = sources.resolve(vault, [], inbox=True)
    assert [(i.kind, i.identity) for i in items] == [("file", f"file:{dragged}")]
    items, _ = sources.resolve(vault, [str(dragged)])  # the same file named by its path
    assert items[0].kind == "file"
    in_drive = root / "spa.pdf"
    in_drive.write_bytes(b"%PDF-1.4")
    set_drive_id(in_drive, "INDRIVE1")
    assert sources.resolve(vault, [str(in_drive)])[0][0].kind == "drive"  # Drive files by path are read in place


@pytest.mark.parametrize("link, expected", [
    ("drive.google.com/file/d/1o0oTQu3rBac/view", "1o0oTQu3rBac"),
    ("docs.google.com/document/d/1AbC-dEf_123/edit", "1AbC-dEf_123"),
    ("drive.google.com/drive/folders/0B_folder123", "0B_folder123"),
])
def test_drive_links_without_https_are_links(link, expected):
    assert sources.drive_id(link) == expected


def test_a_schemeless_drive_link_resolves(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    spa = root / "spa.pdf"
    spa.write_bytes(b"%PDF-1.4")
    set_drive_id(spa, "FILE7")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    items, failed = sources.resolve(vault, ["drive.google.com/file/d/FILE7/view?usp=sharing"])
    assert failed == [] and items[0].identity == "drive:FILE7" and items[0].path == str(spa)


def _shared_layout(tmp_path, monkeypatch):
    """Drive for desktop's layout: My Drive beside .shortcut-targets-by-id/<folder id>/<folder name>/."""
    account = tmp_path / "GoogleDrive-test"
    my_drive = account / "My Drive"
    my_drive.mkdir(parents=True)
    shared = account / sources.SHORTCUTS / "SHARED1" / "Leases"
    shared.mkdir(parents=True)
    lease = shared / "lease.pdf"
    lease.write_bytes(b"%PDF-1.4")
    set_drive_id(lease, "LEASE1")
    set_drive_id(shared, "SHARED1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(my_drive))
    return account, shared, lease


def test_a_file_in_a_folder_shared_with_the_user_is_found(vault, tmp_path, monkeypatch):
    _, _, lease = _shared_layout(tmp_path, monkeypatch)
    items, failed = sources.resolve(vault, ["https://drive.google.com/file/d/LEASE1/view"])
    assert failed == [] and items[0].path == str(lease) and items[0].identity == "drive:LEASE1"


def test_a_shared_folder_link_goes_straight_to_its_shortcut_folder(vault, tmp_path, monkeypatch):
    _, _, lease = _shared_layout(tmp_path, monkeypatch)
    walked = []
    real = sources._search
    monkeypatch.setattr(sources, "_search", lambda vault, ids, roots=None: walked.append(set(ids)) or real(vault, ids, roots))
    found = sources.resolve_targets(vault, ["https://drive.google.com/drive/folders/SHARED1"])
    assert [i.path for i in found.items] == [str(lease)] and found.failed == [] and found.folders == ["Leases"]
    assert walked == []  # found by its id at once: no walk through the whole Drive


def test_the_real_drive_layout_includes_shared_folders(tmp_path, monkeypatch):
    monkeypatch.delenv("BRON_DRIVE_ROOT", raising=False)
    account = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-someone@example.com"
    for sub in ("My Drive", ".shortcut-targets-by-id/ABC/Team", ".Trash"):
        (account / sub).mkdir(parents=True)
    roots = sources.drive_roots(home=tmp_path)
    assert account / "My Drive" in roots and account / sources.SHORTCUTS in roots
    assert all(r.name != ".Trash" for r in roots)
    assert sources.shortcut_dirs(home=tmp_path) == [account / sources.SHORTCUTS]


def test_other_hidden_folders_stay_skipped_and_shortcuts_are_walked(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    (root / ".hidden").mkdir()
    (root / ".hidden" / "x.pdf").write_bytes(b"x")
    set_drive_id(root / ".hidden" / "x.pdf", "HID1")
    inner = root / sources.SHORTCUTS / "F9" / "Shared"
    inner.mkdir(parents=True)
    (inner / "y.pdf").write_bytes(b"y")
    set_drive_id(inner / "y.pdf", "SH1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    assert sources.find_drive_item(vault, "HID1") is None
    assert sources.find_drive_item(vault, "SH1") == inner / "y.pdf"


def test_folders_asked_for_are_named(vault, tmp_path):
    folder = tmp_path / "Receipts"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    single = tmp_path / "b.txt"
    single.write_text("b")
    found = sources.resolve_targets(vault, [str(folder), str(single)])
    assert found.folders == ["Receipts"] and len(found.items) == 2
    assert sources.resolve_targets(vault, [], inbox=True).folders == []
