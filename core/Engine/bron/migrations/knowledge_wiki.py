"""0.8.0: the knowledge base becomes a wiki.

Knowledge/ gets Schema.md (with the vault's own knowledge.doc_types, when it had some), index.md, log.md and the four
page-type folders, wherever they're missing; knowledge.labels and knowledge.doc_types leave System/Settings.md (a
document's labels now come from its wiki page). Nothing is deleted; documents already read show up as "read but no page
yet" until their pages are written."""
from __future__ import annotations

from .. import frontmatter as fm
from ..fmedit import EditError, edit_meta
from ..kb import schema, store
from ..loader import Config
from ..setup import Change

SUMMARY = ("Your knowledge base becomes a wiki: Knowledge/ gets Schema.md (its rules, with your document types), "
           "index.md, log.md and folders for documents, organisations, people and topics.")
OLD_KEYS = ("labels", "doc_types")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def build(cfg: Config) -> Change:
    vault = cfg.vault
    folder = vault.knowledge_dir
    writes: dict[str, str] = {}
    folders: list[str] = []
    try:
        settings_text = vault.settings_file.read_text(encoding="utf-8")
        knowledge = fm.parse(settings_text).meta.get("knowledge")
    except (OSError, UnicodeDecodeError, fm.FrontmatterError):
        settings_text, knowledge = "", None
    knowledge = knowledge if isinstance(knowledge, dict) else {}
    own = schema.clean_list(knowledge.get("doc_types"))
    if own and not any(t.lower() == "other" for t in own):
        own.append("other")
    keep_types = False  # Schema.md can't take the list: it stays in Settings rather than being lost
    target = schema.schema_path(vault)
    try:
        if not target.exists():
            text = schema.template_text(vault)
            writes[f"Knowledge/{schema.SCHEMA}"] = schema.with_doc_types(text, own) if own else text
        elif own:
            writes[f"Knowledge/{schema.SCHEMA}"] = schema.with_doc_types(target.read_text(encoding="utf-8"), own)
    except (OSError, UnicodeDecodeError, EditError):
        keep_types = True
    if not (folder / schema.INDEX).exists():
        writes[f"Knowledge/{schema.INDEX}"] = schema.EMPTY_INDEX
    if not (folder / schema.LOG).exists():
        writes[f"Knowledge/{schema.LOG}"] = schema.LOG_HEADER
    folders = [f"Knowledge/{name}" for name in schema.PAGE_TYPES if not (folder / name).is_dir()]
    drop = [key for key in OLD_KEYS if key in knowledge and not (key == "doc_types" and keep_types)]
    if drop and settings_text:
        try:
            writes["System/Settings.md"] = edit_meta(settings_text, {"knowledge": {k: v for k, v in knowledge.items()
                                                                                   if k not in drop}})
        except EditError:
            pass  # an unusual settings block stays as it is; Bron ignores the old keys
    if not writes and not folders:
        return Change(done="")  # nothing to say
    summary = ["Turn Knowledge/ into a wiki: add Schema.md, index.md, log.md and the page folders where they're missing."]
    if drop:
        summary.append("Move your document types into Knowledge/Schema.md and remove knowledge.labels and "
                       "knowledge.doc_types from System/Settings.md.")
    done = SUMMARY
    waiting = sum(1 for d in store.all_docs(vault) if d.status == "read")
    if waiting:
        done += (f" {_plural(waiting, 'document')} you read before {'has' if waiting == 1 else 'have'} no wiki page yet; "
                 "ask Bron to \"finish the wiki pages\" when you want them.")
    return Change(summary=summary, writes=writes, folders=folders, done=done)
