import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from bron import background, cli as bron_cli
from bron.kb import cli as kb_cli, embed, service, tools
from bron.kb.store import KbError
from bron.vault import Vault
from kbkit import fake_embed
from test_kb_search import add


@pytest.fixture
def short_home(monkeypatch):
    home = Path(tempfile.mkdtemp(prefix="bh", dir="/tmp"))
    monkeypatch.setenv("HOME", str(home))
    yield home
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def helper(vault, monkeypatch):
    monkeypatch.setattr(service, "EMBEDDER_FACTORY", lambda v: fake_embed)
    running = []

    def start(idle=2.0, v=None, wait=True):
        v = v or vault
        stop = threading.Event()
        t = threading.Thread(target=service.serve, args=(v,), kwargs={"idle": idle, "stop": stop}, daemon=True)
        t.start()
        t.stop = stop
        running.append((t, stop, v))
        if wait:
            for _ in range(150):
                if service.ping(v):
                    return t
                time.sleep(0.02)
            raise AssertionError("helper did not start")
        return t

    yield start
    for t, stop, v in running:
        stop.set()
        t.join(5)
        assert not t.is_alive()
    for _, _, v in running:
        assert not service.socket_path(v).exists()


def test_query_returns_hits(vault, helper):
    d = add(vault, "a", ["The liquidation preference is one times."])
    helper()
    reply = service.query(vault, {"query": "liquidation", "limit": 3}, start=False)
    assert reply["hits"][0]["doc_id"] == d.doc_id and reply["hits"][0]["page"] == 1
    assert reply["keyword_only"] is False


def test_filters_pass_through(vault, helper):
    add(vault, "a", ["share price clause"], company="Beta")
    helper()
    assert service.query(vault, {"query": "share price", "company": "nobody"}, start=False)["hits"] == []


def test_idle_exit(vault, helper):
    t = helper(idle=0.3)
    t.join(3)
    assert not t.is_alive()
    assert service.query(vault, {"query": "x"}, start=False) is None


def test_exits_when_version_changes(vault, helper):
    (vault.core / "VERSION").write_text("1.0.0\n")
    t = helper(idle=60)
    (vault.core / "VERSION").write_text("1.0.1\n")
    t.join(3)
    assert not t.is_alive()


def test_second_serve_exits_at_once(vault, helper):
    helper()
    other = helper(wait=False)
    other.join(3)
    assert not other.is_alive()
    assert service.ping(vault)


def test_two_serves_started_together_leave_exactly_one(vault, helper):
    a = helper(wait=False)
    b = helper(wait=False)
    time.sleep(0.8)
    assert [a.is_alive(), b.is_alive()].count(True) == 1
    assert service.ping(vault)
    assert service.query(vault, {"query": "x"}, start=False) is not None


def test_serve_during_slow_warm_up_exits_and_leaves_socket(vault, helper, monkeypatch):
    gate = threading.Event()

    class Slow:
        model = "fake-embedder"

        def embed(self, texts):
            gate.wait(5)
            return fake_embed.embed(texts)

    monkeypatch.setattr(service, "EMBEDDER_FACTORY", lambda v: Slow())
    add(vault, "a", ["liquidation terms"])
    helper()
    inode = service.socket_path(vault).stat().st_ino
    other = helper(wait=False)
    other.join(3)
    assert not other.is_alive()
    assert service.socket_path(vault).stat().st_ino == inode and service.ping(vault)
    assert service.query(vault, {"query": "liquidation"}, start=False) is None  # warming up: caller searches itself
    gate.set()
    for _ in range(100):
        reply = service.query(vault, {"query": "liquidation"}, start=False)
        if reply:
            break
        time.sleep(0.05)
    assert reply["hits"]


def test_stale_socket_file_is_recovered(vault, helper):
    path = service.socket_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.close()  # the file stays, nobody listens
    assert path.exists()
    helper()
    assert service.ping(vault)


