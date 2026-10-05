"""Reading one thing the user pointed to: read it, fix hard pages, label it from its file and folder names, cut it into passages, store and index it.

Files Bron keeps (the inbox, or a path outside Google Drive) are copied to Knowledge/Files/<YYYY-MM>/; Drive files and
web pages are read where they are. A failure is one plain sentence on that document and never stops a batch.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .. import statefile
from ..vault import Vault
from . import sources, store
from .sources import Item
from .store import Doc, KbError

CURL = ["curl", "-fsSL", "--max-time", "30", "-A", "Mozilla/5.0 (Bron)"]
EXPORT_PART_CHARS = 3000
SUMMARY_LINES = 10
GUESS_PDF_BYTES_PER_PAGE = 50_000
SF_DATALESS = 0x40000000  # macOS: an "online only" Drive file whose bytes aren't on this Mac
NATIVE_NAMES = {".gdoc": "Google Doc", ".gsheet": "Google Sheet", ".gslides": "Google Slides file"}


# ---- where a kept copy goes ----

def _free_name(folder: Path, name: str, taken: set[str]) -> Path:
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = folder / name, 1
    while candidate.exists() or str(candidate) in taken:
        n += 1
        candidate = folder / f"{stem} ({n}){suffix}"
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kept_path(vault: Vault, original: Path) -> Path:
    """The copy Bron keeps of a local file.

    A path outside the inbox always maps to the same copy, so reading it again replaces that document (D3).
    An inbox file maps by its content: a new file dropped under an old name gets a new copy and is a new
    document (the old copy may be the only one left); the same bytes again (a resumed read) reuse their copy."""
    if sources.is_under(original, sources.files_dir(vault)):
        return original  # already one of the kept copies
    path_key = os.path.abspath(original)
    inbox = sources.is_under(original, sources.inbox_dir(vault))
    if inbox and not original.exists():
        # Copied and removed from the inbox just before an interruption: the copy made last for this name.
        mapping = statefile.read_json(store.kb_dir(vault) / "kept.json", {})
        last = mapping.get("inbox:" + path_key)
        return Path(last) if isinstance(last, str) and last else original
    key = "sha256:" + _sha256(original) if inbox else path_key
    chosen: dict[str, str] = {}

    def choose(mapping: dict) -> None:
        previous = mapping.get(key)
        if isinstance(previous, str) and previous:
            chosen["path"] = previous
        else:
            month = sources.files_dir(vault) / time.strftime("%Y-%m")
            target = _free_name(month, original.name, {str(v) for v in mapping.values()})
            mapping[key] = chosen["path"] = str(target)
        if inbox:
            mapping["inbox:" + path_key] = chosen["path"]

    statefile.update_json(store.kb_dir(vault) / "kept.json", {}, choose)
    return Path(chosen["path"])


def _copy(original: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(original, tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def _empty_inbox_of(vault: Vault, original: Path) -> None:
    inbox = sources.inbox_dir(vault)
    try:
        original.unlink()
    except OSError:
        return
    folder = original.parent
    while sources.is_under(folder, inbox) and os.path.abspath(folder) != os.path.abspath(inbox):
        try:
            folder.rmdir()  # only empty folders
        except OSError:
            break
        folder = folder.parent


# ---- reading ----

def fetch(url: str) -> str:
    try:
        done = subprocess.run([*CURL, url], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KbError(f"Couldn't open {url} ({exc.__class__.__name__}).") from exc
    if done.returncode != 0:
        err = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        reason = re.sub(r"^curl: \(\d+\)\s*", "", err[0] if err else "").rstrip(".") or f"error {done.returncode}"
        raise KbError(f"Couldn't open {url} ({reason}).")
    from .readers import decode

    return decode(done.stdout or b"")


def _quoted(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _read(item: Item, ocr, work: Path):
    from . import readers

    if item.kind == "web":
        return readers.read_html(fetch(item.url or item.source), item.url or item.source)
    if item.kind == "native":
        what = NATIVE_NAMES.get(Path(item.name).suffix.lower(), "Google file")
        raise KbError(f"Export this {what} through the Drive connection, then run: bron kb add --file <text file> "
                      f"--source {item.source} --name {_quoted(Path(item.name).stem)}")
    return readers.read(Path(item.path), ocr=ocr, work=work)


def _reason(exc: BaseException, item: Item) -> str:
    if isinstance(exc, KbError):
        return str(exc)
    if isinstance(exc, OSError):
        if item.kind == "drive":
            return ("Google Drive couldn't download this file. Open Google Drive for desktop and make sure the file "
                    "is available.")
        return f"Bron couldn't open this file ({exc.strerror or exc.__class__.__name__})."
    return f"Something went wrong while reading it ({exc.__class__.__name__})."


def _log(vault: Vault, name: str, exc: BaseException) -> None:
    try:
        path = vault.bron_dir / "logs" / "kb-errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {name}: {exc.__class__.__name__}: {exc}\n")
    except OSError:
        pass


def _page_texts(pages) -> list[str]:
    texts = [""] * max((p.number for p in pages), default=0)
    for p in pages:
        texts[p.number - 1] = p.text
    return texts


_DRIVE_TOPS = ("My Drive", "Shared drives", "Meu Drive", "Drives compartilhados")


def _folder_hint(vault: Vault, item: Item) -> str:
    """Where the file sits, for the labels worked out from folder names: at most the last two folder names below the
    Drive root, the vault or a home folder, so nothing above them (a user name, say) is ever used."""
    if item.kind == "web":
        return re.sub(r"^https?://([^/]+).*$", r"\1", item.url or item.source)
    if not item.path:
        return ""
    parent = Path(os.path.abspath(item.path)).parent
    home = Path.home()
    roots = [Path(vault.root), home]
    cloud = home / "Library" / "CloudStorage"
    if os.environ.get("BRON_DRIVE_ROOT") or sources.is_under(parent, cloud):
        roots += sources.drive_roots()
    if sources.is_under(parent, cloud):
        below_cloud = parent.relative_to(os.path.abspath(cloud)).parts
        roots.append(cloud.joinpath(*below_cloud[:2]))  # the account and its top folder: never the account name
        if len(below_cloud) > 2 and below_cloud[1] not in _DRIVE_TOPS:
            roots.append(cloud.joinpath(*below_cloud[:3]))  # "Other computers/<computer name>"
    if len(parent.parts) > 2 and parent.parts[1] == "Users":
        roots.append(Path(*parent.parts[:3]))  # someone else's home folder
    below = parent.parts[1:]
    for root in roots:
        if sources.is_under(parent, root):
            rel = parent.relative_to(os.path.abspath(root)).parts
            if len(rel) < len(below):
                below = rel  # the closest root wins
    return "/".join(below[-2:])


def _process(vault: Vault, cfg, item: Item, doc: Doc, previous: Doc | None, get_pages, *, model_call, embedder,
             keep: tuple[Path, Path] | None = None) -> Doc:
    """get_pages(work) -> pages. keep: (original, kept copy) for files Bron keeps.

    The document is saved with status "indexing" and only marked "read" once the search index has it, so an
    interruption in between is finished by whoever opens the index next (never stale passages in search)."""
    from . import index, models
    from .passages import split

    saving = False
    try:
        with tempfile.TemporaryDirectory(prefix="bron-kb-") as work:  # one per document: readers name images p<N>.png
            pages = get_pages(Path(work))
            pages, sent = models.fix_hard_pages(vault, cfg, doc.name, pages, call=model_call or models.call_image)
        texts = _page_texts(pages)
        if not any(t.strip() for t in texts):
            raise KbError("Bron found no text in this file.")
        doc.pages, doc.scanned, doc.model_pages = len(texts), sum(1 for p in pages if p.ocr), sent
        doc.labels = models.labels_from_names(doc.name, _folder_hint(vault, item), web=item.kind == "web")
        passages = split(pages, store.effective_labels(doc))
        try:
            matrix = index.vectors(vault, doc, passages, embedder)  # the slow part, before anything changes
        except KbError:
            matrix = None  # the meaning model isn't available: keyword search now, meaning search once it downloads
        if keep and keep[0] != keep[1]:
            _copy(*keep)
        saving = True
        store.mark_indexing(vault, doc.doc_id)
        doc.status = "indexing"
        store.save(vault, doc, texts, passages)
        with_vectors = index.put(vault, doc, passages, embedder, vectors=matrix, words_only=matrix is None)
        doc.status, doc.vectors_pending = "read", not with_vectors
        store.save_meta(vault, doc)
        if with_vectors:
            store.clear_indexing(vault, doc.doc_id)  # else the marker stays: the next search adds the vectors
    except Exception as exc:  # noqa: BLE001 - one document's failure never stops the batch
        _log(vault, doc.name, exc)
        doc.status, doc.error = "failed", _reason(exc, item)
        doc.pages = doc.scanned = doc.model_pages = 0
        if saving or previous is None or previous.status not in ("read", "indexing"):
            store.save_meta(vault, doc)
            store.clear_indexing(vault, doc.doc_id)
        # else: the text read last time stays; this attempt is only reported
        return doc
    if keep and keep[0] != keep[1] and sources.is_under(keep[0], sources.inbox_dir(vault)):
        _empty_inbox_of(vault, keep[0])
    return doc


def _stamp(path: str | Path) -> tuple[int, float]:
    """Size and modification time of the original (stat never downloads an online-only Drive file)."""
    try:
        st = os.stat(path)
    except OSError:
        return -1, 0.0
    return st.st_size, st.st_mtime


def _unchanged(previous: Doc | None, size: int, mtime: float) -> bool:
    return (previous is not None and previous.status == "read" and size >= 0 and previous.source_size == size
            and previous.source_mtime == mtime and previous.reader_version == store.READER_VERSION)


def _failed(vault: Vault, item: Item, exc: BaseException) -> Doc:
    _log(vault, item.name, exc)
    return Doc(store.doc_id_for(item.identity), item.identity, item.kind, item.source, item.name, item.path,
               read_at=time.strftime("%Y-%m-%d"), status="failed", error=_reason(exc, item))


def _page_record(vault: Vault, doc_id: str) -> dict:
    """The document's wiki page, when it has one, so reading it again keeps the page's labels for search."""
    linked = store.page_of(vault, doc_id)
    labels = linked.get("labels")
    return {"page": linked.get("page", ""), "page_labels": labels if isinstance(labels, dict) else {}}


def read_item(vault: Vault, cfg, item: Item, *, readers_ocr=None, model_call=None, embedder,
              again: bool = False) -> Doc:
    """Read one item. A document already read whose original hasn't changed (same size and time) isn't read again
    and comes back with status "unchanged", unless `again`. Web pages are always read again."""
    if item.kind == "export":
        return _read_export(vault, cfg, item, embedder=embedder)
    try:  # a file that can't even be looked at (no permission, say) is one failure, never the end of the batch
        keep = None
        identity, source, path = item.identity, item.source, item.path
        if item.kind == "file":
            original = Path(item.path)
            kept = _kept_path(vault, original)
            if not original.exists() and kept.exists():
                original = kept  # copied and removed from the inbox just before an interruption: read the copy
            keep = (original, kept)
            identity, source, path = f"file:{kept}", str(kept), str(kept)
        doc_id = store.doc_id_for(identity)
        previous = store.load(vault, doc_id)
        size, mtime = (-1, 0.0) if item.kind == "web" else _stamp(keep[0] if keep else item.path)
        if not again and _unchanged(previous, size, mtime) and (keep is None or keep[1].exists()):
            if keep and keep[0] != keep[1] and sources.is_under(keep[0], sources.inbox_dir(vault)):
                _empty_inbox_of(vault, keep[0])  # Bron already keeps this very file
            return dataclasses.replace(previous, status="unchanged")
        doc = Doc(doc_id, identity, item.kind, source, item.name, path, user_labels=store.user_labels(vault, doc_id),
                  read_at=time.strftime("%Y-%m-%d"), source_size=size, source_mtime=mtime, **_page_record(vault, doc_id))
    except Exception as exc:  # noqa: BLE001
        return _failed(vault, item, exc)
    read_from = item
    if keep:
        read_from = Item(item.kind, item.identity, item.source, item.name, str(keep[0]), item.url)
    return _process(vault, cfg, item, doc, previous, lambda work: _read(read_from, readers_ocr, work).pages,
                    model_call=model_call, embedder=embedder, keep=keep)


EXPORT_SOURCE = ("--source should be the Google Drive link of the document you exported "
                 "(it starts with https://docs.google.com/ or https://drive.google.com/).")


NOT_TEXT = "--file is only for text exported from a Google Doc, Sheet or Slides; give Bron the Drive link instead."


def read_text_file(text_file: Path | str) -> str:
    """The text of an exported Google file. Anything that isn't UTF-8 text (a PDF, an image, a Word file…) is refused:
    a Drive file is always given to `bron kb add` by its link."""
    try:
        data = Path(text_file).read_bytes()
    except OSError as exc:
        raise KbError(f"There's no readable file at {text_file}.") from exc
    if b"\x00" in data or data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"%PDF"):
        raise KbError(NOT_TEXT)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise KbError(NOT_TEXT) from None


def export_item(text_file: Path | str, source: str, name: str) -> Item:
    """An exported Google file, checked now and read with add_export (in a background job, when the tools are
    still being set up)."""
    source = sources.as_link(source.strip())
    did = sources.drive_id(source)
    if not did:
        raise KbError(EXPORT_SOURCE)
    read_text_file(text_file)  # a plain error now: missing, or not exported text
    return Item("export", f"drive:{did}", source, name.strip(), str(Path(text_file).resolve()), source)


def _read_export(vault: Vault, cfg, item: Item, *, embedder) -> Doc:
    try:
        return add_export(vault, cfg, Path(item.path), item.source, item.name, embedder=embedder)
    except Exception as exc:  # noqa: BLE001 - the text file is gone, say: one failure in the job
        return _failed(vault, item, exc)


def _export_pages(text: str):
    from .readers import Page, split_parts

    blocks: list[str] = []
    for block in (b.strip() for b in re.split(r"\n\s*\n", text)):
        while len(block) > EXPORT_PART_CHARS:
            cut = block.rfind(" ", 0, EXPORT_PART_CHARS)
            cut = cut if cut > 0 else EXPORT_PART_CHARS
            blocks.append(block[:cut].strip())
            block = block[cut:].strip()
        if block:
            blocks.append(block)
    return [Page(p.number, p.text) for p in split_parts(blocks)]


def add_export(vault: Vault, cfg, text_file: Path, source: str, name: str, *, embedder) -> Doc:
    """A Google Doc, Sheet or Slides file exported through the Drive connection, read as that document."""
    source = sources.as_link(source.strip())
    did = sources.drive_id(source)
    if not did:
        raise KbError(EXPORT_SOURCE)
    text = read_text_file(text_file)
    item = Item("native", f"drive:{did}", source, name.strip() or Path(text_file).stem, "", source)
    doc_id = store.doc_id_for(item.identity)
    previous = store.load(vault, doc_id)
    doc = Doc(doc_id, item.identity, "native", source, item.name, "",
              user_labels=store.user_labels(vault, doc_id), read_at=time.strftime("%Y-%m-%d"),
              **_page_record(vault, doc_id))
    return _process(vault, cfg, item, doc, previous, lambda work: _export_pages(text), model_call=None, embedder=embedder)


# ---- sizes, for asking first ----

def online_only(path: str) -> bool:
    """A Drive file whose bytes are still in the cloud (opening it would download it). stat never downloads."""
    try:
        return bool(getattr(os.stat(path), "st_flags", 0) & SF_DATALESS)
    except OSError:
        return False


def page_count(item: Item) -> int:
    """Pages in one item: PDFs on this Mac are opened to count; online-only files are estimated; others count as one."""
    if item.kind not in ("file", "drive") or Path(item.path).suffix.lower() != ".pdf":
        return 1
    if online_only(item.path):
        return guess_pages(item)
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(item.path)
        try:
            return max(1, len(doc))
        finally:
            doc.close()
    except Exception:  # noqa: BLE001 - a damaged or locked PDF counts as one page here
        return 1


def looks_scanned(item: Item) -> bool:
    """A photo, or a PDF whose first page has almost no text: Mac text recognition makes these slow to read.
    Only files already on this Mac are opened; an online-only file is never downloaded just to check."""
    from .readers import IMAGE_EXT, MIN_TEXT_CHARS

    if item.kind not in ("file", "drive") or not item.path:
        return False
    suffix = Path(item.path).suffix.lower()
    if suffix in IMAGE_EXT:
        return True
    if suffix != ".pdf" or online_only(item.path):
        return False
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(item.path)
        try:
            if not len(doc):
                return False
            text = doc[0].get_textpage().get_text_range()
        finally:
            doc.close()
    except Exception:  # noqa: BLE001 - damaged or locked: reading it will say so
        return False
    return len(text.strip()) < MIN_TEXT_CHARS


def guess_pages(item: Item) -> int:
    """Pages without opening anything (big folders on Drive would be downloaded just to count)."""
    if item.kind not in ("file", "drive") or Path(item.path).suffix.lower() != ".pdf":
        return 1
    try:
        return max(1, os.stat(item.path).st_size // GUESS_PDF_BYTES_PER_PAGE)
    except OSError:
        return 1


# ---- the one-paragraph report ----

def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def label_line(doc: Doc) -> str:
    labels = store.effective_labels(doc)
    parts = [labels.get("company"), labels.get("doc_type"), labels.get("date")]
    return " · ".join(str(p) for p in parts if p)


def summary(docs: list[Doc], notes: list[str] | tuple = ()) -> str:
    """What was read (with labels), what was already read and unchanged, what couldn't be read and why.
    `notes`: sentences about links that weren't found."""
    read = [d for d in docs if d.status == "read"]
    unchanged = [d for d in docs if d.status == "unchanged"]
    failed = [d for d in docs if d.status not in ("read", "unchanged")]
    lines: list[str] = []
    if read:
        scanned = sum(d.scanned for d in read)
        model = sum(d.model_pages for d in read)
        first = (f"Read {plural(len(read), 'document')} ({plural(scanned, 'scanned page')}, "
                 f"{plural(model, 'page')} read by the model)")
        waiting = sum(1 for d in read if d.vectors_pending)
        if waiting:
            whom = ("it" if len(read) == 1 else "them") if waiting == len(read) else f"{waiting} of them"
            first += f"; meaning search for {whom} will be ready once the model downloads"
        lines.append(first + ".")
        for d in read[:SUMMARY_LINES]:
            labels = label_line(d)
            lines.append(f"- {d.name}" + (f" — {labels}" if labels else ""))
        if len(read) > SUMMARY_LINES:
            lines.append(f"…and {len(read) - SUMMARY_LINES} more; see `bron kb list`")
    if unchanged:
        names = ", ".join(d.name for d in unchanged[:SUMMARY_LINES]) + (", …" if len(unchanged) > SUMMARY_LINES else "")
        lines.append(f"Already read, unchanged: {names} ({len(unchanged)} unchanged, skipped; "
                     f"add --again to read {'it' if len(unchanged) == 1 else 'them'} again).")
    if failed:
        shown = "; ".join(f"{d.name} ({d.error.rstrip('.')})" for d in failed[:SUMMARY_LINES])
        more = f"; …and {len(failed) - SUMMARY_LINES} more, see `bron kb list`" if len(failed) > SUMMARY_LINES else ""
        lines.append(f"Couldn't read: {shown}{more}.")
    lines += [str(n) for n in notes]
    return "\n".join(lines) if lines else "There was nothing to read."
