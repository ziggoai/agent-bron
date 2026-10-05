"""The background wiki run: once a folder (or more than three documents) is read, one agent run writes their wiki pages.
It is a ticket for the default agent, run through the ticket runner like any other, so its final reply (the summary)
reaches the user like any ticket update."""
from __future__ import annotations

from ..vault import Vault
from . import store
from .store import KbError

SECONDS_PER_DOC = 60  # writing one document's pages (the reading is estimated on its own)

REQUEST = """Read these documents into the wiki, one after another. Load the read-documents skill first and follow it; \
write the pages in Knowledge/ (not in Projects/).
{docs}

Then run the skill's judgement checkup over the pages you touched, and finish with
.bron/bin/bron wiki done --log 'check | <one line: what the checkup found and fixed>'

Nobody is waiting on this run, so don't ask questions: note real conflicts and open questions in your reply instead of \
deciding them. Your final reply is what the user reads: in a few lines, what you learned, what changed or contradicted \
earlier pages, the pages you created and updated, and the documents that couldn't be read."""


def title(label: str, count: int) -> str:
    what = label or ("1 document" if count == 1 else f"{count} documents")
    return f"Read {what} into the wiki"


def request(vault: Vault, doc_ids: list[str], report: str = "") -> str:
    lines = []
    for doc_id in doc_ids:
        doc = store.load(vault, doc_id)
        if doc is not None:
            lines.append(f"- {doc.name} — doc {doc.doc_id}")
    text = REQUEST.format(docs="\n".join(lines))
    failed = [line for line in report.splitlines() if line.startswith("Couldn't")]
    if failed:
        text += "\n\nFrom the reading: " + " ".join(failed)
    return text


def start_ticket(vault: Vault, cfg, job) -> str:
    """The run's ticket, assigned to the default agent and asked for by the user (made once per job)."""
    from ..tickets import new_ticket

    agent = cfg.default_agent
    if agent is None:
        raise KbError("There's no default agent to write the wiki pages (System/Settings.md, default_agent).")
    ticket = new_ticket(vault, title=title(job.label, len(job.wiki_docs)), assignee=agent.key,
                        request=request(vault, job.wiki_docs, job.report), requested_by="you")
    return ticket.id
