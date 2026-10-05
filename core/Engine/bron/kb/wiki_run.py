"""The background wiki run: once a folder (or more than three documents) is read, agent runs write their wiki pages.
Each batch of up to BATCH documents is one ticket for the default agent, run through the ticket runner like any other
(one after another), so each final reply (the summary) reaches the user like any ticket update. Batches keep every run
well inside the runner's time limit."""
from __future__ import annotations

from ..vault import Vault
from . import store
from .store import KbError

SECONDS_PER_DOC = 60  # writing one document's pages (the reading is estimated on its own)
BATCH = 10  # documents per ticket: about 10 minutes of writing, well inside the runner's 30-minute limit

REQUEST = """Read these documents into the wiki, one after another. Load the read-documents skill first and follow it; \
write the pages in Knowledge/ (not in Projects/).
{docs}

Then run the skill's judgement checkup over the pages you touched, and finish with
.bron/bin/bron wiki done --log 'check | <one line: what the checkup found and fixed>'

Nobody is waiting on this run, so don't ask questions: note real conflicts and open questions in your reply instead of \
deciding them. Your final reply is what the user reads: in a few lines, what you learned, what changed or contradicted \
earlier pages, the pages you created and updated, and the documents that couldn't be read."""


def batches(doc_ids: list[str]) -> list[list[str]]:
    """The documents of a run, BATCH at a time, in order."""
    return [doc_ids[i:i + BATCH] for i in range(0, len(doc_ids), BATCH)]


def title(label: str, count: int, part: int = 1, parts: int = 1) -> str:
    what = label or ("1 document" if count == 1 else f"{count} documents")
    return f"Read {what} into the wiki" + (f" (part {part} of {parts})" if parts > 1 else "")


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
    """The ticket of the job's current batch (job.wiki_batch), assigned to the default agent and asked for by the user
    (made once per batch). What couldn't be read goes into the first batch's request only."""
    from ..tickets import new_ticket

    agent = cfg.default_agent
    if agent is None:
        raise KbError("There's no default agent to write the wiki pages (System/Settings.md, default_agent).")
    parts = batches(job.wiki_docs)
    n = job.wiki_batch
    ticket = new_ticket(vault, title=title(job.label, len(job.wiki_docs), n + 1, len(parts)), assignee=agent.key,
                        request=request(vault, parts[n], job.report if n == 0 else ""), requested_by="you")
    return ticket.id
