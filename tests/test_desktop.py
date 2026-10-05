"""The Mac notification banner: one osascript call, quotes escaped, never a failure."""
import subprocess

from bron import desktop


def test_a_banner_is_one_osascript_call_with_its_quotes_escaped(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    calls = []
    desktop.show('The "Leases" folder is in the wiki\n(3 documents, 2 min 5 s).', run=lambda args, **kw: calls.append(args))
    assert calls == [["/usr/bin/osascript", "-e",
                      'display notification "The \\"Leases\\" folder is in the wiki (3 documents, 2 min 5 s)." '
                      'with title "Bron"']]


def test_no_banner_off_a_mac(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    calls = []
    desktop.show("Done.", run=lambda args, **kw: calls.append(args))
    assert calls == []


def test_a_banner_that_cannot_be_shown_never_fails_the_work(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "darwin")

    def broken(args, **kw):
        raise subprocess.TimeoutExpired(args, 5)

    desktop.show("Done.", run=broken)
