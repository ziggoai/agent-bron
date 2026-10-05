"""The background wiki run: after a folder is read, one agent run (a ticket through the ticket runner) writes its pages."""
import fcntl

import pytest

from bron.kb import jobs, notices, sources, store, wiki
from bron.tickets import find_ticket, load_ticket
from kbkit import FakeTicketRunner, fake_embed, make_text_pdf, stored_doc, write_page


def folder_of(tmp_path, n, name="Leases"):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    for i in range(n):
        make_text_pdf(folder / f"lease{i}.pdf", [f"Lease number {i}: Harbor Bakery rents shop {i} from Northwind Properties Ltd."])
    return folder


def read_folder(vault, tmp_path, n=3, name="Leases", runner=None):
    found = sources.resolve_targets(vault, [str(folder_of(tmp_path, n, name))])
    job = jobs.create(vault, found.items, wiki=True, label=f"the {found.folders[0]} folder")
    runner = runner or FakeTicketRunner()
    jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    return jobs.load(vault, job.job_id), runner


def hold_the_wiki_lock(vault):
    path = store.kb_dir(vault) / "jobs" / "wiki.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    held = open(path, "a+")
    fcntl.flock(held, fcntl.LOCK_EX)  # another run is writing the wiki
    return held


def test_a_folder_is_read_then_written_into_the_wiki_by_one_ticket(vault, tmp_path):
    job, runner = read_folder(vault, tmp_path)
    assert job.status == "done" and job.wiki_status == "done" and len(job.wiki_docs) == 3
    assert runner.calls == [job.ticket]
    ticket = load_ticket(find_ticket(vault, job.ticket))
    assert ticket.title == "Read the Leases folder into the wiki"
    assert ticket.assignee == "bron" and ticket.requested_by == "you" and ticket.status == "in-review"
    assert "read-documents skill" in ticket.request and "wiki done --log 'check |" in ticket.request
    assert all(f"doc {doc_id}" in ticket.request for doc_id in job.wiki_docs)
    assert job.report.startswith("Read 3 documents")
    assert notices.take(vault) == []  # the ticket's update is the summary
    assert jobs.status_lines(vault)[0] == jobs.IDLE


def test_a_failed_wiki_run_tells_the_user_what_was_read(vault, tmp_path):
    job, _ = read_folder(vault, tmp_path, runner=FakeTicketRunner(status="blocked", message="T-0001 is blocked: the run failed"))
    assert job.wiki_status == "failed"
    told = notices.take(vault)
    assert len(told) == 1 and told[0].startswith("Read 3 documents")
    assert "couldn't write all their wiki pages (T-0001 is blocked: the run failed)" in told[0]
    assert told[0].endswith('Say "finish the wiki pages" to write the rest.')


def test_what_could_not_be_read_goes_into_the_request(vault, tmp_path):
    (folder_of(tmp_path, 2) / "broken.zip").write_bytes(b"x")
    job, _ = read_folder(vault, tmp_path, n=0)
    request = load_ticket(find_ticket(vault, job.ticket)).request
    assert "From the reading: Couldn't read: broken.zip (Bron can't read .zip files yet)." in request


def test_one_wiki_writer_at_a_time(vault, tmp_path):
    runner = FakeTicketRunner()
    held = hold_the_wiki_lock(vault)
    try:
        job, _ = read_folder(vault, tmp_path, runner=runner)
        assert job.status == "done" and job.wiki_status == "waiting" and runner.calls == []
        assert any(line.startswith("Waiting to write the Leases folder into the wiki (since ")
                   for line in jobs.status_lines(vault))
    finally:
        held.close()
    jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    assert jobs.load(vault, job.job_id).wiki_status == "done" and len(runner.calls) == 1


def test_documents_read_in_a_conversation_wait_behind_the_folder_being_written(vault, tmp_path):
    order = []

    def write(vault_, ticket):
        order.append(ticket.title)
        if len(order) == 1:  # while the folder is written, a conversation reads two more documents
            assert jobs.wiki_active(vault) and not jobs.runner_active(vault)  # the reader is free meanwhile
            a, b = stored_doc(vault, "a.pdf", ["A"]), stored_doc(vault, "b.pdf", ["B"])
            jobs.create_wiki(vault, [a.doc_id, b.doc_id])

    read_folder(vault, tmp_path, runner=FakeTicketRunner(write=write))
    assert order == ["Read the Leases folder into the wiki", "Read 2 documents into the wiki"]
    assert jobs.wiki_pending(vault) == []