def test_query_without_helper_and_no_start_is_none(vault):
    assert service.query(vault, {"query": "x"}, start=False) is None


def test_query_starts_helper_with_injected_spawn(vault):
    (vault.bron_dir / "bin").mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "bin" / "bron").write_text("#!/bin/sh\n")
    calls = []
    assert service.query(vault, {"query": "x"}, timeout=0.3, popen=lambda argv, **kw: calls.append((argv, kw))) is None
    assert calls[0][0][1:] == ["kb", "serve"] and calls[0][1]["start_new_session"] is True


def test_spawn_runs_in_ticket_runs_but_not_in_memory_jobs(vault, monkeypatch):
    (vault.bron_dir / "bin").mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "bin" / "bron").write_text("#!/bin/sh\n")
    calls = []
    monkeypatch.setenv("BRON_TICKET", "T-1")
    assert service.spawn(vault, popen=lambda *a, **k: calls.append(a)) is True and len(calls) == 1
    monkeypatch.setenv("BRON_MEMORY_JOB", "1")
    assert service.spawn(vault, popen=lambda *a, **k: calls.append(a)) is False and len(calls) == 1


def test_shared_background_spawn(vault):
    calls = []
    assert background.spawn_detached(vault, ["x"], "a.log", popen=lambda *a, **k: calls.append(a)) is False
    (vault.bron_dir / "bin").mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "bin" / "bron").write_text("#!/bin/sh\n")
    assert background.spawn_detached(vault, ["x", "y"], "a.log", popen=lambda argv, **kw: calls.append((argv, kw))) is True
    assert calls[0][0][1:] == ["x", "y"] and calls[0][1]["start_new_session"] is True
    assert (vault.bron_dir / "logs" / "a.log").exists()


LONG_VAULT = Vault(Path("/tmp") / ("v" * 120) / "Cofre Ágora")


def test_long_vault_path_socket_does_not_depend_on_tmpdir(monkeypatch, short_home):
    monkeypatch.delenv("BRON_KB_SOCKET_DIR", raising=False)
    monkeypatch.setenv("TMPDIR", "/tmp/one")
    first = service.socket_path(LONG_VAULT)
    monkeypatch.setenv("TMPDIR", "/tmp/two")
    assert service.socket_path(LONG_VAULT) == first
    assert first.parent == short_home / "Library" / "Caches" / "Bron" and first.name.startswith("kb-") and first.suffix == ".sock"


def test_socket_folder_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BRON_KB_SOCKET_DIR", str(tmp_path))
    path = service.socket_path(LONG_VAULT)
    assert path.parent == tmp_path and path.name.startswith("kb-")


def test_tests_run_with_a_private_socket_folder():
    folder = Path(os.environ["BRON_KB_SOCKET_DIR"])
    assert len(str(folder)) < 30 and str(folder).startswith("/tmp/") and not str(folder).startswith(os.path.expanduser("~"))


def test_serve_tightens_a_loose_socket_folder(vault, monkeypatch, tmp_path):
    loose = Path(tempfile.mkdtemp(prefix="bl", dir="/tmp"))
    try:
        os.chmod(loose, 0o755)
        monkeypatch.setenv("BRON_KB_SOCKET_DIR", str(loose))
        monkeypatch.setattr(service, "MAX_SOCKET_PATH", 10)
        monkeypatch.setattr(service, "EMBEDDER_FACTORY", lambda v: fake_embed)
        stop = threading.Event()
        stop.set()
        service.serve(vault, idle=1, stop=stop)
        assert (os.stat(loose).st_mode & 0o777) == 0o700
    finally:
        shutil.rmtree(loose, ignore_errors=True)


def test_unbindable_socket_path_is_a_quiet_exit(vault, monkeypatch, capsys):
    monkeypatch.setattr(service, "MAX_SOCKET_PATH", 10**6)  # the in-vault path is far too long to bind
    monkeypatch.setattr(service, "EMBEDDER_FACTORY", lambda v: fake_embed)
    service.serve(vault, idle=1)
    out = capsys.readouterr().out
    assert out.strip() and "Traceback" not in out and len(out.strip().splitlines()) == 1


def test_long_path_serves(vault, helper, monkeypatch, short_home):
    monkeypatch.setattr(service, "MAX_SOCKET_PATH", 10)
    add(vault, "a", ["liquidation terms"])
    helper()
    assert service.query(vault, {"query": "liquidation"}, start=False)["hits"]
    assert not (service.kb_dir(vault) / "serve.path").exists()


def test_short_vault_path_uses_socket_in_the_vault(helper, monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="bk", dir="/tmp"))
    try:
        short = Vault(root)
        assert service.socket_path(short) == root / ".bron" / "kb" / "serve.sock"
        t = helper(v=short)
        assert service.query(short, {"query": "x"}, start=False) == {"hits": [], "keyword_only": False}
        t.stop.set()
        t.join(5)
        assert not t.is_alive() and not service.socket_path(short).exists()  # serve removed it itself
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_copied_vault_never_gets_the_originals_hits(vault, helper, monkeypatch, tmp_path):
    add(vault, "a", ["liquidation terms"])
    helper()
    other = Vault(tmp_path / "copy")
    (other.bron_dir / "kb").mkdir(parents=True)
    original = service.socket_path(vault)
    monkeypatch.setattr(service, "socket_path", lambda v: original)
    assert service.query(other, {"query": "liquidation"}, start=False) is None
    assert service.query(vault, {"query": "liquidation"}, start=False)["hits"]


def test_foreign_owned_socket_is_refused_by_client_and_server(vault, helper, monkeypatch, capsys):
    helper()
    monkeypatch.setattr(service.os, "getuid", lambda: os.stat(service.socket_path(vault)).st_uid + 1)
    assert service.query(vault, {"query": "x"}, start=False) is None
    assert not service.ping(vault)


def test_server_refuses_to_replace_a_foreign_owned_socket(vault, monkeypatch, capsys):
    path = service.socket_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.close()
    monkeypatch.setattr(service, "EMBEDDER_FACTORY", lambda v: fake_embed)
    monkeypatch.setattr(service.os, "getuid", lambda: path.stat().st_uid + 1)
    service.serve(vault, idle=1)
    assert path.exists() and capsys.readouterr().out.strip()
    path.unlink()


def test_a_hung_helper_with_start_waits_once_and_spawns_nothing(vault, monkeypatch):
    monkeypatch.setattr(service, "REPLY_TIMEOUT", 0.3)
    (vault.bron_dir / "bin").mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "bin" / "bron").write_text("#!/bin/sh\n")
    path = service.socket_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.listen(1)
    calls = []
    try:
        began = time.monotonic()
        assert service.query(vault, {"query": "x"}, popen=lambda *a, **k: calls.append(a)) is None
        assert time.monotonic() - began < 1.5 and calls == []
    finally:
        s.close()
        path.unlink()


def test_a_warming_helper_with_start_returns_none_at_once_and_spawns_nothing(vault, helper, monkeypatch):
    gate = threading.Event()

    class Slow:
        model = "fake-embedder"

        def embed(self, texts):
            gate.wait(5)
            return fake_embed.embed(texts)

    monkeypatch.setattr(service, "EMBEDDER_FACTORY", lambda v: Slow())
    (vault.bron_dir / "bin").mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "bin" / "bron").write_text("#!/bin/sh\n")
    helper()
    calls = []
    began = time.monotonic()
    assert service.query(vault, {"query": "x"}, popen=lambda *a, **k: calls.append(a)) is None
    assert time.monotonic() - began < 1 and calls == []
    gate.set()


def test_nested_request_does_not_kill_the_helper(vault, helper):
    helper()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
        c.connect(str(service.socket_path(vault)))
        c.sendall(b"[" * 200000)
        c.shutdown(socket.SHUT_WR)
        c.recv(1000)
    assert service.ping(vault)