def test_an_interrupted_wiki_run_resumes_then_gives_up_plainly(vault, tmp_path):
    class LidCloses(FakeTicketRunner):
        def __call__(self, vault, ticket_id, **kw):
            self.calls.append(ticket_id)
            raise KeyboardInterrupt

    runner = LidCloses()
    with pytest.raises(KeyboardInterrupt):
        read_folder(vault, tmp_path, runner=runner)
    job = jobs.all_jobs(vault)[-1]
    assert job.wiki_status == "writing" and job.wiki_attempts == 1 and not jobs.wiki_active(vault)
    assert [j.job_id for j in jobs.stalled(vault)] == [job.job_id]  # a new session starts a runner for it
    assert any("stopped part-way" in line for line in jobs.status_lines(vault))
    with pytest.raises(KeyboardInterrupt):
        jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    assert len(runner.calls) == 2 and runner.calls[0] == runner.calls[1]  # the same ticket, run again
    jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    final = jobs.load(vault, job.job_id)
    assert final.wiki_status == "failed" and len(runner.calls) == 2  # never a third time
    told = notices.take(vault)[0]
    assert "it stopped twice before finishing" in told and "finish the wiki pages" in told
    assert len(store.all_docs(vault)) == 3  # what was read stays searchable


def test_documents_that_already_have_pages_are_not_written_again(vault, tmp_path):
    job, runner = read_folder(vault, tmp_path, n=2)
    first, second = job.wiki_docs
    write_page(vault, "Documents/Lease 0.md", type="document", summary="Lease 0", doc=first)
    wiki.link_documents(vault, wiki.all_pages(vault))
    again = jobs.create(vault, sources.resolve_targets(vault, [str(tmp_path / "Leases")]).items, wiki=True)
    jobs.run(vault, again.job_id, embedder=fake_embed, run_ticket=runner)
    done = jobs.load(vault, again.job_id)
    assert done.read == [] and sorted(done.unchanged) == sorted([first, second]) and done.wiki_docs == [second]
    write_page(vault, "Documents/Lease 1.md", type="document", summary="Lease 1", doc=second)
    wiki.link_documents(vault, wiki.all_pages(vault))
    last = jobs.create(vault, sources.resolve_targets(vault, [str(tmp_path / "Leases")]).items, wiki=True)
    jobs.run(vault, last.job_id, embedder=fake_embed, run_ticket=runner)
    assert jobs.load(vault, last.job_id).wiki_status == "" and len(runner.calls) == 2
    assert notices.take(vault)[-1].startswith("Already read, unchanged: lease0.pdf, lease1.pdf")


def test_cancel_stops_wiki_runs_that_are_waiting(vault, tmp_path):
    held = hold_the_wiki_lock(vault)
    try:
        job, _ = read_folder(vault, tmp_path)
        texts = jobs.cancel(vault)
    finally:
        held.close()
    assert jobs.load(vault, job.job_id).wiki_status == "cancelled" and jobs.wiki_pending(vault) == []
    assert any(t.startswith("Read 3 documents") and "the wiki pages for 3 documents weren't written" in t
               and "finish the wiki pages" in t for t in texts)


def test_jobs_waiting_for_the_wiki_are_never_pruned(vault):
    waiting = jobs.create_wiki(vault, ["0000000000000000"])
    for _ in range(jobs.KEEP_FINISHED + 2):
        finished = jobs.create(vault, [])
        finished.status = "done"
        jobs.save(vault, finished)
    jobs.create(vault, [])  # creating a job prunes the old finished ones
    assert jobs.load(vault, waiting.job_id) is not None


def test_without_a_default_agent_the_run_fails_plainly(vault, tmp_path):
    from vaultkit import set_meta

    set_meta(vault.settings_file, default_agent="Nobody")
    job, runner = read_folder(vault, tmp_path)
    assert job.wiki_status == "failed" and runner.calls == []
    assert "There's no default agent to write the wiki pages" in notices.take(vault)[0]

def test_a_failed_wiki_run_says_which_documents_got_pages(vault, tmp_path):
    def write(vault_, ticket):  # the run wrote lease0's page, then fell over
        job = jobs.wiki_pending(vault_)[0]
        write_page(vault_, "Documents/Lease 0.md", type="document", summary="Lease 0", doc=job.wiki_docs[0])
        wiki.link_documents(vault_, wiki.all_pages(vault_))

    job, _ = read_folder(vault, tmp_path, n=2, runner=FakeTicketRunner(status="blocked", message="T-0001 is blocked", write=write))
    assert job.wiki_status == "failed"
    told = notices.take(vault)[0]
    assert "Pages written for: lease0.pdf." in told and "No page yet: lease1.pdf." in told
    assert told.index("couldn't write all their wiki pages") < told.index("Pages written for")
    assert told.endswith('Say "finish the wiki pages" to write the rest.')