def test_a_hung_helper_does_not_hold_the_caller(vault, monkeypatch):
    monkeypatch.setattr(service, "REPLY_TIMEOUT", 0.3)
    path = service.socket_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    s.listen(1)  # accepts connections, never answers
    try:
        began = time.monotonic()
        assert service.query(vault, {"query": "x"}, start=False) is None
        assert time.monotonic() - began < 3
    finally:
        s.close()
        path.unlink()


def run_cli(vault, capsys, *argv):
    args = bron_cli.build_parser().parse_args(["kb", *argv])
    code = kb_cli.handle(args, vault)
    return code, capsys.readouterr().out


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(tools, "ensure", lambda vault, say=print: None)
    monkeypatch.setattr(service, "query", lambda *a, **k: None)
    monkeypatch.setattr(embed, "get", lambda vault: fake_embed)


def test_cli_falls_back_to_in_process_search(vault, offline, capsys):
    add(vault, "a", ["The liquidation preference is one times."])
    code, out = run_cli(vault, capsys, "search", "liquidation", "--company", "acme", "--type", "contract")
    assert code == 0 and "liquidation preference" in out and "keyword matches" not in out


def test_cli_nothing_found(vault, offline, capsys):
    add(vault, "a", ["board seats"])
    code, out = run_cli(vault, capsys, "search", "zzzz")
    assert "Nothing in the knowledge base matches that. Try other words, or check `bron kb list`." in out


def test_cli_keyword_only_note_when_embedder_fails(vault, offline, monkeypatch, capsys):
    add(vault, "a", ["The liquidation preference is one times."])

    class Broken:
        model = "fake-embedder"

        def embed(self, texts):
            raise KbError("The meaning-search model couldn't be loaded.")

    monkeypatch.setattr(embed, "get", lambda vault: Broken())
    code, out = run_cli(vault, capsys, "search", "liquidation")
    assert code == 0
    assert "Meaning search isn't available right now; these are keyword matches." in out
    assert "liquidation preference" in out


def test_cli_uses_helper_reply(vault, offline, monkeypatch, capsys):
    add(vault, "a", ["The liquidation preference is one times."])
    monkeypatch.setattr(service, "EMBEDDER_FACTORY", lambda v: fake_embed)
    reply = service._answer(vault, fake_embed, {"query": "liquidation", "vault": str(vault.root)})
    monkeypatch.setattr(service, "query", lambda *a, **k: reply)
    code, out = run_cli(vault, capsys, "search", "liquidation")
    assert code == 0 and "liquidation preference" in out and "/drive/a.pdf" in out


def test_kb_is_a_registered_command_and_serve_is_hidden():
    parser = bron_cli.build_parser()
    assert parser.parse_args(["kb", "serve"]).kb_command == "serve"
    help_text = parser._subparsers._group_actions[0].choices["kb"].format_help()
    assert "search" in help_text and "serve" not in help_text


def test_cli_shows_the_keyword_note_from_the_helper(vault, offline, monkeypatch, capsys):
    add(vault, "a", ["The liquidation preference is one times."])

    class Broken:
        model = "fake-embedder"

        def embed(self, texts):
            raise KbError("no model")

    reply = service._answer(vault, Broken(), {"query": "liquidation", "vault": str(vault.root)})
    assert reply["keyword_only"] is True
    monkeypatch.setattr(service, "query", lambda *a, **k: reply)
    code, out = run_cli(vault, capsys, "search", "liquidation")
    assert "keyword matches" in out and "liquidation preference" in out


def test_cli_without_tools_prints_a_plain_message(vault, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.delitem(sys.modules, "bron.kb.search", raising=False)

    def refuse(vault, say=print):
        raise KbError("The knowledge base tools couldn't be installed: no network.")

    monkeypatch.setattr(tools, "ensure", refuse)
    code, out = run_cli(vault, capsys, "search", "anything")
    assert code == 1 and "couldn't be installed" in out and "Traceback" not in out
